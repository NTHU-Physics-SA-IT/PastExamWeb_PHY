from __future__ import annotations

import json

from app.db.schema_manifests import (
    HEAD_SCHEMA_REVISION,
    get_manifest_spec,
    reviewed_manifest_revisions,
)


def test_reviewed_manifest_registry_has_required_revisions() -> None:
    assert HEAD_SCHEMA_REVISION == "a7c3e9f1b5d2"
    assert reviewed_manifest_revisions() == (
        "c4d8e2f1a6b9",
        "a4c7e9d2f6b1",
        "c9e4f1a7b2d6",
        "e3b7c1d9f5a2",
        "a7c3e9f1b5d2",
    )


def test_recovery_manifest_is_versioned_and_revision_bound() -> None:
    spec = get_manifest_spec("c4d8e2f1a6b9")
    assert spec is not None
    assert spec.snapshot_path is not None
    payload = json.loads(spec.snapshot_path.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == 1
    assert payload["revision"] == spec.revision
    assert payload["schema"]["tables"]
    assert payload["schema"]["enums"]
