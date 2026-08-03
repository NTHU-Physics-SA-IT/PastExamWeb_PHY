from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import ArchiveSubmission


logger = logging.getLogger(__name__)

ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT = "uq_archive_submissions_created_archive_id"
ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL = {
    "code": "archive_submission_link_conflict",
    "message": "This archive is already linked to another submission.",
}

ArchiveSubmissionLinkOperation = Literal[
    "approval",
    "review",
    "restore",
    "archive_trash",
    "archive_restore",
    "source_lookup",
]


class ArchiveSubmissionOneToOneInvariantError(RuntimeError):
    """An internal relationship invariant failed without a safe public outcome."""


def archive_submission_link_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=dict(ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL),
    )


def _log_invariant_violation(
    *,
    operation: ArchiveSubmissionLinkOperation,
    invariant: str,
    occupant_count: int,
    duplicate_group_count: int = 0,
    affected_row_count: int = 0,
) -> None:
    logger.error(
        "archive_submission_one_to_one_invariant_violation",
        extra={
            "event": "archive_submission_one_to_one_invariant_violation",
            "operation": operation,
            "invariant": invariant,
            "occupant_count": occupant_count,
            "duplicate_group_count": duplicate_group_count,
            "affected_row_count": affected_row_count,
            "constraint_name": ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT,
        },
    )


def _raise_invariant_violation(
    *,
    operation: ArchiveSubmissionLinkOperation,
    invariant: str,
    occupant_count: int,
    duplicate_group_count: int = 0,
    affected_row_count: int = 0,
) -> None:
    _log_invariant_violation(
        operation=operation,
        invariant=invariant,
        occupant_count=occupant_count,
        duplicate_group_count=duplicate_group_count,
        affected_row_count=affected_row_count,
    )
    raise ArchiveSubmissionOneToOneInvariantError(
        "ArchiveSubmission/Archive one-to-one invariant violated"
    )


async def ensure_archive_submission_link_available(
    db: AsyncSession,
    *,
    submission_id: int | None,
    current_archive_id: int | None,
    target_archive_id: int | None,
    operation: ArchiveSubmissionLinkOperation,
) -> None:
    """Fail before mutation when an exact Archive link is not safely claimable."""
    if target_archive_id is None:
        return

    if current_archive_id is not None and current_archive_id != target_archive_id:
        _raise_invariant_violation(
            operation=operation,
            invariant="non_null_relink_forbidden",
            occupant_count=0,
        )

    occupant_count, occupant_id = (
        await db.execute(
            select(
                func.count(ArchiveSubmission.id),
                func.min(ArchiveSubmission.id),
            ).where(ArchiveSubmission.created_archive_id == target_archive_id)
        )
    ).one()
    occupant_count = int(occupant_count or 0)

    if occupant_count > 1:
        _raise_invariant_violation(
            operation=operation,
            invariant="multiple_archive_occupants",
            occupant_count=occupant_count,
            duplicate_group_count=1,
            affected_row_count=occupant_count,
        )

    if occupant_count == 1 and occupant_id != submission_id:
        raise archive_submission_link_conflict()


def validate_archive_source_membership(
    submission_ids: Iterable[int | None],
    *,
    operation: ArchiveSubmissionLinkOperation,
) -> tuple[int, ...]:
    """Return one exact source at most, or fail closed as an integrity anomaly."""
    normalized_ids = tuple(
        sorted(
            {
                submission_id
                for submission_id in submission_ids
                if submission_id is not None
            }
        )
    )
    if len(normalized_ids) > 1:
        _raise_invariant_violation(
            operation=operation,
            invariant="multiple_archive_occupants",
            occupant_count=len(normalized_ids),
            duplicate_group_count=1,
            affected_row_count=len(normalized_ids),
        )
    return normalized_ids


def validate_archive_source_submission_rows(
    rows: Iterable[tuple[int | None, int | None]],
    *,
    operation: Literal["source_lookup"] = "source_lookup",
) -> dict[int, list[int]]:
    """Build the compatibility array only after validating one-to-one cardinality."""
    submission_ids_by_archive: dict[int, set[int]] = {}
    for archive_id, submission_id in rows:
        if archive_id is None or submission_id is None:
            continue
        submission_ids_by_archive.setdefault(archive_id, set()).add(submission_id)

    duplicate_sizes = [
        len(submission_ids)
        for submission_ids in submission_ids_by_archive.values()
        if len(submission_ids) > 1
    ]
    if duplicate_sizes:
        _raise_invariant_violation(
            operation=operation,
            invariant="multiple_archive_occupants",
            occupant_count=max(duplicate_sizes),
            duplicate_group_count=len(duplicate_sizes),
            affected_row_count=sum(duplicate_sizes),
        )

    return {
        archive_id: list(
            validate_archive_source_membership(
                submission_ids,
                operation=operation,
            )
        )
        for archive_id, submission_ids in submission_ids_by_archive.items()
    }


def is_archive_submission_link_unique_violation(error: BaseException) -> bool:
    """Match only PostgreSQL 23505 from the named one-to-one constraint."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current, "pgcode", None
        )
        diagnostic = getattr(current, "diag", None)
        constraint_name = getattr(current, "constraint_name", None) or getattr(
            diagnostic,
            "constraint_name",
            None,
        )
        if (
            sqlstate == "23505"
            and constraint_name == ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT
        ):
            return True
        current = (
            getattr(current, "orig", None)
            or getattr(current, "__cause__", None)
            or getattr(current, "__context__", None)
        )
    return False
