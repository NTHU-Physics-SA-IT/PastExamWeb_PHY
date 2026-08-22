from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import settings
from app.db.migration_safety import alembic_config, revision_graph
from app.db.schema_manifests import HEAD_SCHEMA_REVISION
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

PREVIOUS_PREVIOUS_REVISION = "f3a7c1e9d5b2"
PREVIOUS_REVISION = "c7e4a9b2d6f1"
NEW_REVISION = "c8e4a1f7b2d9"
INDEX_NAME = "uq_archive_reports_pending_reporter_archive"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


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


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _index_predicate(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.scalar(
                text(
                    """
                    SELECT lower(
                        regexp_replace(
                            replace(
                                pg_get_expr(
                                    index_state.indpred,
                                    index_state.indrelid
                                ),
                                '::text',
                                ''
                            ),
                            '[()"[:space:]]',
                            '',
                            'g'
                        )
                    )
                    FROM pg_class AS table_relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = table_relation.relnamespace
                    JOIN pg_index AS index_state
                      ON index_state.indrelid = table_relation.oid
                    JOIN pg_class AS index_relation
                      ON index_relation.oid = index_state.indexrelid
                    WHERE namespace.nspname = 'public'
                      AND table_relation.relname = 'archive_reports'
                      AND index_relation.relname = :index_name
                    """
                ),
                {"index_name": INDEX_NAME},
            )
        )


def _create_scope(engine: Engine) -> tuple[int, int]:
    marker = uuid.uuid4().hex
    with engine.begin() as connection:
        reporter_id = int(
            connection.scalar(
                text(
                    "INSERT INTO users (email, name, is_admin, is_local) "
                    "VALUES (:email, :name, false, true) RETURNING id"
                ),
                {
                    "email": f"archive-report-migration-{marker}@example.invalid",
                    "name": f"archive-report-migration-{marker}",
                },
            )
        )
        course_id = int(
            connection.scalar(
                text(
                    "INSERT INTO courses (name, category, order_index) "
                    "VALUES (:name, 'fundamental', 0) RETURNING id"
                ),
                {"name": f"archive-report-course-{marker}"},
            )
        )
        archive_id = int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archives (
                        name, academic_year, archive_type, professor,
                        has_answers, download_count, object_name, course_id,
                        created_at, updated_at
                    )
                    VALUES (
                        :name, 115, 'FINAL', 'Migration Professor',
                        false, 0, :object_name, :course_id, :now, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "name": f"archive-report-archive-{marker}",
                    "object_name": f"archive-report-{marker}.pdf",
                    "course_id": course_id,
                    "now": NOW,
                },
            )
        )
    return reporter_id, archive_id


def _insert_report(
    engine: Engine,
    *,
    reporter_id: int,
    archive_id: int,
    deleted: bool,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archive_reports (
                        reporter_user_id, reporter_name_snapshot,
                        archive_id, archive_id_snapshot, reason,
                        archive_name_snapshot, course_name_snapshot,
                        academic_year_snapshot, archive_type_snapshot,
                        professor_snapshot, status, deleted_at,
                        created_at, updated_at
                    )
                    VALUES (
                        :reporter_id, 'Migration Reporter',
                        :archive_id, :archive_id, 'metadata_mismatch',
                        'Migration Archive', 'Migration Course',
                        115, 'FINAL', 'Migration Professor', 'pending',
                        :deleted_at, :now, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "reporter_id": reporter_id,
                    "archive_id": archive_id,
                    "deleted_at": NOW if deleted else None,
                    "now": NOW,
                },
            )
        )


def _report_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*)::integer,
                    count(*) FILTER (WHERE deleted_at IS NULL)::integer
                FROM archive_reports
                """
            )
        ).one()
    return int(row[0]), int(row[1])


def test_revision_is_the_sole_forward_head() -> None:
    script, heads = revision_graph()

    assert HEAD_SCHEMA_REVISION == NEW_REVISION
    assert heads == [NEW_REVISION]
    assert script.get_revision(NEW_REVISION).down_revision == PREVIOUS_REVISION
    assert (
        script.get_revision(PREVIOUS_REVISION).down_revision
        == PREVIOUS_PREVIOUS_REVISION
    )


def test_upgrade_preserves_trashed_history_and_allows_one_active_pending(
    migration_engine: Engine,
) -> None:
    reporter_id, archive_id = _create_scope(migration_engine)
    trashed_id = _insert_report(
        migration_engine,
        reporter_id=reporter_id,
        archive_id=archive_id,
        deleted=True,
    )

    command.upgrade(alembic_config(), NEW_REVISION)
    assert _index_predicate(migration_engine) == (
        "status='pending'anddeleted_atisnull"
    )
    active_id = _insert_report(
        migration_engine,
        reporter_id=reporter_id,
        archive_id=archive_id,
        deleted=False,
    )

    assert active_id != trashed_id
    assert _report_counts(migration_engine) == (2, 1)
    with pytest.raises(IntegrityError):
        _insert_report(
            migration_engine,
            reporter_id=reporter_id,
            archive_id=archive_id,
            deleted=False,
        )


def test_downgrade_restores_old_predicate_when_existing_rows_are_valid(
    migration_engine: Engine,
) -> None:
    reporter_id, archive_id = _create_scope(migration_engine)
    report_id = _insert_report(
        migration_engine,
        reporter_id=reporter_id,
        archive_id=archive_id,
        deleted=False,
    )
    command.upgrade(alembic_config(), NEW_REVISION)

    command.downgrade(alembic_config(), PREVIOUS_REVISION)

    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert _index_predicate(migration_engine) == "status='pending'"
    assert _report_counts(migration_engine) == (1, 1)
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM archive_reports WHERE id = :report_id"),
            {"report_id": report_id},
        ) == 1


def test_downgrade_fails_closed_without_rewriting_conflicting_history(
    migration_engine: Engine,
) -> None:
    reporter_id, archive_id = _create_scope(migration_engine)
    _insert_report(
        migration_engine,
        reporter_id=reporter_id,
        archive_id=archive_id,
        deleted=True,
    )
    command.upgrade(alembic_config(), NEW_REVISION)
    _insert_report(
        migration_engine,
        reporter_id=reporter_id,
        archive_id=archive_id,
        deleted=False,
    )
    before = _report_counts(migration_engine)

    with pytest.raises(RuntimeError, match="Cannot restore the previous"):
        command.downgrade(alembic_config(), PREVIOUS_REVISION)

    assert _current_revision(migration_engine) == NEW_REVISION
    assert _index_predicate(migration_engine) == (
        "status='pending'anddeleted_atisnull"
    )
    assert _report_counts(migration_engine) == before
