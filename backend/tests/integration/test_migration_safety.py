from __future__ import annotations

import json
from urllib.parse import quote, quote_plus

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine

import migrate
from app.db.migration_safety import (
    alembic_config,
    database_url,
    inspect_database,
    revision_graph,
    safe_error,
)


@pytest.fixture(autouse=True)
def clean_public_schema() -> Engine:
    engine = create_engine(alembic_config().get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def head_revision() -> str:
    _, heads = revision_graph()
    assert len(heads) == 1
    return heads[0]


def drop_ledger(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))


def insert_course(engine: Engine, name: str = "Migration safety marker") -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    "INSERT INTO courses (name, category, order_index) "
                    "VALUES (:name, 'FRESHMAN', 0) RETURNING id"
                ),
                {"name": name},
            )
        )


def test_empty_database_upgrade_is_idempotent() -> None:
    report = inspect_database()
    assert report.database_empty is True
    assert report.upgrade_allowed is True

    assert migrate.main(["upgrade", "--json"]) == 0
    assert inspect_database().current_revision == head_revision()
    assert migrate.main(["upgrade", "--json"]) == 0
    assert inspect_database().upgrade_allowed is True


def test_head_database_preflight_is_read_only(clean_public_schema: Engine) -> None:
    upgrade()
    course_id = insert_course(clean_public_schema)

    before = inspect_database().to_dict()
    assert migrate.main(["preflight", "--json"]) == 0
    after = inspect_database().to_dict()

    assert before == after
    with clean_public_schema.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM courses WHERE id = :course_id"),
            {"course_id": course_id},
        ) == 1


def test_missing_ledger_reports_candidate_but_never_stamps(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    course_id = insert_course(clean_public_schema)
    drop_ledger(clean_public_schema)

    assert migrate.main(["upgrade", "--json"]) == 2
    assert migrate.main(["reconcile", "--check", "--json"]) == 2
    report = inspect_database()

    assert report.schema_matches_head is True
    assert report.schema_candidate_revision == head_revision()
    assert report.upgrade_allowed is False
    with clean_public_schema.connect() as connection:
        assert "alembic_version" not in sa_inspect(connection).get_table_names()
        assert connection.scalar(
            text("SELECT count(*) FROM courses WHERE id = :course_id"),
            {"course_id": course_id},
        ) == 1


def test_missing_ledger_with_drift_fails_without_mutation(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    drop_ledger(clean_public_schema)
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_users_deleted_by_id"))

    report = inspect_database()
    assert report.upgrade_allowed is False
    assert report.schema_matches_head is False
    assert any(
        not check.passed and check.name == "users.indexes"
        for check in report.schema_checks
    )
    with clean_public_schema.connect() as connection:
        assert "alembic_version" not in sa_inspect(connection).get_table_names()
        assert not connection.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_indexes "
                "WHERE schemaname='public' AND indexname='ix_users_deleted_by_id'"
                ")"
            )
        )


def test_unknown_and_multiple_ledger_revisions_fail(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    with clean_public_schema.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num='unknown_revision'")
        )
    unknown = inspect_database()
    assert unknown.current_revision_known is False
    assert unknown.upgrade_allowed is False

    with clean_public_schema.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES (:head), ('unexpected_second_revision')"
            ),
            {"head": head_revision()},
        )
    multiple = inspect_database()
    assert len(multiple.alembic_versions) == 2
    assert multiple.upgrade_allowed is False
    assert any("exactly one revision" in error for error in multiple.errors)


def test_known_non_head_revision_is_not_auto_upgraded() -> None:
    script, _ = revision_graph()
    previous_revision = script.get_revision(head_revision()).down_revision
    assert isinstance(previous_revision, str)
    upgrade(previous_revision)

    before = inspect_database().alembic_versions
    assert migrate.main(["upgrade", "--json"]) == 2
    after = inspect_database().alembic_versions

    assert before == [previous_revision]
    assert after == before


def test_multiple_repository_heads_fail_closed(
    clean_public_schema: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade()
    script, heads = revision_graph()
    current_head = heads[0]
    monkeypatch.setattr(
        "app.db.migration_safety.revision_graph",
        lambda config=None: (script, [current_head, "second_head"]),
    )
    report = inspect_database()
    assert report.multiple_heads is True
    assert report.upgrade_allowed is False


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        ("DROP TABLE announcement_read_receipts", "tables"),
        ("ALTER TABLE users DROP COLUMN nickname", "users.columns"),
        (
            "ALTER TABLE users ALTER COLUMN show_level_title TYPE text "
            "USING show_level_title::text",
            "users.show_level_title.type",
        ),
        (
            "ALTER TABLE users ALTER COLUMN email DROP NOT NULL",
            "users.email.nullability",
        ),
        (
            "ALTER TABLE system_issue_reports "
            "ALTER COLUMN github_sync_status DROP DEFAULT",
            "system_issue_reports.github_sync_status.server_default",
        ),
        (
            "ALTER TABLE users DROP CONSTRAINT fk_users_deleted_by_id_users",
            "users.foreign_keys",
        ),
        (
            "ALTER TABLE announcement_read_receipts "
            "DROP CONSTRAINT uq_announcement_read_receipts_notification_user",
            "announcement_read_receipts.unique_constraints",
        ),
        (
            "ALTER TABLE comment_reports "
            "DROP CONSTRAINT ck_comment_reports_status",
            "comment_reports.check_constraints",
        ),
        ("DROP INDEX ix_users_deleted_by_id", "users.indexes"),
        (
            "ALTER TYPE submissionstatus ADD VALUE 'UNEXPECTED_SAFETY_TEST_VALUE'",
            "enum.submissionstatus.values",
        ),
    ],
)
def test_partial_schema_states_fail_closed(
    clean_public_schema: Engine, mutation: str, failed_check: str
) -> None:
    upgrade()
    drop_ledger(clean_public_schema)
    with clean_public_schema.begin() as connection:
        connection.execute(text(mutation))

    report = inspect_database()
    assert report.upgrade_allowed is False
    assert report.schema_candidate_revision is None
    assert any(
        not check.passed and check.name == failed_check
        for check in report.schema_checks
    ), report.to_dict()


def test_credentials_are_redacted_from_errors_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "migration-super-secret:/?#[]@!"
    monkeypatch.setattr("app.db.migration_safety.settings.DB_PASSWORD", password)
    monkeypatch.setattr("app.db.migration_safety.settings.DB_PORT", 1)

    report = inspect_database()
    rendered = json.dumps(report.to_dict(), default=str)
    raw_url = database_url().render_as_string(hide_password=False)
    error = safe_error(
        RuntimeError(
            f"{password} {quote(password, safe='')} "
            f"{quote_plus(password)} {raw_url}"
        )
    )
    assert report.database_connected is False
    assert password not in error
    assert quote(password, safe="") not in error
    assert quote_plus(password) not in error
    assert raw_url not in error
    assert password not in rendered
    assert "postgresql" not in rendered
