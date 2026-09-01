"""Validate a privacy-safe immutable production-candidate receipt."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ALLOWED_FIELDS = {
    "schema_version",
    "kind",
    "source_sha",
    "workflow_run_id",
    "workflow_run_attempt",
    "source_ci_run_id",
    "source_ci_run_attempt",
    "prepared_at",
    "image_digests",
    "package_sha256",
    "release_files_sha256",
    "release_manifest_sha256",
    "release_id",
    "release_path",
    "outcome",
}


class ReceiptError(ValueError):
    """The candidate receipt does not match its immutable authority."""


def validate_receipt(data: object, expected: dict[str, str]) -> None:
    if not isinstance(data, dict) or set(data) != ALLOWED_FIELDS:
        raise ReceiptError("Candidate receipt has an unexpected schema.")
    sha = expected["release_sha"]
    fixed = {
        "schema_version": 1,
        "kind": "production-candidate-preparation",
        "source_sha": sha,
        "image_digests": {
            "frontend": expected["frontend_digest"],
            "backend": expected["backend_digest"],
            "nginx": expected["nginx_digest"],
        },
        "package_sha256": expected["source_archive_sha256"],
        "release_files_sha256": expected["release_files_sha256"],
        "release_id": sha,
        "release_path": f"releases/{sha}",
        "outcome": "verified",
    }
    for key, value in fixed.items():
        if data.get(key) != value:
            raise ReceiptError(f"Candidate receipt field {key} does not match.")
    for key in (
        "workflow_run_id",
        "workflow_run_attempt",
        "source_ci_run_id",
        "source_ci_run_attempt",
    ):
        if not isinstance(data.get(key), int) or data[key] < 1:
            raise ReceiptError(f"Candidate receipt field {key} is invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data["release_manifest_sha256"])):
        raise ReceiptError("Candidate receipt manifest checksum is invalid.")
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(data["prepared_at"])
    ):
        raise ReceiptError("Candidate receipt timestamp is invalid.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--frontend-digest", required=True)
    parser.add_argument("--backend-digest", required=True)
    parser.add_argument("--nginx-digest", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument("--release-files-sha256", required=True)
    args = parser.parse_args()
    data = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_receipt(
        data,
        {
            "release_sha": args.release_sha,
            "frontend_digest": args.frontend_digest,
            "backend_digest": args.backend_digest,
            "nginx_digest": args.nginx_digest,
            "source_archive_sha256": args.source_archive_sha256,
            "release_files_sha256": args.release_files_sha256,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
