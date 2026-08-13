#!/usr/bin/env python3
"""MinIO orphan storage audit and optional cleanup for archive/submission files."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from minio.error import S3Error
from sqlalchemy import select

from app.core.config import settings
from app.db.init_db import validate_database_ready
from app.db.session import AsyncSessionLocal
from app.models.models import Archive, ArchiveSubmission, SubmissionStatus
from app.utils.storage import get_minio_client

KNOWN_PREFIXES = ("archives/", "archive-submissions/")
SIZE_1GB = 1024 * 1024 * 1024


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_prefix(key: str) -> str:
    for prefix in KNOWN_PREFIXES:
        if key.startswith(prefix):
            return "known"
    return "unknown"


def _is_empty_folder_marker(obj: Any) -> bool:
    return bool(getattr(obj, "is_dir", False)) or (
        getattr(obj, "size", None) == 0 and str(getattr(obj, "object_name", "")).endswith("/")
    )


async def _collect_db_refs() -> dict[str, dict[str, list[dict[str, Any]]]]:
    async with AsyncSessionLocal() as db:
        archive_rows = (await db.execute(select(Archive.id, Archive.object_name, Archive.deleted_at))).all()
        submission_rows = (
            await db.execute(
                select(
                    ArchiveSubmission.id,
                    ArchiveSubmission.object_name,
                    ArchiveSubmission.deleted_at,
                    ArchiveSubmission.status,
                )
            )
        ).all()

    refs: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"active": [], "trashed": []})

    for row in archive_rows:
        object_name = row.object_name
        if not object_name:
            continue
        refs[object_name]["trashed" if row.deleted_at is not None else "active"].append(
            {"type": "archive", "id": row.id}
        )

    for row in submission_rows:
        object_name = row.object_name
        if not object_name:
            continue
        is_trashed = row.deleted_at is not None or row.status == SubmissionStatus.DELETED
        refs[object_name]["trashed" if is_trashed else "active"].append(
            {"type": "archive_submission", "id": row.id, "status": row.status.value}
        )

    return refs


async def run_audit() -> dict[str, Any]:
    db_refs = await _collect_db_refs()
    object_to_refs = db_refs

    client = get_minio_client()
    objects = list(client.list_objects(settings.MINIO_BUCKET_NAME, recursive=True))

    referenced_active = []
    referenced_trashed = []
    orphan_objects = []
    unknown_prefix = []
    empty_folder_markers = []

    seen_objects = set()
    for obj in objects:
        key = obj.object_name
        seen_objects.add(key)
        size = int(obj.size) if getattr(obj, "size", None) is not None else None
        modified = getattr(obj, "last_modified", None).isoformat() if getattr(obj, "last_modified", None) else None

        if _is_empty_folder_marker(obj):
            if _normalize_prefix(key) == "known":
                empty_folder_markers.append({"key": key, "size": size, "last_modified": modified, "reason": "empty folder marker"})
            else:
                unknown_prefix.append({"key": key, "size": size, "last_modified": modified, "reason": "unknown prefix marker"})
            continue

        prefix_type = _normalize_prefix(key)
        if key in object_to_refs:
            if object_to_refs[key]["active"]:
                referenced_active.append({
                    "key": key,
                    "size": size,
                    "last_modified": modified,
                    "referenced_by": object_to_refs[key]["active"],
                })
            elif object_to_refs[key]["trashed"]:
                referenced_trashed.append({
                    "key": key,
                    "size": size,
                    "last_modified": modified,
                    "referenced_by": object_to_refs[key]["trashed"],
                })
            else:
                # Defensive fallback.
                referenced_trashed.append({
                    "key": key,
                    "size": size,
                    "last_modified": modified,
                    "referenced_by": [],
                })
            continue

        if prefix_type == "known":
            orphan_objects.append({"key": key, "size": size, "last_modified": modified})
        else:
            unknown_prefix.append({"key": key, "size": size, "last_modified": modified})

    missing_object = []
    for object_name, refs in object_to_refs.items():
        if object_name in seen_objects:
            continue
        if object_name:
            if refs["active"]:
                category = "active"
            elif refs["trashed"]:
                category = "trashed"
            else:
                category = "unknown"
            missing_object.append({"key": object_name, "category": category, "referenced_by": refs["active"] or refs["trashed"]})

    return {
        "generated_at": _utcnow(),
        "bucket": settings.MINIO_BUCKET_NAME,
        "summary": {
            "total_objects": len(objects),
            "referenced_active_count": len(referenced_active),
            "referenced_trashed_count": len(referenced_trashed),
            "orphan_object_count": len(orphan_objects),
            "missing_object_count": len(missing_object),
            "unknown_prefix_count": len(unknown_prefix),
            "empty_folder_marker_count": len(empty_folder_markers),
            "db_referenced_object_count": len(object_to_refs),
            "orphan_total_size": sum(item.get("size") or 0 for item in orphan_objects),
            "unknown_total_size": sum(item.get("size") or 0 for item in unknown_prefix),
        },
        "referenced_active": referenced_active,
        "referenced_trashed": referenced_trashed,
        "orphan_objects": orphan_objects,
        "missing_object": missing_object,
        "unknown_prefix": unknown_prefix,
        "empty_folder_markers": empty_folder_markers,
    }


async def run_cleanup(
    *,
    max_orphans: int = 200,
    max_orphan_bytes: int = SIZE_1GB,
    apply: bool = False,
    confirmed_database_name: str | None = None,
    confirmed_bucket_name: str | None = None,
) -> dict[str, Any]:
    if apply:
        if confirmed_database_name != settings.DB_NAME:
            raise RuntimeError(
                "Object cleanup database confirmation does not match"
            )
        if confirmed_bucket_name != settings.MINIO_BUCKET_NAME:
            raise RuntimeError("Object cleanup bucket confirmation does not match")
        # A missing ledger, revision mismatch, or schema drift must stop object
        # deletion before the candidate list is even evaluated.
        await asyncio.to_thread(validate_database_ready)

    audit = await run_audit()
    candidate = [item for item in audit["orphan_objects"] if item.get("key")]
    candidate_with_reason = [
        {
            **item,
            "reason": "not referenced by any DB file record",
        }
        for item in candidate
    ]

    manifest = {
        "generated_at": _utcnow(),
        "bucket": settings.MINIO_BUCKET_NAME,
        "apply": apply,
        "candidates": candidate_with_reason,
        "candidate_count": len(candidate_with_reason),
        "candidate_total_size": sum(item.get("size") or 0 for item in candidate_with_reason),
        "deletions": [],
        "warnings": [],
        "summary": {
            "before": audit["summary"],
            "after": None,
            "deleted_count": 0,
            "deleted_total_size": 0,
        },
    }

    if not apply:
        return manifest

    if manifest["candidate_count"] > max_orphans or manifest["candidate_total_size"] > max_orphan_bytes:
        manifest["warnings"].append(
            f"Deletion skipped: candidate_count={manifest['candidate_count']} or candidate_total_size={manifest['candidate_total_size']} exceeds limits."
        )
        return manifest

    client = get_minio_client()
    deleted = 0
    deleted_size = 0
    for item in candidate:
        key = item["key"]
        try:
            client.remove_object(settings.MINIO_BUCKET_NAME, key)
            deleted += 1
            deleted_size += int(item.get("size") or 0)
            manifest["deletions"].append({"key": key, "status": "deleted"})
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                manifest["deletions"].append({"key": key, "status": "missing", "error": str(exc)})
            else:
                manifest["deletions"].append({"key": key, "status": "warning", "error": str(exc)})
                manifest["warnings"].append(str(exc))
        except Exception as exc:
            manifest["deletions"].append({"key": key, "status": "warning", "error": str(exc)})
            manifest["warnings"].append(str(exc))

    manifest["summary"]["deleted_count"] = deleted
    manifest["summary"]["deleted_total_size"] = deleted_size

    audit_after = await run_audit()
    manifest["summary"]["after"] = audit_after["summary"]
    return manifest


def _dump(path: str, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit/cleanup orphan objects in MinIO.")
    parser.add_argument("--dry-run", action="store_true", help="Only audit, do not delete")
    parser.add_argument("--apply", action="store_true", help="Delete confirmed orphan objects")
    parser.add_argument(
        "--confirm-database-name",
        help="Required with --apply; must exactly match DB_NAME",
    )
    parser.add_argument(
        "--confirm-bucket-name",
        help="Required with --apply; must exactly match MINIO_BUCKET_NAME",
    )
    parser.add_argument("--max-orphans", type=int, default=200, help="Safety threshold for number of candidates")
    parser.add_argument("--max-orphan-bytes", type=int, default=SIZE_1GB, help="Safety threshold for total orphan bytes")
    parser.add_argument("--out", type=str, default="/tmp/pastexam-minio-audit-before.json", help="Audit report output path")
    parser.add_argument("--manifest", type=str, default="/tmp/pastexam-minio-orphans-to-delete.json", help="Cleanup manifest path")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if args.apply:
        result = await run_cleanup(
            max_orphans=args.max_orphans,
            max_orphan_bytes=args.max_orphan_bytes,
            apply=True,
            confirmed_database_name=args.confirm_database_name,
            confirmed_bucket_name=args.confirm_bucket_name,
        )
        _dump(args.out, result)
        _dump(
            args.manifest,
            {
                "generated_at": result["generated_at"],
                "object_count": len(result.get("candidates", [])),
                "candidates": result.get("candidates", []),
            },
        )
        print(f"Cleanup complete. Report: {args.out}, manifest: {args.manifest}")
    else:
        result = await run_audit()
        _dump(args.out, result)
        candidates_with_reason = [
            {
                **item,
                "reason": "not referenced by any DB file record",
            }
            for item in result.get("orphan_objects", [])
            if item.get("key")
        ]
        manifest = {
            "generated_at": result["generated_at"],
            "object_count": len(candidates_with_reason),
            "candidates": candidates_with_reason,
        }
        _dump(args.manifest, manifest)
        print(f"Dry-run complete. Audit: {args.out}, manifest: {args.manifest}")


if __name__ == "__main__":
    asyncio.run(main())
