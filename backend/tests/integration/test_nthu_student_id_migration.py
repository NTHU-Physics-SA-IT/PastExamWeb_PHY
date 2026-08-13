from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine, make_url

from alembic import command
from app.core.config import settings
from app.db.migration_safety import alembic_config
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

PREVIOUS_REVISION = "9f1c2a7e4b63"
NEW_REVISION = "b7e3d9a1c5f2"


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
            for item in sa_inspect(connection).get_columns("users", schema="public")
        }


def _insert_user(engine: Engine, *, student_id: str | None = None) -> int:
    marker = uuid.uuid4().hex
    columns = "email, name, is_admin, is_local"
    values = ":email, :name, false, true"
    parameters = {
        "email": f"student-id-migration-{marker}@example.invalid",
        "name": f"student-id-migration-{marker}",
    }
    if student_id is not None:
        columns = f"{columns}, student_id"
        values = f"{values}, :student_id"
        parameters["student_id"] = student_id
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(f"INSERT INTO users ({columns}) VALUES ({values}) RETURNING id"),
                parameters,
            )
        )


def test_upgrade_adds_one_nullable_student_id_column(
    migration_engine: Engine,
) -> None:
    existing_user_id = _insert_user(migration_engine)

    command.upgrade(alembic_config(), NEW_REVISION)

    student_id = _columns(migration_engine)["student_id"]
    assert student_id["nullable"] is True
    assert student_id["type"].length == 255
    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT student_id FROM users WHERE id = :user_id"),
                {"user_id": existing_user_id},
            )
            is None
        )


def test_downgrade_and_reupgrade_only_toggle_student_id_column(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), NEW_REVISION)
    user_id = _insert_user(migration_engine, student_id="112022123")

    command.downgrade(alembic_config(), PREVIOUS_REVISION)
    assert "student_id" not in _columns(migration_engine)
    command.upgrade(alembic_config(), NEW_REVISION)

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT student_id FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
            is None
        )
