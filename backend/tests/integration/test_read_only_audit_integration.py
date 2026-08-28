from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from alembic import command
from app.core.config import settings
from app.db.audit.models import AuditMode, AuditRequest
from app.db.audit.registry import (
    ELIGIBILITY_AUDIT_ID,
    PERMANENT_DELETION_FOUNDATION_REVISION,
    get_audit_adapter,
)
from app.db.audit.runner import _continuity_cte
from app.db.migration_safety import alembic_config
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

PREVIOUS_REVISION = "a7c3e9f1b5d2"
NEW_REVISION = "f5e1d8c3a7b2"


@pytest.fixture()
def audit_engine(monkeypatch: pytest.MonkeyPatch) -> Engine:
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


def _insert_user(engine: Engine, *, name: str, admin: bool = False) -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO users (email, name, is_admin, is_local)
                    VALUES (:email, :name, :admin, true)
                    RETURNING id
                    """
                ),
                {
                    "email": f"{name}@example.invalid",
                    "name": name,
                    "admin": admin,
                },
            )
        )


def _insert_submission(
    engine: Engine,
    *,
    suffix: str,
    requester_id: int,
    owner_id: int | None = None,
    status: str = "PENDING",
    deleted_by_id: int | None = None,
    delete_reason: str | None = None,
    lifecycle_reason: str | None = None,
) -> None:
    deleted = status == "DELETED"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO archive_submissions (
                    subject, category, name, academic_year, archive_type,
                    professor, has_answers, object_name, status,
                    requester_id, owner_id, deleted_at, deleted_by_id,
                    delete_reason, lifecycle_reason, created_at
                )
                VALUES (
                    :subject, 'FRESHMAN', :name, 115, 'FINAL',
                    'Audit Professor', false, :object_name, :status,
                    :requester_id, :owner_id,
                    CASE WHEN :deleted THEN now() ELSE NULL END,
                    :deleted_by_id, :delete_reason, :lifecycle_reason, now()
                )
                """
            ),
            {
                "subject": f"Audit {suffix}",
                "name": f"Audit {suffix}",
                "object_name": f"audit-{suffix}.pdf",
                "status": status,
                "requester_id": requester_id,
                "owner_id": owner_id,
                "deleted": deleted,
                "deleted_by_id": deleted_by_id,
                "delete_reason": delete_reason,
                "lifecycle_reason": lifecycle_reason,
            },
        )


def _migration_module() -> dict[str, object]:
    return runpy.run_path(
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "f5e1d8c3a7b2_add_archive_submission_self_delete_eligibility.py"
    )


def test_permanent_deletion_head_passes_sealed_audit_schema_continuity(
    audit_engine: Engine,
) -> None:
    command.upgrade(alembic_config(), "head")
    request = AuditRequest(
        audit_id=ELIGIBILITY_AUDIT_ID,
        audit_version=4,
        mode=AuditMode.ISOLATED_TEST,
        expected_ledger=PERMANENT_DELETION_FOUNDATION_REVISION,
        repository_revision="a" * 40,
    )

    with audit_engine.connect() as connection:
        schema_ok = connection.scalar(
            text(_continuity_cte(request) + "SELECT schema_ok FROM schema_state")
        )

    assert schema_ok is True


def test_adapter_matches_migration_classifier_and_reports_fixed_combinations(
    audit_engine: Engine,
) -> None:
    owner = _insert_user(audit_engine, name="audit-owner")
    admin = _insert_user(audit_engine, name="audit-admin", admin=True)
    other = _insert_user(audit_engine, name="audit-other")
    _insert_submission(audit_engine, suffix="clean", requester_id=owner)
    _insert_submission(
        audit_engine,
        suffix="owner-delete",
        requester_id=owner,
        status="DELETED",
        deleted_by_id=owner,
        delete_reason="user deleted",
    )
    _insert_submission(
        audit_engine,
        suffix="admin-delete",
        requester_id=owner,
        status="DELETED",
        deleted_by_id=admin,
        delete_reason="admin deleted",
    )
    _insert_submission(
        audit_engine,
        suffix="system-delete",
        requester_id=owner,
        status="DELETED",
        deleted_by_id=other,
        delete_reason="linked archive permanently deleted",
        lifecycle_reason="linked_archive_permanently_deleted",
    )
    _insert_submission(
        audit_engine,
        suffix="owner-conflict",
        requester_id=owner,
        owner_id=other,
    )

    adapter = get_audit_adapter(ELIGIBILITY_AUDIT_ID, 1)
    migration = _migration_module()
    with audit_engine.connect() as connection:
        adapter_summary = dict(
            connection.execute(text(adapter.summary_sql)).mappings().one()
        )
        migration_summary = dict(
            connection.execute(text(migration["_SUMMARY_SQL"])).mappings().one()
        )
        combinations = [
            dict(row)
            for row in connection.execute(text(adapter.combinations_sql)).mappings()
        ]

    assert {
        key: adapter_summary[key]
        for key in (
            "total",
            "automatic_true",
            "automatic_false",
            "unsupported",
            "unclassified",
            "overlap",
            "bucket_sum",
        )
    } == migration_summary
    assert adapter_summary["difference"] == 0
    assert combinations == [
        {"flags": ["ownership_invalid"], "count": 1},
    ]


def test_read_only_transaction_rejects_writes_and_rolls_back(
    audit_engine: Engine,
) -> None:
    with audit_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(Exception, match="read-only"):
            connection.execute(
                text("UPDATE archive_submissions SET owner_id = owner_id")
            )
        transaction.rollback()

    with audit_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM archive_submissions")) == 0
