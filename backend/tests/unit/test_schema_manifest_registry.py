from __future__ import annotations

import json

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.schema import CreateTable

from app.db.migration_safety import metadata_for_revision
from app.db.schema_manifests import (
    HEAD_SCHEMA_REVISION,
    get_manifest_spec,
    reviewed_manifest_revisions,
)
from app.models.models import ArchiveSubmission, User


def test_reviewed_manifest_registry_has_required_revisions() -> None:
    assert HEAD_SCHEMA_REVISION == "e8a4c1d7b2f6"
    assert reviewed_manifest_revisions() == (
        "c4d8e2f1a6b9",
        "a4c7e9d2f6b1",
        "c9e4f1a7b2d6",
        "e3b7c1d9f5a2",
        "a7c3e9f1b5d2",
        "f5e1d8c3a7b2",
        "d8f2a6c1b4e7",
        "6f3a9c2d8e41",
        "9f1c2a7e4b63",
        "b7e3d9a1c5f2",
        "c2a8e4f6b9d1",
        "d4b7e2a9c6f1",
        "e6a1b3c5d7f9",
        "e8a4c1d7b2f6",
    )
    assert get_manifest_spec("d4b7e2a9c6f1").metadata_variant == (
        "pre_about_us_entries"
    )
    assert get_manifest_spec("e6a1b3c5d7f9").metadata_variant == (
        "pre_category_state_preservation"
    )
    assert get_manifest_spec("e8a4c1d7b2f6").metadata_variant == "head"


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
    previous_status_column = "previous_status"
    constraint_name = "uq_archive_submissions_created_archive_id"
    head = metadata_for_revision("e8a4c1d7b2f6")
    pre_category_state = metadata_for_revision("e6a1b3c5d7f9")
    pre_about_us = metadata_for_revision("d4b7e2a9c6f1")
    pre_bilingual_snapshots = metadata_for_revision("c2a8e4f6b9d1")
    pre_bilingual_catalog = metadata_for_revision("b7e3d9a1c5f2")
    pre_student_id = metadata_for_revision("9f1c2a7e4b63")
    previous_head = metadata_for_revision("6f3a9c2d8e41")
    d8 = metadata_for_revision("d8f2a6c1b4e7")
    f5 = metadata_for_revision("f5e1d8c3a7b2")
    a7 = metadata_for_revision("a7c3e9f1b5d2")
    e3 = metadata_for_revision("e3b7c1d9f5a2")
    c9 = metadata_for_revision("c9e4f1a7b2d6")
    a4 = metadata_for_revision("a4c7e9d2f6b1")

    assert head is not None
    assert pre_category_state is not None
    assert pre_about_us is not None
    assert "about_us_entries" in head.tables
    assert "about_us_entries" in pre_category_state.tables
    assert "about_us_entries" not in pre_about_us.tables
    assert pre_bilingual_snapshots is not None
    assert pre_bilingual_catalog is not None
    assert pre_student_id is not None
    assert previous_head is not None
    assert d8 is not None
    assert f5 is not None
    assert a7 is not None
    assert e3 is not None
    assert c9 is not None
    assert a4 is not None

    assert column_name in head.tables["archive_submissions"].c
    assert "student_id" in head.tables["users"].c
    assert "name_en" in head.tables["courses"].c
    assert "name_en" in head.tables["course_category_configs"].c
    assert "pre_delete_is_active" in head.tables["course_category_configs"].c
    assert (
        "pre_delete_is_active"
        not in pre_category_state.tables["course_category_configs"].c
    )
    assert (
        "pre_delete_is_active"
        not in pre_about_us.tables["course_category_configs"].c
    )
    assert "label_en" in head.tables["course_category_configs"].c
    for bilingual_snapshot_column in (
        "requested_course_name_en",
        "requested_category_name_en",
        "requested_category_label_en",
    ):
        assert bilingual_snapshot_column in head.tables["archive_submissions"].c
        assert (
            bilingual_snapshot_column
            not in pre_bilingual_snapshots.tables["archive_submissions"].c
        )
        assert (
            bilingual_snapshot_column
            not in pre_bilingual_catalog.tables["archive_submissions"].c
        )
    assert "name_en" in pre_bilingual_snapshots.tables["courses"].c
    assert "name_en" in pre_bilingual_snapshots.tables["course_category_configs"].c
    assert "label_en" in pre_bilingual_snapshots.tables["course_category_configs"].c
    assert "name_en" not in pre_bilingual_catalog.tables["courses"].c
    assert "name_en" not in pre_bilingual_catalog.tables["course_category_configs"].c
    assert "label_en" not in pre_bilingual_catalog.tables["course_category_configs"].c
    assert "student_id" not in pre_student_id.tables["users"].c
    assert previous_status_column in head.tables["archive_submissions"].c
    assert "archive_reports" in head.tables
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == constraint_name
        and tuple(constraint.columns.keys()) == ("created_archive_id",)
        for constraint in head.tables["archive_submissions"].constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_users_oauth_provider_sub"
        and tuple(constraint.columns.keys()) == ("oauth_provider", "oauth_sub")
        for constraint in head.tables["users"].constraints
    )
    assert all(
        constraint.name != "uq_users_oauth_provider_sub"
        for constraint in previous_head.tables["users"].constraints
    )

    assert column_name in d8.tables["archive_submissions"].c
    assert previous_status_column in d8.tables["archive_submissions"].c
    assert "archive_reports" in d8.tables
    assert all(
        constraint.name != constraint_name
        for constraint in d8.tables["archive_submissions"].constraints
    )

    assert column_name in f5.tables["archive_submissions"].c
    assert previous_status_column not in f5.tables["archive_submissions"].c
    assert "archive_reports" in f5.tables

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
    rebuilt_head = metadata_for_revision("e8a4c1d7b2f6")
    assert rebuilt_head is not None
    assert column_name in rebuilt_head.tables["archive_submissions"].c
    assert previous_status_column in rebuilt_head.tables["archive_submissions"].c
    assert "archive_reports" in rebuilt_head.tables
    assert "student_id" in rebuilt_head.tables["users"].c
    assert any(
        constraint.name == constraint_name
        for constraint in rebuilt_head.tables["archive_submissions"].constraints
    )


def test_nthu_identity_constraint_compiles_for_nullable_local_accounts() -> None:
    statement = str(CreateTable(User.__table__).compile(dialect=sqlite_dialect()))

    assert "CONSTRAINT uq_users_oauth_provider_sub" in statement
    assert "UNIQUE (oauth_provider, oauth_sub)" in statement


def test_one_to_one_constraint_compiles_for_sqlite_metadata_neighbors() -> None:
    statement = str(
        CreateTable(ArchiveSubmission.__table__).compile(
            dialect=sqlite_dialect(),
        )
    )

    assert "CONSTRAINT uq_archive_submissions_created_archive_id" in statement
    assert "UNIQUE (created_archive_id)" in statement
