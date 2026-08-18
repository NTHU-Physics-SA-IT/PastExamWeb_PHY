from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import settings
from app.db.audit.registry import (
    ELIGIBILITY_AUDIT_ID,
    get_audit_adapter,
)
from app.db.migration_safety import (
    alembic_config,
    metadata_for_revision,
    revision_graph,
)
from app.db.schema_manifests import HEAD_SCHEMA_REVISION
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)
from app.models.models import (
    ArchiveSubmission,
    ArchiveSubmissionActionRead,
    ArchiveSubmissionAdminRead,
    ArchiveSubmissionRead,
)

PREVIOUS_REVISION = "f5e1d8c3a7b2"
NEW_REVISION = "d8f2a6c1b4e7"
NEXT_REVISION = "6f3a9c2d8e41"
COLUMN_NAME = "previous_status"
NOT_DELETED_CONSTRAINT = "ck_archive_submissions_previous_status_not_deleted"
ACTIVE_NULL_CONSTRAINT = "ck_archive_submissions_active_previous_status_null"
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def migration_engine(monkeypatch: pytest.MonkeyPatch) -> Engine:
    test_database_url = os.environ["TEST_DATABASE_URL"]
    test_url = make_url(test_database_url)
    runtime_url = alembic_config().get_main_option("sqlalchemy.url")
    target = validate_test_database_target(
        test_database_url=test_database_url,
        runtime_database_url=runtime_url,
        isolation_confirmed=os.environ.get("PASTEXAM_TEST_DATABASE_ISOLATED"),
        allowed_hosts=os.environ.get(
            "TEST_DATABASE_ALLOWED_HOSTS",
            "127.0.0.1,localhost,db",
        ).split(","),
    )
    original_settings = {
        "DB_HOST": settings.DB_HOST,
        "DB_PORT": settings.DB_PORT,
        "DB_USER": settings.DB_USER,
        "DB_PASSWORD": settings.DB_PASSWORD,
        "DB_NAME": settings.DB_NAME,
    }
    monkeypatch.setattr(settings, "DB_HOST", test_url.host)
    monkeypatch.setattr(settings, "DB_PORT", test_url.port)
    monkeypatch.setattr(settings, "DB_USER", test_url.username)
    monkeypatch.setattr(settings, "DB_PASSWORD", test_url.password)
    monkeypatch.setattr(settings, "DB_NAME", target.database_name)

    config = alembic_config()
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        identity = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "pg_get_userbyid(database.datdba), "
                "role.rolsuper, role.rolcreatedb, role.rolcreaterole "
                "FROM pg_database AS database "
                "JOIN pg_roles AS role ON role.rolname = current_user "
                "WHERE database.datname = current_database()"
            )
        ).one()
        validate_connected_test_database(
            actual_database_name=identity[0],
            actual_user_name=identity[1],
            actual_database_owner=identity[2],
            is_superuser=identity[3],
            can_create_database=identity[4],
            can_create_role=identity[5],
            target=target,
        )
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(config, PREVIOUS_REVISION)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(config, "head")
        for setting_name, setting_value in original_settings.items():
            setattr(settings, setting_name, setting_value)
        engine.dispose()


def _reset_empty(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _insert_user(
    engine: Engine,
    *,
    suffix: str,
    is_admin: bool = False,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO users (email, name, is_admin, is_local)
                    VALUES (:email, :name, :is_admin, true)
                    RETURNING id
                    """
                ),
                {
                    "email": f"{suffix}@example.invalid",
                    "name": f"previous-status-{suffix}",
                    "is_admin": is_admin,
                },
            )
        )


def _insert_archive(engine: Engine, *, suffix: str) -> int:
    with engine.begin() as connection:
        course_id = int(
            connection.scalar(
                text(
                    """
                    INSERT INTO courses (name, category, order_index)
                    VALUES (:name, 'fundamental', 0)
                    RETURNING id
                    """
                ),
                {"name": f"previous-status-course-{suffix}"},
            )
        )
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archives (
                        name, academic_year, archive_type, professor,
                        has_answers, download_count, object_name, course_id,
                        created_at, updated_at
                    )
                    VALUES (
                        :name, 115, 'FINAL', 'Previous Status Professor',
                        false, 0, :object_name, :course_id, :now, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "name": f"previous-status-archive-{suffix}",
                    "object_name": f"previous-status-archive-{suffix}.pdf",
                    "course_id": course_id,
                    "now": NOW,
                },
            )
        )


def _insert_submission(
    engine: Engine,
    *,
    suffix: str,
    requester_id: int,
    status: str = "PENDING",
    deleted_by_id: int | None = None,
    delete_reason: str | None = None,
    lifecycle_reason: str | None = None,
    created_archive_id: int | None = None,
) -> int:
    is_deleted = status == "DELETED"
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archive_submissions (
                        subject, category, name, academic_year, archive_type,
                        professor, has_answers, object_name, status,
                        requester_id, lifecycle_reason, created_archive_id,
                        deleted_at, deleted_by_id, delete_reason, created_at
                    )
                    VALUES (
                        :subject, 'fundamental', :name, 115, 'FINAL',
                        'Previous Status Professor', false, :object_name,
                        CAST(:status AS submissionstatus), :requester_id,
                        :lifecycle_reason, :created_archive_id,
                        CASE WHEN :is_deleted THEN :now ELSE NULL END,
                        :deleted_by_id, :delete_reason, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "subject": f"previous-status-{suffix}",
                    "name": f"previous-status-{suffix}",
                    "object_name": f"previous-status-{suffix}.pdf",
                    "status": status,
                    "requester_id": requester_id,
                    "lifecycle_reason": lifecycle_reason,
                    "created_archive_id": created_archive_id,
                    "is_deleted": is_deleted,
                    "deleted_by_id": deleted_by_id,
                    "delete_reason": delete_reason,
                    "now": NOW,
                },
            )
        )


def _source_snapshot(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        id, status::text AS status, deleted_at, deleted_by_id,
                        delete_reason, lifecycle_reason, created_archive_id,
                        owner_self_delete_consumed
                    FROM archive_submissions
                    ORDER BY id
                    """
                )
            ).mappings()
        ]


def _previous_statuses(engine: Engine) -> dict[int, str | None]:
    with engine.connect() as connection:
        return {
            int(row.id): row.previous_status
            for row in connection.execute(
                text(
                    """
                    SELECT id, previous_status::text AS previous_status
                    FROM archive_submissions
                    ORDER BY id
                    """
                )
            )
        }


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def test_model_manifest_and_response_boundary_define_previous_status() -> None:
    column = ArchiveSubmission.__table__.c[COLUMN_NAME]
    assert column.nullable is True
    assert column.type.name == "submissionstatus"
    assert set(column.type.enums) == {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "DELETED",
        "TAKEDOWN",
    }
    assert HEAD_SCHEMA_REVISION == "a9c4e7b2d6f1"

    source_metadata = metadata_for_revision(PREVIOUS_REVISION)
    head_metadata = metadata_for_revision(NEW_REVISION)
    assert source_metadata is not None
    assert head_metadata is not None
    assert COLUMN_NAME not in source_metadata.tables["archive_submissions"].c
    assert COLUMN_NAME in head_metadata.tables["archive_submissions"].c

    for schema in (
        ArchiveSubmissionRead,
        ArchiveSubmissionAdminRead,
        ArchiveSubmissionActionRead,
    ):
        assert COLUMN_NAME not in schema.model_fields


def test_new_revision_remains_between_f5_and_its_successor() -> None:
    script, heads = revision_graph()

    assert heads == [HEAD_SCHEMA_REVISION]
    assert script.get_revision(NEW_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(NEXT_REVISION).down_revision == NEW_REVISION


def test_fresh_upgrade_adds_nullable_typed_column_without_index(
    migration_engine: Engine,
) -> None:
    _reset_empty(migration_engine)
    command.upgrade(alembic_config(), NEW_REVISION)

    with migration_engine.connect() as connection:
        inspector = sa_inspect(connection)
        column = {
            item["name"]: item
            for item in inspector.get_columns(
                "archive_submissions",
                schema="public",
            )
        }[COLUMN_NAME]
        checks = {
            item["name"]
            for item in inspector.get_check_constraints(
                "archive_submissions",
                schema="public",
            )
        }
        indexes = inspector.get_indexes("archive_submissions", schema="public")

    assert column["nullable"] is True
    assert column["default"] is None
    assert column["type"].name == "submissionstatus"
    assert NOT_DELETED_CONSTRAINT in checks
    assert ACTIVE_NULL_CONSTRAINT in checks
    assert all(COLUMN_NAME not in index["column_names"] for index in indexes)
    assert _current_revision(migration_engine) == NEW_REVISION


def test_f5_upgrade_backfills_only_deterministic_deleted_owner_rows(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="owner")
    admin_id = _insert_user(migration_engine, suffix="admin", is_admin=True)
    other_id = _insert_user(migration_engine, suffix="other")
    archive_id = _insert_archive(migration_engine, suffix="ambiguous")

    rows = {
        f"active-{status.lower()}": _insert_submission(
            migration_engine,
            suffix=f"active-{status.lower()}",
            requester_id=owner_id,
            status=status,
        )
        for status in ("PENDING", "APPROVED", "REJECTED", "TAKEDOWN")
    }
    rows["course-valid"] = _insert_submission(
        migration_engine,
        suffix="course-valid",
        requester_id=owner_id,
        status="TAKEDOWN",
        lifecycle_reason=(
            "course_trashed|previous_status=rejected|course_id=1"
            f"|archive_id={archive_id}"
        ),
        created_archive_id=archive_id,
    )
    rows["course-invalid"] = _insert_submission(
        migration_engine,
        suffix="course-invalid",
        requester_id=owner_id,
        status="TAKEDOWN",
        lifecycle_reason="course_trashed|previous_status=unknown|course_id=1",
    )
    rows["owner-deleted"] = _insert_submission(
        migration_engine,
        suffix="owner-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    rows["admin-deleted"] = _insert_submission(
        migration_engine,
        suffix="admin-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=admin_id,
        delete_reason="admin deleted",
    )
    rows["archive-group"] = _insert_submission(
        migration_engine,
        suffix="archive-group",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=admin_id,
        delete_reason="archive group deleted",
        lifecycle_reason="archive_trashed",
    )
    rows["permanent"] = _insert_submission(
        migration_engine,
        suffix="permanent",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=other_id,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
    )
    rows["unknown"] = _insert_submission(
        migration_engine,
        suffix="unknown",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=other_id,
        delete_reason="unknown deleted provenance",
    )
    rows["archive-present-ambiguous"] = _insert_submission(
        migration_engine,
        suffix="archive-present-ambiguous",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=admin_id,
        delete_reason="admin deleted",
        created_archive_id=archive_id,
    )
    rows["archive-absent-ambiguous"] = _insert_submission(
        migration_engine,
        suffix="archive-absent-ambiguous",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=admin_id,
        delete_reason="admin deleted",
    )
    before = _source_snapshot(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)

    statuses = _previous_statuses(migration_engine)
    assert statuses[rows["owner-deleted"]] == "APPROVED"
    assert {
        statuses[row_id] for name, row_id in rows.items() if name != "owner-deleted"
    } == {None}
    assert _source_snapshot(migration_engine) == before


def test_database_constraints_reject_deleted_prior_state_and_active_non_null(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="constraints")
    active_id = _insert_submission(
        migration_engine,
        suffix="constraints-active",
        requester_id=owner_id,
    )
    deleted_id = _insert_submission(
        migration_engine,
        suffix="constraints-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    command.upgrade(alembic_config(), NEW_REVISION)

    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                    UPDATE archive_submissions
                    SET previous_status = 'DELETED'::submissionstatus
                    WHERE id = :submission_id
                    """
            ),
            {"submission_id": deleted_id},
        )
    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                    UPDATE archive_submissions
                    SET previous_status = 'PENDING'::submissionstatus
                    WHERE id = :submission_id
                    """
            ),
            {"submission_id": active_id},
        )


def test_downgrade_and_reupgrade_only_remove_and_restore_new_contract(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="roundtrip")
    owner_deleted_id = _insert_submission(
        migration_engine,
        suffix="roundtrip-owner",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    before = _source_snapshot(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)
    assert _previous_statuses(migration_engine)[owner_deleted_id] == "APPROVED"

    command.downgrade(alembic_config(), PREVIOUS_REVISION)
    with migration_engine.connect() as connection:
        assert COLUMN_NAME not in {
            item["name"]
            for item in sa_inspect(connection).get_columns(
                "archive_submissions",
                schema="public",
            )
        }
    assert _source_snapshot(migration_engine) == before

    command.upgrade(alembic_config(), NEW_REVISION)
    assert _previous_statuses(migration_engine)[owner_deleted_id] == "APPROVED"
    assert _source_snapshot(migration_engine) == before


def test_audit_v2_classifier_is_read_only_and_rolls_back(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="audit-owner")
    course_marker_id = _insert_submission(
        migration_engine,
        suffix="audit-course",
        requester_id=owner_id,
        status="TAKEDOWN",
        lifecycle_reason="course_trashed|previous_status=approved|course_id=1",
    )
    _insert_submission(
        migration_engine,
        suffix="audit-owner-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    command.upgrade(alembic_config(), NEW_REVISION)

    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 2)
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        aggregates = adapter.aggregate_model.model_validate(
            dict(connection.execute(text(adapter.summary_sql)).mappings().one())
        )
        transaction.rollback()
        assert connection.in_transaction() is False

    assert aggregates.valid_course_marker == 1
    assert aggregates.valid_course_marker_with_previous_status == 0
    assert aggregates.deterministic_owner_delete_candidate == 1
    assert aggregates.deterministic_backfilled == 1

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT previous_status FROM archive_submissions "
                    "WHERE id = :submission_id"
                ),
                {"submission_id": course_marker_id},
            )
            is None
        )
