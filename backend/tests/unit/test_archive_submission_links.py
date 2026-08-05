from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services.archive_submission_links import (
    ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL,
    ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT,
    ArchiveSubmissionOneToOneInvariantError,
    archive_submission_link_conflict,
    ensure_archive_submission_link_available,
    is_archive_submission_link_unique_violation,
    validate_archive_source_submission_rows,
)


class _Diagnostic:
    def __init__(self, constraint_name: str | None) -> None:
        self.constraint_name = constraint_name


class _DatabaseError(Exception):
    def __init__(
        self,
        *,
        sqlstate: str,
        constraint_name: str | None,
    ) -> None:
        super().__init__("sanitized database error")
        self.sqlstate = sqlstate
        self.diag = _Diagnostic(constraint_name)


def _integrity_error(
    *,
    sqlstate: str,
    constraint_name: str | None,
) -> IntegrityError:
    return IntegrityError(
        "sanitized statement",
        {},
        _DatabaseError(
            sqlstate=sqlstate,
            constraint_name=constraint_name,
        ),
    )


@pytest.mark.parametrize(
    ("sqlstate", "constraint_name", "expected"),
    [
        ("23505", ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT, True),
        ("23505", "uq_users_email", False),
        ("23503", ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT, False),
        ("23514", ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT, False),
        ("40P01", ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT, False),
        ("55P03", ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT, False),
    ],
)
def test_named_unique_violation_classifier_is_exact(
    sqlstate: str,
    constraint_name: str,
    expected: bool,
) -> None:
    assert (
        is_archive_submission_link_unique_violation(
            _integrity_error(
                sqlstate=sqlstate,
                constraint_name=constraint_name,
            )
        )
        is expected
    )


def test_link_conflict_uses_the_approved_structured_contract() -> None:
    error = archive_submission_link_conflict()

    assert error.status_code == 409
    assert error.detail == ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL
    assert error.detail == {
        "code": "archive_submission_link_conflict",
        "message": "This archive is already linked to another submission.",
    }


class _Rows:
    def __init__(self, row: tuple[int, int | None]) -> None:
        self._row = row

    def one(self) -> tuple[int, int | None]:
        return self._row


class _FakeSession:
    def __init__(self, row: tuple[int, int | None]) -> None:
        self.row = row
        self.execute_calls = 0

    async def execute(self, _statement):
        self.execute_calls += 1
        return _Rows(self.row)


@pytest.mark.asyncio
async def test_link_guard_allows_null_unoccupied_and_same_link() -> None:
    null_session = _FakeSession((0, None))
    await ensure_archive_submission_link_available(
        null_session,
        submission_id=10,
        current_archive_id=None,
        target_archive_id=None,
        operation="approval",
    )
    assert null_session.execute_calls == 0

    unoccupied_session = _FakeSession((0, None))
    await ensure_archive_submission_link_available(
        unoccupied_session,
        submission_id=10,
        current_archive_id=None,
        target_archive_id=20,
        operation="approval",
    )

    same_link_session = _FakeSession((1, 10))
    await ensure_archive_submission_link_available(
        same_link_session,
        submission_id=10,
        current_archive_id=20,
        target_archive_id=20,
        operation="restore",
    )


@pytest.mark.asyncio
async def test_link_guard_rejects_relink_as_internal_invariant(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession((0, None))

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ArchiveSubmissionOneToOneInvariantError),
    ):
        await ensure_archive_submission_link_available(
            session,
            submission_id=10,
            current_archive_id=20,
            target_archive_id=21,
            operation="approval",
        )

    assert session.execute_calls == 0
    record = caplog.records[-1]
    assert record.event == "archive_submission_one_to_one_invariant_violation"
    assert record.operation == "approval"
    assert record.invariant == "non_null_relink_forbidden"
    assert "10" not in record.getMessage()
    assert "20" not in record.getMessage()
    assert "21" not in record.getMessage()


@pytest.mark.asyncio
async def test_link_guard_returns_conflict_for_another_occupant() -> None:
    session = _FakeSession((1, 11))

    with pytest.raises(HTTPException) as exc_info:
        await ensure_archive_submission_link_available(
            session,
            submission_id=10,
            current_archive_id=None,
            target_archive_id=20,
            operation="approval",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL


@pytest.mark.asyncio
async def test_link_guard_fails_closed_for_multiple_occupants(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession((2, 10))

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ArchiveSubmissionOneToOneInvariantError),
    ):
        await ensure_archive_submission_link_available(
            session,
            submission_id=10,
            current_archive_id=20,
            target_archive_id=20,
            operation="restore",
        )

    record = caplog.records[-1]
    assert record.event == "archive_submission_one_to_one_invariant_violation"
    assert record.operation == "restore"
    assert record.invariant == "multiple_archive_occupants"
    assert record.occupant_count == 2
    assert record.constraint_name == ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT
    assert "10" not in record.getMessage()
    assert "11" not in record.getMessage()
    assert "20" not in record.getMessage()


def test_source_submission_rows_allow_zero_or_one_source() -> None:
    assert validate_archive_source_submission_rows([], operation="source_lookup") == {}
    assert validate_archive_source_submission_rows(
        [(20, 10)],
        operation="source_lookup",
    ) == {20: [10]}


def test_source_submission_rows_fail_closed_instead_of_truncating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ArchiveSubmissionOneToOneInvariantError),
    ):
        validate_archive_source_submission_rows(
            [(20, 10), (20, 11)],
            operation="source_lookup",
        )

    record = caplog.records[-1]
    assert record.event == "archive_submission_one_to_one_invariant_violation"
    assert record.operation == "source_lookup"
    assert record.invariant == "multiple_archive_occupants"
    assert record.duplicate_group_count == 1
    assert record.affected_row_count == 2
    assert record.occupant_count == 2
    assert "10" not in record.getMessage()
    assert "11" not in record.getMessage()
    assert "20" not in record.getMessage()
