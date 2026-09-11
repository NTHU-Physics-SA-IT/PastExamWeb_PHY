#!/usr/bin/env python3
"""Validate and retain only fixed production framework installation evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_KEYS = {"schema_version", "source_sha", "outcome", "installed_files"}
COMPONENTS = (
    ("deployment-controller", "0755"),
    ("activation-wrapper", "0755"),
    ("activation-engine", "0700"),
    ("activation-contract", "0700"),
    ("postgres-backup", "0700"),
    ("minio-preflight", "0700"),
    ("minio-manifest", "0700"),
    ("nginx-override", "0600"),
    ("maintenance-wrapper", "0755"),
    ("maintenance-helper", "0700"),
)


class EvidenceError(RuntimeError):
    """Installation evidence is malformed or disagrees with authority."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Installation evidence contains duplicate keys.")
        result[key] = value
    return result


def validate(payload: Any, expected_sha: str) -> dict[str, Any]:
    if SHA.fullmatch(expected_sha) is None:
        raise EvidenceError("Expected source SHA is malformed.")
    if not isinstance(payload, dict) or set(payload) != EVIDENCE_KEYS:
        raise EvidenceError("Installation evidence schema is invalid.")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or not isinstance(payload["source_sha"], str)
        or payload["source_sha"] != expected_sha
        or not isinstance(payload["outcome"], str)
        or payload["outcome"] != "installed"
        or not isinstance(payload["installed_files"], list)
    ):
        raise EvidenceError("Installation evidence authority disagrees.")
    expected = dict(COMPONENTS)
    observed: list[str] = []
    for item in payload["installed_files"]:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "sha256",
            "uid",
            "gid",
            "mode",
        }:
            raise EvidenceError("Installed component evidence is invalid.")
        component_id = item["id"]
        if (
            not isinstance(component_id, str)
            or component_id not in expected
            or component_id in observed
        ):
            raise EvidenceError("Installed component identifier is invalid.")
        if (
            not isinstance(item["sha256"], str)
            or DIGEST.fullmatch(item["sha256"]) is None
            or type(item["uid"]) is not int
            or type(item["gid"]) is not int
            or item["uid"] != 0
            or item["gid"] != 0
            or item["mode"] != expected[component_id]
        ):
            raise EvidenceError("Installed component integrity is invalid.")
        observed.append(component_id)
    if observed != [item[0] for item in COMPONENTS]:
        raise EvidenceError("Installed component set is incomplete.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(
            args.input.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
        validated = validate(payload, args.expected_sha)
        temporary = args.output.with_name(f".{args.output.name}.partial-{os.getpid()}")
        temporary.write_text(
            json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, args.output)
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceError):
        print(
            "Production framework installation evidence failed validation.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
