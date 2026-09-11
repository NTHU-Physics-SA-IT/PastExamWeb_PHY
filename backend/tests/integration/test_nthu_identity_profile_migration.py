from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import settings
from app.db.migration_safety import alembic_config
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

PREVIOUS_REVISION = "a5f7c9d2e4b6"
NEW_REVISION = "c3f8a1d6e9b2"
LOCAL_NAME_INDEX = "uq_users_local_name"
OAUTH_IDENTITY_CONSTRAINT = "uq_users_oauth_provider_sub"


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


def _columns(engine: Engine) -> dict[str, dict[str, object]]:
    with engine.connect() as connection:
        return {
            item["name"]: item
            for item in inspect(connection).get_columns("users", schema="public")
        }


def _indexes(engine: Engine) -> dict[str, dict[str, object]]:
    with engine.connect() as connection:
        return {
            item["name"]: item
            for item in inspect(connection).get_indexes("users", schema="public")
        }


def _constraint_columns(engine: Engine) -> dict[str, tuple[str, ...]]:
    with engine.connect() as connection:
        return {
            item["name"]: tuple(item.get("column_names") or ())
            for item in inspect(connection).get_unique_constraints(
                "users",
                schema="public",
            )
        }


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _insert_user(
    engine: Engine,
    *,
    name: str | None = None,
    email: str | None = None,
    is_local: bool,
    provider: str | None = None,
    subject: str | None = None,
    deleted_at: datetime | None = None,
    nthu_inschool: bool | None = None,
) -> int:
    marker = uuid.uuid4().hex
    parameters = {
        "name": name or f"identity-profile-{marker}",
        "email": email or f"identity-profile-{marker}@example.invalid",
        "is_local": is_local,
        "provider": provider,
        "subject": subject,
        "deleted_at": deleted_at,
        "nthu_inschool": nthu_inschool,
    }
    columns = "email, name, is_admin, is_local, oauth_provider, oauth_sub, deleted_at"
    values = ":email, :name, false, :is_local, :provider, :subject, :deleted_at"
    if "nthu_inschool" in _columns(engine):
        columns += ", nthu_inschool"
        values += ", :nthu_inschool"
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(f"INSERT INTO users ({columns}) VALUES ({values}) RETURNING id"),
                parameters,
            )
        )


def test_upgrade_preserves_rows_and_adds_nullable_unknown_state(
    migration_engine: Engine,
) -> None:
    user_id = _insert_user(migration_engine, is_local=True)
    with migration_engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT id, email, name, is_local, deleted_at FROM users WHERE id=:id"
            ),
            {"id": user_id},
        ).one()

    command.upgrade(alembic_config(), NEW_REVISION)

    column = _columns(migration_engine)["nthu_inschool"]
    assert column["nullable"] is True
    assert column["default"] is None
    with migration_engine.connect() as connection:
        after = connection.execute(
            text(
                "SELECT id, email, name, is_local, deleted_at FROM users WHERE id=:id"
            ),
            {"id": user_id},
        ).one()
        assert (
            connection.scalar(
                text("SELECT nthu_inschool FROM users WHERE id=:id"),
                {"id": user_id},
            )
            is None
        )
    assert after == before


def test_upgraded_schema_allows_profile_duplicates_and_enforces_local_names(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    shared_name = "shared-profile-name"
    shared_email = "shared-profile@example.invalid"
    _insert_user(
        migration_engine,
        name=shared_name,
        email=shared_email,
        is_local=False,
        provider="nthu",
        subject="profile-uuid-1",
    )
    _insert_user(
        migration_engine,
        name=shared_name,
        email=shared_email,
        is_local=False,
        provider="nthu",
        subject="profile-uuid-2",
    )
    _insert_user(
        migration_engine,
        name=shared_name,
        email=shared_email,
        is_local=True,
    )
    _insert_user(
        migration_engine,
        name="another-local-name",
        email=shared_email,
        is_local=True,
    )

    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, name, is_admin, is_local) "
                "VALUES ('unique-local@example.invalid', :name, false, true)"
            ),
            {"name": shared_name},
        )

    deleted_name = "soft-deleted-local-name"
    _insert_user(
        migration_engine,
        name=deleted_name,
        is_local=True,
        deleted_at=datetime.now(UTC),
    )
    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, name, is_admin, is_local) "
                "VALUES ('replacement@example.invalid', :name, false, true)"
            ),
            {"name": deleted_name},
        )

    indexes = _indexes(migration_engine)
    assert indexes["ix_users_email"]["unique"] is False
    assert indexes["ix_users_name"]["unique"] is False
    assert indexes[LOCAL_NAME_INDEX]["unique"] is True
    predicate = str(indexes[LOCAL_NAME_INDEX]["dialect_options"]["postgresql_where"])
    assert "is_local IS TRUE" in predicate
    assert "deleted_at" not in predicate


def test_oauth_provider_identity_constraint_is_unchanged(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    _insert_user(
        migration_engine,
        is_local=False,
        provider="nthu",
        subject="stable-uuid",
    )

    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(email, name, is_admin, is_local, oauth_provider, oauth_sub) "
                "VALUES ('duplicate@example.invalid', 'duplicate', false, false, "
                "'nthu', 'stable-uuid')"
            )
        )

    assert _constraint_columns(migration_engine)[OAUTH_IDENTITY_CONSTRAINT] == (
        "oauth_provider",
        "oauth_sub",
    )


def test_compatible_downgrade_restores_old_uniqueness_without_data_loss(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    user_id = _insert_user(
        migration_engine,
        is_local=False,
        provider="nthu",
        subject="downgrade-uuid",
        nthu_inschool=False,
    )

    command.downgrade(alembic_config(), PREVIOUS_REVISION)

    assert "nthu_inschool" not in _columns(migration_engine)
    indexes = _indexes(migration_engine)
    assert indexes["ix_users_email"]["unique"] is True
    assert indexes["ix_users_name"]["unique"] is True
    assert LOCAL_NAME_INDEX not in indexes
    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM users WHERE id=:id"),
                {"id": user_id},
            )
            == 1
        )


def test_downgrade_duplicate_guard_fails_transactionally_without_values(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    shared_email = "guard-shared@example.invalid"
    shared_name = "guard-shared-name"
    _insert_user(
        migration_engine,
        name="guard-email-1",
        email=shared_email,
        is_local=False,
        provider="nthu",
        subject="guard-uuid-1",
    )
    _insert_user(
        migration_engine,
        name="guard-email-2",
        email=shared_email,
        is_local=False,
        provider="nthu",
        subject="guard-uuid-2",
    )
    _insert_user(
        migration_engine,
        name=shared_name,
        is_local=False,
        provider="nthu",
        subject="guard-uuid-3",
    )
    _insert_user(
        migration_engine,
        name=shared_name,
        is_local=False,
        provider="nthu",
        subject="guard-uuid-4",
    )
    with migration_engine.connect() as connection:
        before_count = connection.scalar(text("SELECT count(*) FROM users"))

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(alembic_config(), PREVIOUS_REVISION)

    message = str(exc_info.value)
    assert "email_duplicate_groups=1" in message
    assert "name_duplicate_groups=1" in message
    assert shared_email not in message
    assert shared_name not in message
    assert _revision(migration_engine) == NEW_REVISION
    assert "nthu_inschool" in _columns(migration_engine)
    assert LOCAL_NAME_INDEX in _indexes(migration_engine)
    with migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == before_count
