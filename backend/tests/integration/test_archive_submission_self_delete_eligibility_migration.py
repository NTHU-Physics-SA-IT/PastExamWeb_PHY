from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import runpy
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, event, inspect as sa_inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.migration_safety import (
    alembic_config,
    inspect_database,
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
    ArchiveSubmissionRead,
    ArchiveType,
)


PREVIOUS_REVISION = "a7c3e9f1b5d2"
PRODUCTION_BASE_REVISION = "a4c7e9d2f6b1"
NEW_REVISION = "f5e1d8c3a7b2"
NEXT_REVISION = "d8f2a6c1b4e7"
COLUMN_NAME = "owner_self_delete_consumed"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


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

    cleanup_config = alembic_config()
    engine = create_engine(cleanup_config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        (
            actual_database_name,
            actual_user_name,
            actual_database_owner,
            is_superuser,
            can_create_database,
            can_create_role,
        ) = connection.execute(
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
            actual_database_name=actual_database_name,
            actual_user_name=actual_user_name,
            actual_database_owner=actual_database_owner,
            is_superuser=is_superuser,
            can_create_database=can_create_database,
            can_create_role=can_create_role,
            target=target,
        )
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), PREVIOUS_REVISION)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(cleanup_config, "head")
        for setting_name, setting_value in original_settings.items():
            setattr(settings, setting_name, setting_value)
        engine.dispose()


def test_model_and_manifest_define_the_new_head_contract() -> None:
    assert COLUMN_NAME in ArchiveSubmission.__table__.c
    assert HEAD_SCHEMA_REVISION == "b7e3d9a1c5f2"

    source_metadata = metadata_for_revision(PREVIOUS_REVISION)
    head_metadata = metadata_for_revision(NEW_REVISION)
    assert source_metadata is not None
    assert head_metadata is not None
    assert COLUMN_NAME not in source_metadata.tables["archive_submissions"].c
    assert COLUMN_NAME in head_metadata.tables["archive_submissions"].c


def test_model_instance_default_is_false() -> None:
    submission = ArchiveSubmission(
        subject="Model default",
        category="fundamental",
        name="Model default",
        academic_year=115,
        archive_type=ArchiveType.FINAL,
        professor="Test Professor",
        object_name="model-default.pdf",
        requester_id=1,
    )

    assert submission.owner_self_delete_consumed is False
    assert COLUMN_NAME not in ArchiveSubmissionRead.model_fields


def test_new_revision_remains_between_a7_and_its_successor() -> None:
    script, heads = revision_graph()

    assert heads == [HEAD_SCHEMA_REVISION]
    assert script.get_revision(NEW_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(NEXT_REVISION).down_revision == NEW_REVISION


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
                    "name": f"user-{suffix}",
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
                {"name": f"course-{suffix}"},
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
                        :name, 115, 'FINAL', 'Test Professor',
                        false, 0, :object_name, :course_id, :created_at,
                        :created_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "name": f"archive-{suffix}",
                    "object_name": f"archive-{suffix}.pdf",
                    "course_id": course_id,
                    "created_at": NOW,
                },
            )
        )


def _insert_submission(
    engine: Engine,
    *,
    suffix: str,
    requester_id: int | None,
    owner_id: int | None = None,
    status: str = "PENDING",
    deleted_at: datetime | None = None,
    deleted_by_id: int | None = None,
    delete_reason: str | None = None,
    lifecycle_reason: str | None = None,
    restored_at: datetime | None = None,
    restored_by_id: int | None = None,
    created_archive_id: int | None = None,
    category: str = "fundamental",
) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archive_submissions (
                        subject, category, name, academic_year, archive_type,
                        professor, has_answers, object_name, status,
                        requester_id, owner_id, lifecycle_reason,
                        created_archive_id, deleted_at, deleted_by_id,
                        delete_reason, restored_at, restored_by_id, created_at
                    )
                    VALUES (
                        :subject, :category, :name, 115, 'FINAL',
                        'Test Professor', false, :object_name,
                        CAST(:status AS submissionstatus), :requester_id,
                        :owner_id, :lifecycle_reason, :created_archive_id,
                        :deleted_at, :deleted_by_id, :delete_reason,
                        :restored_at, :restored_by_id, :created_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "subject": f"subject-{suffix}",
                    "category": category,
                    "name": f"submission-{suffix}",
                    "object_name": f"submission-{suffix}.pdf",
                    "status": status,
                    "requester_id": requester_id,
                    "owner_id": owner_id,
                    "lifecycle_reason": lifecycle_reason,
                    "created_archive_id": created_archive_id,
                    "deleted_at": deleted_at,
                    "deleted_by_id": deleted_by_id,
                    "delete_reason": delete_reason,
                    "restored_at": restored_at,
                    "restored_by_id": restored_by_id,
                    "created_at": NOW,
                },
            )
        )


def _reset_schema_to(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), revision)


def _eligibility_values(engine: Engine) -> dict[int, bool]:
    with engine.connect() as connection:
        return {
            int(row.id): bool(row.owner_self_delete_consumed)
            for row in connection.execute(
                text(
                    """
                    SELECT id, owner_self_delete_consumed
                    FROM archive_submissions
                    ORDER BY id
                    """
                )
            )
        }


def _source_snapshot(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        id, requester_id, owner_id, status::text AS status,
                        deleted_at, deleted_by_id, delete_reason,
                        lifecycle_reason, restored_at, restored_by_id,
                        created_archive_id
                    FROM archive_submissions
                    ORDER BY id
                    """
                )
            ).mappings()
        ]


def _column_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return COLUMN_NAME in {
            column["name"]
            for column in sa_inspect(connection).get_columns(
                "archive_submissions",
                schema="public",
            )
        }


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _migration_module() -> dict[str, Any]:
    return runpy.run_path(
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / ("f5e1d8c3a7b2_add_archive_submission_self_delete_eligibility.py")
    )


def test_a7_upgrade_adds_the_eligibility_column(
    migration_engine: Engine,
) -> None:
    with migration_engine.connect() as connection:
        before_indexes = sa_inspect(connection).get_indexes(
            "archive_submissions",
            schema="public",
        )
        before_checks = sa_inspect(connection).get_check_constraints(
            "archive_submissions",
            schema="public",
        )
        before_triggers = (
            connection.execute(
                text(
                    """
                SELECT tgname
                FROM pg_trigger
                WHERE tgrelid = 'archive_submissions'::regclass
                  AND NOT tgisinternal
                ORDER BY tgname
                """
                )
            )
            .scalars()
            .all()
        )

    command.upgrade(alembic_config(), NEW_REVISION)

    with migration_engine.connect() as connection:
        inspector = sa_inspect(connection)
        columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "archive_submissions",
                schema="public",
            )
        }
        assert columns[COLUMN_NAME]["nullable"] is False
        assert str(columns[COLUMN_NAME]["type"]).upper() == "BOOLEAN"
        assert columns[COLUMN_NAME]["default"] == "false"
        assert (
            inspector.get_indexes(
                "archive_submissions",
                schema="public",
            )
            == before_indexes
        )
        assert (
            inspector.get_check_constraints(
                "archive_submissions",
                schema="public",
            )
            == before_checks
        )
        assert (
            connection.execute(
                text(
                    """
                SELECT tgname
                FROM pg_trigger
                WHERE tgrelid = 'archive_submissions'::regclass
                  AND NOT tgisinternal
                ORDER BY tgname
                """
                )
            )
            .scalars()
            .all()
            == before_triggers
        )

        requester_id = int(
            connection.scalar(
                text(
                    """
                    INSERT INTO users (email, name, is_admin, is_local)
                    VALUES (
                        'raw-default@example.invalid',
                        'raw-default',
                        false,
                        true
                    )
                    RETURNING id
                    """
                )
            )
        )
        raw_default = connection.scalar(
            text(
                """
                INSERT INTO archive_submissions (
                    subject, category, name, academic_year, archive_type,
                    professor, has_answers, object_name, status,
                    requester_id, created_at
                )
                VALUES (
                    'Raw default', 'fundamental', 'Raw default', 115,
                    'FINAL', 'Test Professor', false, 'raw-default.pdf',
                    'PENDING', :requester_id, :created_at
                )
                RETURNING owner_self_delete_consumed
                """
            ),
            {"requester_id": requester_id, "created_at": NOW},
        )
        assert raw_default is False

    command.downgrade(alembic_config(), PREVIOUS_REVISION)
    assert _column_exists(migration_engine) is False
    assert _current_revision(migration_engine) == PREVIOUS_REVISION


def test_migration_lock_levels_block_identity_and_submission_writes(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="lock-owner")
    submission_id = _insert_submission(
        migration_engine,
        suffix="lock-submission",
        requester_id=owner_id,
    )
    migration_module = _migration_module()

    with migration_engine.connect() as locker:
        lock_transaction = locker.begin()
        try:
            locker.execute(text(migration_module["USER_LOCK_SQL"]))
            locker.execute(text(migration_module["SUBMISSION_LOCK_SQL"]))

            with migration_engine.connect() as user_writer:
                user_transaction = user_writer.begin()
                try:
                    user_writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(OperationalError, match="lock timeout"):
                        user_writer.execute(
                            text(
                                "UPDATE users SET is_admin = true WHERE id = :owner_id"
                            ),
                            {"owner_id": owner_id},
                        )
                finally:
                    user_transaction.rollback()

            with migration_engine.connect() as submission_writer:
                submission_transaction = submission_writer.begin()
                try:
                    submission_writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(OperationalError, match="lock timeout"):
                        submission_writer.execute(
                            text(
                                "UPDATE archive_submissions "
                                "SET subject = subject "
                                "WHERE id = :submission_id"
                            ),
                            {"submission_id": submission_id},
                        )
                finally:
                    submission_transaction.rollback()
        finally:
            lock_transaction.rollback()

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT is_admin FROM users WHERE id = :owner_id"),
                {"owner_id": owner_id},
            )
            is False
        )
        assert (
            connection.scalar(
                text(
                    "SELECT subject FROM archive_submissions WHERE id = :submission_id"
                ),
                {"submission_id": submission_id},
            )
            == "subject-lock-submission"
        )


def test_supported_backfill_categories_and_shared_archive_are_independent(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="supported-owner")
    admin_id = _insert_user(
        migration_engine,
        suffix="supported-admin",
        is_admin=True,
    )
    restorer_id = _insert_user(migration_engine, suffix="supported-restorer")
    shared_archive_id = _insert_archive(migration_engine, suffix="shared")

    clean_id = _insert_submission(
        migration_engine,
        suffix="clean",
        requester_id=owner_id,
    )
    owner_deleted_id = _insert_submission(
        migration_engine,
        suffix="owner-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    restored_id = _insert_submission(
        migration_engine,
        suffix="restored",
        requester_id=owner_id,
        status="APPROVED",
        restored_at=NOW,
        restored_by_id=restorer_id,
    )
    admin_deleted_id = _insert_submission(
        migration_engine,
        suffix="admin-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=admin_id,
        delete_reason="admin deleted",
    )
    shared_clean_id = _insert_submission(
        migration_engine,
        suffix="shared-clean",
        requester_id=owner_id,
        created_archive_id=shared_archive_id,
    )
    shared_restored_id = _insert_submission(
        migration_engine,
        suffix="shared-restored",
        requester_id=owner_id,
        status="APPROVED",
        restored_at=NOW,
        restored_by_id=restorer_id,
        created_archive_id=shared_archive_id,
    )
    temporary_takedown_id = _insert_submission(
        migration_engine,
        suffix="temporary-takedown",
        requester_id=owner_id,
        status="TAKEDOWN",
        lifecycle_reason=(
            "course_trashed|previous_status=approved|course_id=1"
            f"|archive_id={shared_archive_id}"
        ),
        created_archive_id=shared_archive_id,
    )
    archive_snapshot = None
    with migration_engine.connect() as connection:
        archive_snapshot = connection.execute(
            text(
                """
                SELECT id, deleted_at, deleted_by_id, deleted_reason,
                       restored_at, restored_by_id
                FROM archives
                WHERE id = :archive_id
                """
            ),
            {"archive_id": shared_archive_id},
        ).one()

    command.upgrade(alembic_config(), NEW_REVISION)

    assert _eligibility_values(migration_engine) == {
        clean_id: False,
        owner_deleted_id: True,
        restored_id: True,
        admin_deleted_id: True,
        shared_clean_id: False,
        shared_restored_id: True,
        temporary_takedown_id: False,
    }
    with migration_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    """
                SELECT id, deleted_at, deleted_by_id, deleted_reason,
                       restored_at, restored_by_id
                FROM archives
                WHERE id = :archive_id
                """
                ),
                {"archive_id": shared_archive_id},
            ).one()
            == archive_snapshot
        )


def test_recognized_system_history_backfills_consumed_for_admin_and_owner_actors(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="system-history-owner")
    admin_id = _insert_user(
        migration_engine,
        suffix="system-history-admin",
        is_admin=True,
    )
    admin_actor_id = _insert_submission(
        migration_engine,
        suffix="system-history-admin-actor",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=admin_id,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
    )
    owner_actor_id = _insert_submission(
        migration_engine,
        suffix="system-history-owner-actor",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=owner_id,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
    )
    before = _source_snapshot(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)

    assert _eligibility_values(migration_engine) == {
        admin_actor_id: True,
        owner_actor_id: True,
    }
    assert _source_snapshot(migration_engine) == before


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        (
            "system-reason-lifecycle-mismatch",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": "other",
                "delete_reason": "linked archive permanently deleted",
            },
        ),
        (
            "system-lifecycle-reason-mismatch",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": "other",
                "delete_reason": "admin deleted",
                "lifecycle_reason": "linked_archive_permanently_deleted",
            },
        ),
        (
            "system-actor-missing",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": 2_147_483_647,
                "delete_reason": "linked archive permanently deleted",
                "lifecycle_reason": "linked_archive_permanently_deleted",
            },
        ),
        (
            "unknown-reason",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": "owner",
                "delete_reason": "unknown delete reason",
            },
        ),
        (
            "group-hard-delete",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": "other",
                "delete_reason": "group hard delete",
            },
        ),
        (
            "actor-reason-mismatch",
            {
                "status": "DELETED",
                "deleted_at": NOW,
                "deleted_by_id": "other",
                "delete_reason": "user deleted",
            },
        ),
        ("owner-conflict", {"owner_id": "other"}),
        ("status-delete-mismatch", {"status": "DELETED"}),
        ("restore-contradiction", {"restored_at": NOW}),
        ("active-delete-residue", {"delete_reason": "admin deleted"}),
        (
            "unsupported-lifecycle",
            {
                "status": "TAKEDOWN",
                "lifecycle_reason": (
                    "course_trashed|previous_status=unknown|course_id=1"
                ),
            },
        ),
    ],
)
def test_unsupported_rows_abort_without_schema_or_data_change(
    migration_engine: Engine,
    case: str,
    overrides: dict[str, Any],
) -> None:
    owner_id = _insert_user(migration_engine, suffix=f"{case}-owner")
    other_id = _insert_user(migration_engine, suffix=f"{case}-other")
    resolved = {
        key: (owner_id if value == "owner" else other_id if value == "other" else value)
        for key, value in overrides.items()
    }
    _insert_submission(
        migration_engine,
        suffix=case,
        requester_id=owner_id,
        **resolved,
    )
    before = _source_snapshot(migration_engine)

    with pytest.raises(RuntimeError, match="not deterministic"):
        command.upgrade(alembic_config(), NEW_REVISION)

    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert _column_exists(migration_engine) is False
    assert _source_snapshot(migration_engine) == before


def test_source_manifest_drift_blocks_requester_null_before_classification(
    migration_engine: Engine,
) -> None:
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE archive_submissions "
                "ALTER COLUMN requester_id DROP NOT NULL"
            )
        )
    _insert_submission(
        migration_engine,
        suffix="source-drift-both-owners-null",
        requester_id=None,
    )

    report = inspect_database()
    assert report.upgrade_allowed is False
    assert any(
        check.name == "archive_submissions.requester_id.nullability"
        and not check.passed
        for check in report.schema_checks
    )
    with pytest.raises(RuntimeError, match="source schema does not match"):
        command.upgrade(alembic_config(), NEW_REVISION)

    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert _column_exists(migration_engine) is False


def test_postflight_statement_failure_rolls_back_ddl_backfill_and_ledger(
    migration_engine: Engine,
) -> None:
    owner_id = _insert_user(migration_engine, suffix="atomic-owner")
    _insert_submission(
        migration_engine,
        suffix="atomic-owner-delete",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=owner_id,
        delete_reason="user deleted",
    )
    before = _source_snapshot(migration_engine)

    def fail_postflight(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        if "owner_self_delete_eligibility_postflight" in statement:
            raise RuntimeError("injected postflight statement failure")

    event.listen(Engine, "before_cursor_execute", fail_postflight)
    try:
        with pytest.raises(
            RuntimeError,
            match="injected postflight statement failure",
        ):
            command.upgrade(alembic_config(), NEW_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_postflight)

    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert _column_exists(migration_engine) is False
    assert _source_snapshot(migration_engine) == before


def test_production_like_a4_path_backfills_base_and_system_history(
    migration_engine: Engine,
) -> None:
    _reset_schema_to(migration_engine, PRODUCTION_BASE_REVISION)
    owner_id = _insert_user(migration_engine, suffix="production-like-owner")
    admin_id = _insert_user(
        migration_engine,
        suffix="production-like-admin",
        is_admin=True,
    )
    for index in range(10):
        _insert_submission(
            migration_engine,
            suffix=f"production-like-clean-{index}",
            requester_id=owner_id,
            category="FRESHMAN",
        )
    _insert_submission(
        migration_engine,
        suffix="production-like-admin-deleted",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=admin_id,
        delete_reason="admin deleted",
        category="FRESHMAN",
    )
    _insert_submission(
        migration_engine,
        suffix="production-like-system-admin-actor",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=admin_id,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
        category="FRESHMAN",
    )
    _insert_submission(
        migration_engine,
        suffix="production-like-system-owner-actor",
        requester_id=owner_id,
        status="DELETED",
        deleted_at=NOW,
        deleted_by_id=owner_id,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
        category="FRESHMAN",
    )
    before = _source_snapshot(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)

    values = list(_eligibility_values(migration_engine).values())
    assert len(values) == 13
    assert values.count(False) == 10
    assert values.count(True) == 3
    assert _source_snapshot(migration_engine) == before
    assert _current_revision(migration_engine) == NEW_REVISION


@pytest.mark.parametrize(
    "summary",
    [
        {
            "total": 1,
            "automatic_true": 1,
            "automatic_false": 0,
            "unsupported": 1,
            "unclassified": 0,
            "overlap": 1,
            "bucket_sum": 2,
        },
        {
            "total": 1,
            "automatic_true": 0,
            "automatic_false": 0,
            "unsupported": 0,
            "unclassified": 1,
            "overlap": 0,
            "bucket_sum": 1,
        },
        {
            "total": 2,
            "automatic_true": 1,
            "automatic_false": 0,
            "unsupported": 0,
            "unclassified": 0,
            "overlap": 0,
            "bucket_sum": 1,
        },
    ],
)
def test_overlap_unclassified_and_conservation_fail_closed(
    summary: dict[str, int],
) -> None:
    migration_module = _migration_module()

    with pytest.raises(RuntimeError, match="not deterministic"):
        migration_module["_assert_supported"](summary)
