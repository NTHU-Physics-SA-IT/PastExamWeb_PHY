from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import UniqueConstraint, create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import settings
from app.db.audit.registry import ELIGIBILITY_AUDIT_ID, get_audit_adapter
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
from app.models.models import ArchiveSubmission

PREVIOUS_REVISION = "d8f2a6c1b4e7"
NEW_REVISION = "6f3a9c2d8e41"
NEXT_REVISION = "9f1c2a7e4b63"
CONSTRAINT_NAME = "uq_archive_submissions_created_archive_id"
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


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _constraint_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {
            item["name"]
            for item in sa_inspect(connection).get_unique_constraints(
                "archive_submissions",
                schema="public",
            )
        }


def _insert_user(engine: Engine, *, suffix: str) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO users (email, name, is_admin, is_local)
                    VALUES (:email, :name, false, true)
                    RETURNING id
                    """
                ),
                {
                    "email": f"one-to-one-{suffix}@example.invalid",
                    "name": f"one-to-one-{suffix}",
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
                {"name": f"one-to-one-course-{suffix}"},
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
                        :name, 115, 'FINAL', 'One-to-one Professor',
                        false, 0, :object_name, :course_id, :now, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "name": f"one-to-one-archive-{suffix}",
                    "object_name": f"one-to-one-archive-{suffix}.pdf",
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
    created_archive_id: int | None,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO archive_submissions (
                        subject, category, name, academic_year, archive_type,
                        professor, has_answers, object_name, status,
                        requester_id, created_archive_id, created_at
                    )
                    VALUES (
                        :subject, 'fundamental', :name, 115, 'FINAL',
                        'One-to-one Professor', false, :object_name, 'PENDING',
                        :requester_id, :created_archive_id, :now
                    )
                    RETURNING id
                    """
                ),
                {
                    "subject": f"one-to-one-{suffix}",
                    "name": f"one-to-one-{suffix}",
                    "object_name": f"one-to-one-{suffix}.pdf",
                    "requester_id": requester_id,
                    "created_archive_id": created_archive_id,
                    "now": NOW,
                },
            )
        )


def _link_snapshot(engine: Engine) -> list[tuple[int, int | None]]:
    with engine.connect() as connection:
        return [
            (int(row.id), row.created_archive_id)
            for row in connection.execute(
                text(
                    """
                    SELECT id, created_archive_id
                    FROM archive_submissions
                    ORDER BY id
                    """
                )
            )
        ]


def test_model_and_manifest_define_named_nullable_unique_constraint() -> None:
    table = ArchiveSubmission.__table__
    column = table.c.created_archive_id
    constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert column.nullable is True
    assert constraints[CONSTRAINT_NAME] == ("created_archive_id",)
    assert HEAD_SCHEMA_REVISION == "b4d6f8a2c1e3"

    source_metadata = metadata_for_revision(PREVIOUS_REVISION)
    head_metadata = metadata_for_revision(NEW_REVISION)
    assert source_metadata is not None
    assert head_metadata is not None
    assert all(
        constraint.name != CONSTRAINT_NAME
        for constraint in source_metadata.tables["archive_submissions"].constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == CONSTRAINT_NAME
        and tuple(constraint.columns.keys()) == ("created_archive_id",)
        for constraint in head_metadata.tables["archive_submissions"].constraints
    )


def test_new_revision_remains_between_d8_and_the_current_head() -> None:
    script, heads = revision_graph()

    assert heads == [HEAD_SCHEMA_REVISION]
    assert script.get_revision(NEW_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(NEXT_REVISION).down_revision == NEW_REVISION


def test_d8_allows_duplicate_created_archive_links(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="d8-duplicate")
    archive_id = _insert_archive(migration_engine, suffix="d8-duplicate")

    _insert_submission(
        migration_engine,
        suffix="d8-first",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )
    _insert_submission(
        migration_engine,
        suffix="d8-second",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )

    assert len(_link_snapshot(migration_engine)) == 2
    assert CONSTRAINT_NAME not in _constraint_names(migration_engine)


def test_fresh_upgrade_adds_named_nullable_unique_constraint(
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
        }["created_archive_id"]
        unique_constraints = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(
                "archive_submissions",
                schema="public",
            )
        }
        indexes = inspector.get_indexes(
            "archive_submissions",
            schema="public",
        )

    assert column["nullable"] is True
    assert unique_constraints == {
        CONSTRAINT_NAME: ("created_archive_id",),
    }
    assert all(
        not (
            tuple(index["column_names"]) == ("created_archive_id",)
            and not index["unique"]
        )
        for index in indexes
    )
    assert _current_revision(migration_engine) == NEW_REVISION


def test_d8_upgrade_preserves_legal_rows_and_links(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="legal")
    first_archive_id = _insert_archive(migration_engine, suffix="legal-first")
    second_archive_id = _insert_archive(migration_engine, suffix="legal-second")
    _insert_submission(
        migration_engine,
        suffix="null-first",
        requester_id=requester_id,
        created_archive_id=None,
    )
    _insert_submission(
        migration_engine,
        suffix="null-second",
        requester_id=requester_id,
        created_archive_id=None,
    )
    _insert_submission(
        migration_engine,
        suffix="linked-first",
        requester_id=requester_id,
        created_archive_id=first_archive_id,
    )
    _insert_submission(
        migration_engine,
        suffix="linked-second",
        requester_id=requester_id,
        created_archive_id=second_archive_id,
    )
    before = _link_snapshot(migration_engine)
    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 3)
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        before_aggregates = adapter.aggregate_model.model_validate(
            dict(connection.execute(text(adapter.summary_sql)).mappings().one())
        )
        transaction.rollback()

    command.upgrade(alembic_config(), NEW_REVISION)

    assert _link_snapshot(migration_engine) == before
    assert CONSTRAINT_NAME in _constraint_names(migration_engine)
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        after_aggregates = adapter.aggregate_model.model_validate(
            dict(connection.execute(text(adapter.summary_sql)).mappings().one())
        )
        transaction.rollback()
        assert connection.in_transaction() is False

    assert before_aggregates.created_archive_id_null == 2
    assert before_aggregates.created_archive_id_non_null == 2
    assert before_aggregates.distinct_created_archive_ids == 2
    assert before_aggregates.max_created_archive_cardinality == 1
    assert before_aggregates.dangling_created_archive_links == 0
    assert (
        after_aggregates.created_archive_link_checksum
        == before_aggregates.created_archive_link_checksum
    )
    assert (
        after_aggregates.submission_state_checksum
        == before_aggregates.submission_state_checksum
    )


def test_duplicate_source_fails_closed_without_partial_schema(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="blocked")
    archive_id = _insert_archive(migration_engine, suffix="blocked")
    _insert_submission(
        migration_engine,
        suffix="blocked-first",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )
    _insert_submission(
        migration_engine,
        suffix="blocked-second",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )
    before = _link_snapshot(migration_engine)

    with pytest.raises(
        RuntimeError,
        match=("duplicate_groups=1, affected_rows=2, max_cardinality=2"),
    ) as exc_info:
        command.upgrade(alembic_config(), NEW_REVISION)

    assert "created_archive_id=" not in str(exc_info.value)
    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert CONSTRAINT_NAME not in _constraint_names(migration_engine)
    assert _link_snapshot(migration_engine) == before


def test_dangling_source_fails_closed_without_partial_schema(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="dangling")
    archive_id = _insert_archive(migration_engine, suffix="dangling")
    _insert_submission(
        migration_engine,
        suffix="dangling",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )

    with migration_engine.connect() as connection:
        foreign_key = next(
            item
            for item in sa_inspect(connection).get_foreign_keys(
                "archive_submissions",
                schema="public",
            )
            if tuple(item.get("constrained_columns") or ()) == ("created_archive_id",)
        )
    foreign_key_name = str(foreign_key["name"])
    quoted_foreign_key = migration_engine.dialect.identifier_preparer.quote(
        foreign_key_name
    )
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                f"ALTER TABLE archive_submissions DROP CONSTRAINT {quoted_foreign_key}"
            )
        )
        connection.execute(
            text("DELETE FROM archives WHERE id = :archive_id"),
            {"archive_id": archive_id},
        )
        connection.execute(
            text(
                "ALTER TABLE archive_submissions "
                f"ADD CONSTRAINT {quoted_foreign_key} "
                "FOREIGN KEY (created_archive_id) REFERENCES archives (id) "
                "NOT VALID"
            )
        )
    before = _link_snapshot(migration_engine)

    with pytest.raises(
        RuntimeError,
        match="dangling created_archive_id relationships: dangling_links=1",
    ) as exc_info:
        command.upgrade(alembic_config(), NEW_REVISION)

    assert "created_archive_id=" not in str(exc_info.value)
    assert _current_revision(migration_engine) == PREVIOUS_REVISION
    assert CONSTRAINT_NAME not in _constraint_names(migration_engine)
    assert _link_snapshot(migration_engine) == before


def test_new_constraint_allows_nulls_and_rejects_duplicate_non_null(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="enforcement")
    archive_id = _insert_archive(migration_engine, suffix="enforcement")
    command.upgrade(alembic_config(), NEW_REVISION)

    _insert_submission(
        migration_engine,
        suffix="enforcement-null-first",
        requester_id=requester_id,
        created_archive_id=None,
    )
    _insert_submission(
        migration_engine,
        suffix="enforcement-null-second",
        requester_id=requester_id,
        created_archive_id=None,
    )
    _insert_submission(
        migration_engine,
        suffix="enforcement-linked",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )

    with pytest.raises(IntegrityError) as exc_info:
        _insert_submission(
            migration_engine,
            suffix="enforcement-duplicate",
            requester_id=requester_id,
            created_archive_id=archive_id,
        )

    assert exc_info.value.orig.pgcode == "23505"
    assert exc_info.value.orig.diag.constraint_name == CONSTRAINT_NAME


def test_downgrade_and_reupgrade_only_toggle_unique_constraint(
    migration_engine: Engine,
) -> None:
    requester_id = _insert_user(migration_engine, suffix="roundtrip")
    archive_id = _insert_archive(migration_engine, suffix="roundtrip")
    _insert_submission(
        migration_engine,
        suffix="roundtrip-null",
        requester_id=requester_id,
        created_archive_id=None,
    )
    _insert_submission(
        migration_engine,
        suffix="roundtrip-linked",
        requester_id=requester_id,
        created_archive_id=archive_id,
    )
    before = _link_snapshot(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)
    assert CONSTRAINT_NAME in _constraint_names(migration_engine)

    command.downgrade(alembic_config(), PREVIOUS_REVISION)
    assert CONSTRAINT_NAME not in _constraint_names(migration_engine)
    assert _link_snapshot(migration_engine) == before

    command.upgrade(alembic_config(), NEW_REVISION)
    assert CONSTRAINT_NAME in _constraint_names(migration_engine)
    assert _link_snapshot(migration_engine) == before


@pytest.mark.parametrize(
    ("mutation", "failed_checks"),
    [
        (
            f"ALTER TABLE archive_submissions DROP CONSTRAINT {CONSTRAINT_NAME}",
            {
                "archive_submissions.unique_constraints",
                "archive_submissions.named_critical_unique_constraints",
            },
        ),
        (
            (
                "ALTER TABLE archive_submissions "
                f"DROP CONSTRAINT {CONSTRAINT_NAME}; "
                "ALTER TABLE archive_submissions "
                "ADD CONSTRAINT uq_archive_submissions_wrong_name "
                "UNIQUE (created_archive_id)"
            ),
            {"archive_submissions.named_critical_unique_constraints"},
        ),
        (
            (
                "ALTER TABLE archive_submissions "
                f"DROP CONSTRAINT {CONSTRAINT_NAME}; "
                "CREATE UNIQUE INDEX uq_archive_submissions_partial "
                "ON archive_submissions (created_archive_id) "
                "WHERE created_archive_id IS NOT NULL"
            ),
            {
                "archive_submissions.unique_constraints",
                "archive_submissions.named_critical_unique_constraints",
                "archive_submissions.indexes",
            },
        ),
        (
            (
                "ALTER TABLE archive_submissions "
                f"DROP CONSTRAINT {CONSTRAINT_NAME}; "
                "CREATE INDEX ix_archive_submissions_created_archive_id "
                "ON archive_submissions (created_archive_id)"
            ),
            {
                "archive_submissions.unique_constraints",
                "archive_submissions.named_critical_unique_constraints",
                "archive_submissions.indexes",
            },
        ),
        (
            (
                "ALTER TABLE archive_submissions "
                "ALTER COLUMN created_archive_id SET NOT NULL"
            ),
            {"archive_submissions.created_archive_id.nullability"},
        ),
    ],
)
def test_manifest_rejects_one_to_one_constraint_substitutes(
    migration_engine: Engine,
    mutation: str,
    failed_checks: set[str],
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    with migration_engine.begin() as connection:
        for statement in mutation.split("; "):
            connection.execute(text(statement))

    report = inspect_database()
    actual_failures = {check.name for check in report.schema_checks if not check.passed}

    assert report.schema_matches_head is False
    assert failed_checks.issubset(actual_failures)
