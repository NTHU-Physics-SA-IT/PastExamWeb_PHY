from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.archive_report_uniqueness import (
    ARCHIVE_REPORT_PENDING_UNIQUE_INDEX,
    acquire_archive_report_uniqueness_mutex,
    archive_report_pending_conflict_error,
    archive_report_restore_pending_conflict_error,
    archive_report_uniqueness_scope,
    is_archive_report_pending_unique_violation,
)


class _Diagnostic:
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class _DriverError(Exception):
    def __init__(self, *, sqlstate: str, constraint_name: str) -> None:
        super().__init__("database integrity failure")
        self.sqlstate = sqlstate
        self.diag = _Diagnostic(constraint_name)


class _WrappedError(Exception):
    def __init__(self, original: BaseException) -> None:
        super().__init__("wrapped")
        self.orig = original


def test_archive_report_uniqueness_scope_is_exact_and_stable() -> None:
    assert (
        archive_report_uniqueness_scope(reporter_user_id=17, archive_id=29)
        == "archive_report_pending:17:29"
    )


@pytest.mark.asyncio
async def test_mutex_uses_transaction_advisory_lock_for_exact_scope() -> None:
    db = AsyncMock()

    scope = await acquire_archive_report_uniqueness_mutex(
        db,
        reporter_user_id=17,
        archive_id=29,
    )

    assert scope == "archive_report_pending:17:29"
    statement, parameters = db.execute.await_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert parameters == {"scope_key": scope}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reporter_user_id", "archive_id"),
    [(None, 29), (17, None)],
)
async def test_mutex_skips_nullable_detached_scope(
    reporter_user_id: int | None,
    archive_id: int | None,
) -> None:
    db = AsyncMock()

    assert (
        await acquire_archive_report_uniqueness_mutex(
            db,
            reporter_user_id=reporter_user_id,
            archive_id=archive_id,
        )
        is None
    )
    db.execute.assert_not_awaited()


def test_named_postgresql_violation_is_the_only_duplicate_match() -> None:
    expected = _WrappedError(
        _DriverError(
            sqlstate="23505",
            constraint_name=ARCHIVE_REPORT_PENDING_UNIQUE_INDEX,
        )
    )
    wrong_constraint = _WrappedError(
        _DriverError(sqlstate="23505", constraint_name="other_unique_constraint")
    )
    wrong_state = _WrappedError(
        _DriverError(
            sqlstate="23503",
            constraint_name=ARCHIVE_REPORT_PENDING_UNIQUE_INDEX,
        )
    )

    assert is_archive_report_pending_unique_violation(expected) is True
    assert is_archive_report_pending_unique_violation(wrong_constraint) is False
    assert is_archive_report_pending_unique_violation(wrong_state) is False
    assert is_archive_report_pending_unique_violation(RuntimeError("other")) is False


@pytest.mark.parametrize(
    ("factory", "code", "message"),
    [
        (
            archive_report_pending_conflict_error,
            "archive_report_pending_conflict",
            "You already have an active pending report for this archive.",
        ),
        (
            archive_report_restore_pending_conflict_error,
            "archive_report_restore_pending_conflict",
            "Another active pending report prevents restoration.",
        ),
    ],
)
def test_conflict_errors_are_stable_structured_409(factory, code, message) -> None:
    error = factory()

    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert error.detail == {
        "code": code,
        "message": message,
        "reload_required": False,
    }
