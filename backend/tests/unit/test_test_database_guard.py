from __future__ import annotations

import pytest

from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

RUNTIME_URL = "postgresql+asyncpg://runtime:secret@db:5432/archive_db"
VALID_TEST_URL = (
    "postgresql+asyncpg://pastexam_test_runner:secret@"
    "db:5432/pastexam_test_suite"
)


def valid_target():
    return validate_test_database_target(
        test_database_url=VALID_TEST_URL,
        runtime_database_url=RUNTIME_URL,
        isolation_confirmed="true",
    )


@pytest.mark.parametrize(
    "test_url",
    [
        "postgresql+asyncpg://pastexam_test_runner:secret@db:5432/archive_db",
        "postgresql+asyncpg://pastexam_test_runner:secret@db:5432/production",
        "postgresql+asyncpg://pastexam_test_runner:secret@db:5432/test_legacy",
    ],
)
def test_rejects_forbidden_or_legacy_database_names(test_url: str) -> None:
    with pytest.raises(ValueError, match="database name"):
        validate_test_database_target(
            test_database_url=test_url,
            runtime_database_url=RUNTIME_URL,
            isolation_confirmed="true",
        )


def test_requires_explicit_url_and_isolation_marker() -> None:
    with pytest.raises(ValueError, match="ISOLATED"):
        validate_test_database_target(
            test_database_url=VALID_TEST_URL,
            runtime_database_url=RUNTIME_URL,
            isolation_confirmed=None,
        )
    with pytest.raises(ValueError, match="TEST_DATABASE_URL"):
        validate_test_database_target(
            test_database_url=None,
            runtime_database_url=RUNTIME_URL,
            isolation_confirmed="true",
        )


def test_rejects_runtime_target_role_and_unapproved_host() -> None:
    with pytest.raises(ValueError, match="runtime database"):
        validate_test_database_target(
            test_database_url=VALID_TEST_URL,
            runtime_database_url=VALID_TEST_URL.replace(
                "postgresql+asyncpg", "postgresql+psycopg2"
            ),
            isolation_confirmed="true",
        )
    with pytest.raises(ValueError, match="role"):
        validate_test_database_target(
            test_database_url=VALID_TEST_URL.replace(
                "pastexam_test_runner", "runtime"
            ),
            runtime_database_url=RUNTIME_URL,
            isolation_confirmed="true",
        )
    with pytest.raises(ValueError, match="host"):
        validate_test_database_target(
            test_database_url=VALID_TEST_URL.replace("db:5432", "remote:5432"),
            runtime_database_url=RUNTIME_URL,
            isolation_confirmed="true",
        )


def test_connected_identity_must_match_configured_target() -> None:
    target = valid_target()
    validate_connected_test_database(
        actual_database_name=target.database_name,
        actual_user_name=target.user_name,
        actual_database_owner=target.user_name,
        is_superuser=False,
        can_create_database=False,
        can_create_role=False,
        target=target,
    )
    with pytest.raises(ValueError, match="database"):
        validate_connected_test_database(
            actual_database_name="archive_db",
            actual_user_name=target.user_name,
            actual_database_owner=target.user_name,
            is_superuser=False,
            can_create_database=False,
            can_create_role=False,
            target=target,
        )
    with pytest.raises(ValueError, match="role"):
        validate_connected_test_database(
            actual_database_name=target.database_name,
            actual_user_name="runtime",
            actual_database_owner=target.user_name,
            is_superuser=False,
            can_create_database=False,
            can_create_role=False,
            target=target,
        )


def test_connected_role_must_own_database_without_cluster_privileges() -> None:
    target = valid_target()
    with pytest.raises(ValueError, match="own"):
        validate_connected_test_database(
            actual_database_name=target.database_name,
            actual_user_name=target.user_name,
            actual_database_owner="runtime",
            is_superuser=False,
            can_create_database=False,
            can_create_role=False,
            target=target,
        )
    with pytest.raises(ValueError, match="privileges"):
        validate_connected_test_database(
            actual_database_name=target.database_name,
            actual_user_name=target.user_name,
            actual_database_owner=target.user_name,
            is_superuser=True,
            can_create_database=False,
            can_create_role=False,
            target=target,
        )
