from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from app.core.config import settings
from app.db.migration_safety import (
    alembic_config,
    inspect_database,
    revision_graph,
)
from app.db.schema_manifests import HEAD_SCHEMA_REVISION
from app.db.schema_manifests.registry import (
    PREVIOUS_HEAD_SCHEMA_REVISION,
)
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

PREVIOUS_HEAD = "f6b8d2c4a9e1"
CURRENT_HEAD = "a5f7c9d2e4b6"
TABLES = (
    "permanent_deletion_operations",
    "permanent_deletion_targets",
    "permanent_deletion_objects",
)
ENUMS = {
    "permanent_deletion_status": (
        "ACCEPTED",
        "PROCESSING",
        "VERIFICATION_REQUIRED",
        "RETRYABLE_FAILED",
        "MANUAL_REVIEW",
        "COMPLETED",
    ),
    "permanent_deletion_identity_scheme": ("MINIO_VERSION_ID_V1",),
    "permanent_deletion_object_state": (
        "CAPTURED",
        "DELETE_IN_PROGRESS",
        "VERIFICATION_REQUIRED",
        "RETRYABLE_FAILED",
        "MANUAL_REVIEW",
        "VERIFIED_ABSENT",
    ),
}


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
    command.upgrade(config, PREVIOUS_HEAD)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(config, CURRENT_HEAD)
        for setting_name, setting_value in original_settings.items():
            setattr(settings, setting_name, setting_value)
        engine.dispose()


def _ledger(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _insert_operation(engine: Engine, marker: str | None = None) -> int:
    marker = marker or uuid.uuid4().hex
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    "INSERT INTO permanent_deletion_operations "
                    "(root_entity_type, root_entity_id, idempotency_key) "
                    "VALUES ('archive', 1, :key) RETURNING id"
                ),
                {"key": f"operation-{marker}"},
            )
        )


def _insert_target(engine: Engine, operation_id: int, entity_id: int = 1) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    "INSERT INTO permanent_deletion_targets "
                    "(operation_id, entity_type, entity_id) "
                    "VALUES (:operation_id, 'archive', :entity_id) RETURNING id"
                ),
                {"operation_id": operation_id, "entity_id": entity_id},
            )
        )


def test_revision_is_the_single_forward_head() -> None:
    script, heads = revision_graph()

    assert PREVIOUS_HEAD_SCHEMA_REVISION == PREVIOUS_HEAD
    assert HEAD_SCHEMA_REVISION == CURRENT_HEAD
    assert heads == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == PREVIOUS_HEAD


def test_upgrade_is_additive_and_manifest_matches(
    migration_engine: Engine,
) -> None:
    marker = uuid.uuid4().hex
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, name, is_admin, is_local) "
                "VALUES (:email, :name, false, true)"
            ),
            {
                "email": f"permanent-deletion-{marker}@example.invalid",
                "name": f"permanent-deletion-{marker}",
            },
        )

    command.upgrade(alembic_config(), CURRENT_HEAD)

    assert _ledger(migration_engine) == CURRENT_HEAD
    assert set(TABLES) <= set(inspect(migration_engine).get_table_names())
    with migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 1
        assert all(
            connection.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0
            for table_name in TABLES
        )
        reflected_enums = {
            str(row[0]): tuple(row[1])
            for row in connection.execute(
                text(
                    "SELECT pg_type.typname, "
                    "array_agg(pg_enum.enumlabel ORDER BY pg_enum.enumsortorder) "
                    "FROM pg_type JOIN pg_enum ON pg_enum.enumtypid = pg_type.oid "
                    "JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace "
                    "WHERE pg_namespace.nspname = 'public' "
                    "AND pg_type.typname LIKE 'permanent_deletion_%' "
                    "GROUP BY pg_type.typname"
                )
            )
        }
    assert reflected_enums == ENUMS
    assert inspect_database().schema_matches_head is True


def test_empty_ledger_downgrade_removes_only_foundation(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), CURRENT_HEAD)
    command.downgrade(alembic_config(), PREVIOUS_HEAD)

    assert _ledger(migration_engine) == PREVIOUS_HEAD
    table_names = set(inspect(migration_engine).get_table_names())
    assert not set(TABLES) & table_names
    assert "users" in table_names
    with migration_engine.connect() as connection:
        enum_count = connection.scalar(
            text(
                "SELECT count(*) FROM pg_type "
                "JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace "
                "WHERE pg_namespace.nspname = 'public' "
                "AND pg_type.typname LIKE 'permanent_deletion_%'"
            )
        )
    assert enum_count == 0


def test_populated_ledger_downgrade_fails_before_data_or_schema_loss(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), CURRENT_HEAD)
    operation_id = _insert_operation(migration_engine)

    with pytest.raises(RuntimeError, match="operation or recovery data exists"):
        command.downgrade(alembic_config(), PREVIOUS_HEAD)

    assert _ledger(migration_engine) == CURRENT_HEAD
    assert set(TABLES) <= set(inspect(migration_engine).get_table_names())
    with migration_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM permanent_deletion_operations WHERE id = :id"
                ),
                {"id": operation_id},
            )
            == 1
        )


def test_exact_identity_and_active_reservation_constraints(
    migration_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), CURRENT_HEAD)
    operation_id = _insert_operation(migration_engine)
    target_id = _insert_target(migration_engine, operation_id)

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO permanent_deletion_objects "
                "(operation_id, target_id, bucket_name, object_key, version_id) "
                "VALUES (:operation_id, :target_id, 'archives', 'legacy.pdf', 'null')"
            ),
            {"operation_id": operation_id, "target_id": target_id},
        )

    for invalid_version_id in (None, ""):
        with (
            pytest.raises((IntegrityError, DBAPIError)),
            migration_engine.begin() as connection,
        ):
            connection.execute(
                text(
                    "INSERT INTO permanent_deletion_objects "
                    "(operation_id, target_id, bucket_name, object_key, version_id) "
                    "VALUES (:operation_id, :target_id, 'archives', "
                    "'invalid.pdf', :version_id)"
                ),
                {
                    "operation_id": operation_id,
                    "target_id": target_id,
                    "version_id": invalid_version_id,
                },
            )

    with pytest.raises(IntegrityError), migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO permanent_deletion_objects "
                "(operation_id, target_id, bucket_name, object_key, version_id) "
                "VALUES (:operation_id, :target_id, 'archives', 'legacy.pdf', 'null')"
            ),
            {"operation_id": operation_id, "target_id": target_id},
        )

    second_operation_id = _insert_operation(migration_engine)
    with pytest.raises(IntegrityError):
        _insert_target(migration_engine, second_operation_id)

    with migration_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT identity_scheme::text, version_id, state::text "
                "FROM permanent_deletion_objects"
            )
        ).one()
    assert row == ("MINIO_VERSION_ID_V1", "null", "CAPTURED")
