from __future__ import annotations

import os
import uuid

from alembic import command
import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.migration_safety import alembic_config
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)


PREVIOUS_REVISION = "6f3a9c2d8e41"
NEW_REVISION = "9f1c2a7e4b63"
CONSTRAINT_NAME = "uq_users_oauth_provider_sub"


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


def _constraint_columns(engine: Engine) -> dict[str, tuple[str, ...]]:
    with engine.connect() as connection:
        return {
            item["name"]: tuple(item.get("column_names") or ())
            for item in sa_inspect(connection).get_unique_constraints(
                "users",
                schema="public",
            )
        }


def _insert_user(
    engine: Engine,
    *,
    provider: str | None,
    subject: str | None,
) -> int:
    marker = uuid.uuid4().hex
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO users (
                        oauth_provider, oauth_sub, email, name, is_admin, is_local
                    )
                    VALUES (:provider, :subject, :email, :name, false, :is_local)
                    RETURNING id
                    """
                ),
                {
                    "provider": provider,
                    "subject": subject,
                    "email": f"oauth-migration-{marker}@example.invalid",
                    "name": f"oauth-migration-{marker}",
                    "is_local": provider is None and subject is None,
                },
            )
        )


def test_fresh_upgrade_adds_exact_nullable_identity_constraint(
    migration_engine: Engine,
) -> None:
    _reset_empty(migration_engine)
    command.upgrade(alembic_config(), NEW_REVISION)

    assert _constraint_columns(migration_engine)[CONSTRAINT_NAME] == (
        "oauth_provider",
        "oauth_sub",
    )
    with migration_engine.connect() as connection:
        columns = {
            item["name"]: item
            for item in sa_inspect(connection).get_columns("users", schema="public")
        }
    assert columns["oauth_provider"]["nullable"] is True
    assert columns["oauth_sub"]["nullable"] is True


def test_duplicate_source_fails_closed_without_partial_constraint(
    migration_engine: Engine,
) -> None:
    _insert_user(migration_engine, provider="nthu", subject="duplicate-uuid")
    _insert_user(migration_engine, provider="nthu", subject="duplicate-uuid")

    with pytest.raises(
        RuntimeError,
        match="duplicate_groups=1, affected_rows=2, max_cardinality=2",
    ) as exc_info:
        command.upgrade(alembic_config(), NEW_REVISION)

    assert "duplicate-uuid" not in str(exc_info.value)
    assert CONSTRAINT_NAME not in _constraint_columns(migration_engine)


def test_constraint_allows_local_nulls_and_rejects_duplicate_nthu_identity(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    _insert_user(migration_engine, provider=None, subject=None)
    _insert_user(migration_engine, provider=None, subject=None)
    _insert_user(migration_engine, provider="nthu", subject="stable-uuid")

    with pytest.raises(IntegrityError) as exc_info:
        _insert_user(migration_engine, provider="nthu", subject="stable-uuid")

    assert exc_info.value.orig.pgcode == "23505"
    assert exc_info.value.orig.diag.constraint_name == CONSTRAINT_NAME


def test_downgrade_and_reupgrade_only_toggle_identity_constraint(
    migration_engine: Engine,
) -> None:
    local_id = _insert_user(migration_engine, provider=None, subject=None)
    oauth_id = _insert_user(migration_engine, provider="nthu", subject="roundtrip-uuid")

    command.upgrade(alembic_config(), NEW_REVISION)
    assert CONSTRAINT_NAME in _constraint_columns(migration_engine)
    command.downgrade(alembic_config(), PREVIOUS_REVISION)
    assert CONSTRAINT_NAME not in _constraint_columns(migration_engine)
    command.upgrade(alembic_config(), NEW_REVISION)

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM users WHERE id IN (:local_id, :oauth_id)"),
                {"local_id": local_id, "oauth_id": oauth_id},
            )
            == 2
        )
