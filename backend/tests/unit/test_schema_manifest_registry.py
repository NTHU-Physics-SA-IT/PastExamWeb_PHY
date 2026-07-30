from __future__ import annotations

import json

from app.db.schema_manifests import (
    HEAD_SCHEMA_REVISION,
    get_manifest_spec,
    reviewed_manifest_revisions,
)
from app.db.migration_safety import metadata_for_revision


def test_reviewed_manifest_registry_has_required_revisions() -> None:
    assert HEAD_SCHEMA_REVISION == "f5e1d8c3a7b2"
    assert reviewed_manifest_revisions() == (
        "c4d8e2f1a6b9",
        "a4c7e9d2f6b1",
        "c9e4f1a7b2d6",
        "e3b7c1d9f5a2",
        "a7c3e9f1b5d2",
        "f5e1d8c3a7b2",
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


def test_model_derived_manifest_variants_are_cumulative_and_isolated() -> None:
    column_name = "owner_self_delete_consumed"
    head = metadata_for_revision("f5e1d8c3a7b2")
    a7 = metadata_for_revision("a7c3e9f1b5d2")
    e3 = metadata_for_revision("e3b7c1d9f5a2")
    c9 = metadata_for_revision("c9e4f1a7b2d6")
    a4 = metadata_for_revision("a4c7e9d2f6b1")

    assert head is not None
    assert a7 is not None
    assert e3 is not None
    assert c9 is not None
    assert a4 is not None

    assert column_name in head.tables["archive_submissions"].c
    assert "archive_reports" in head.tables

    assert column_name not in a7.tables["archive_submissions"].c
    assert "archive_reports" in a7.tables

    assert column_name not in e3.tables["archive_submissions"].c
    assert "archive_reports" not in e3.tables
    for table_name in ("courses", "course_submissions", "archive_submissions"):
        assert any(
            tuple(index.columns.keys()) == ("category",)
            for index in e3.tables[table_name].indexes
        )

    for metadata in (c9, a4):
        assert column_name not in metadata.tables["archive_submissions"].c
        assert "archive_reports" not in metadata.tables
        for table_name in (
            "courses",
            "course_submissions",
            "archive_submissions",
        ):
            assert all(
                tuple(index.columns.keys()) != ("category",)
                for index in metadata.tables[table_name].indexes
            )

    category_config = a4.tables["course_category_configs"]
    assert all(
        index.name
        not in {
            "uq_course_category_configs_normalized_name",
            "uq_course_category_configs_normalized_key",
        }
        for index in category_config.indexes
    )
    assert all(
        constraint.name != "ck_course_category_configs_no_legacy_key"
        for constraint in category_config.constraints
    )

    # Building older variants must never mutate current SQLModel metadata.
    rebuilt_head = metadata_for_revision("f5e1d8c3a7b2")
    assert rebuilt_head is not None
    assert column_name in rebuilt_head.tables["archive_submissions"].c
    assert "archive_reports" in rebuilt_head.tables
