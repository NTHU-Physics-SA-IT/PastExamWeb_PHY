"""Fail-closed validation for destructive test database operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.engine import URL, make_url


TEST_DATABASE_PREFIX = "pastexam_test_"
TEST_ROLE_PREFIX = "pastexam_test_"
DEFAULT_ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "db"})
FORBIDDEN_DATABASE_NAMES = frozenset(
    {
        "archive_db",
        "postgres",
        "template0",
        "template1",
        "production",
        "prod",
    }
)


@dataclass(frozen=True)
class TestDatabaseTarget:
    url: URL
    database_name: str
    user_name: str
    host_name: str


def _canonical_target(url: URL) -> tuple[str, int, str, str]:
    return (
        (url.host or "").strip().lower(),
        int(url.port or 5432),
        (url.username or "").strip(),
        (url.database or "").strip().lower(),
    )


def _normalized_allowed_hosts(values: Iterable[str]) -> set[str]:
    return {
        value.strip().lower()
        for value in values
        if value and value.strip()
    }


def validate_test_database_target(
    *,
    test_database_url: str | None,
    runtime_database_url: str,
    isolation_confirmed: str | None,
    allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_TEST_HOSTS,
) -> TestDatabaseTarget:
    """Validate configuration before opening a destructive test connection."""
    if str(isolation_confirmed or "").strip().lower() != "true":
        raise ValueError(
            "PASTEXAM_TEST_DATABASE_ISOLATED=true is required for database tests"
        )
    if not test_database_url:
        raise ValueError("TEST_DATABASE_URL must be explicitly configured")

    test_url = make_url(test_database_url)
    runtime_url = make_url(runtime_database_url)
    database_name = (test_url.database or "").strip().lower()
    user_name = (test_url.username or "").strip()
    host_name = (test_url.host or "").strip().lower()

    if (
        not database_name.startswith(TEST_DATABASE_PREFIX)
        or database_name in FORBIDDEN_DATABASE_NAMES
        or "production" in database_name
    ):
        raise ValueError(
            f"Test database name must start with {TEST_DATABASE_PREFIX!r}"
        )
    if not user_name.startswith(TEST_ROLE_PREFIX):
        raise ValueError(
            f"Test database role must start with {TEST_ROLE_PREFIX!r}"
        )
    if host_name not in _normalized_allowed_hosts(allowed_hosts):
        raise ValueError(f"Test database host is not allowed: {host_name!r}")
    if _canonical_target(test_url) == _canonical_target(runtime_url):
        raise ValueError("TEST_DATABASE_URL must not target the runtime database")

    return TestDatabaseTarget(
        url=test_url,
        database_name=database_name,
        user_name=user_name,
        host_name=host_name,
    )


def validate_connected_test_database(
    *,
    actual_database_name: str | None,
    actual_user_name: str | None,
    actual_database_owner: str | None,
    is_superuser: bool,
    can_create_database: bool,
    can_create_role: bool,
    target: TestDatabaseTarget,
) -> None:
    """Validate server-reported identity before a destructive fixture runs."""
    if str(actual_database_name or "").strip().lower() != target.database_name:
        raise ValueError("Connected database does not match TEST_DATABASE_URL")
    if str(actual_user_name or "").strip() != target.user_name:
        raise ValueError("Connected role does not match TEST_DATABASE_URL")
    if str(actual_database_owner or "").strip() != target.user_name:
        raise ValueError("Isolated test role must own only its test database")
    if is_superuser or can_create_database or can_create_role:
        raise ValueError("Isolated test role has unsafe cluster-level privileges")
