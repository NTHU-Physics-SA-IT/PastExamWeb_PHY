"""Active-pending ArchiveReport uniqueness and conflict ownership."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import ArchiveReport

ARCHIVE_REPORT_PENDING_UNIQUE_INDEX = "uq_archive_reports_pending_reporter_archive"
ARCHIVE_REPORT_PENDING_CONFLICT_CODE = "archive_report_pending_conflict"
ARCHIVE_REPORT_PENDING_CONFLICT_MESSAGE = (
    "You already have an active pending report for this archive."
)
ARCHIVE_REPORT_RESTORE_PENDING_CONFLICT_CODE = "archive_report_restore_pending_conflict"
ARCHIVE_REPORT_RESTORE_PENDING_CONFLICT_MESSAGE = (
    "Another active pending report prevents restoration."
)


def archive_report_uniqueness_scope(
    *,
    reporter_user_id: int,
    archive_id: int,
) -> str:
    """Return the transaction-mutex namespace for one active-pending scope."""

    return f"archive_report_pending:{reporter_user_id}:{archive_id}"


async def acquire_archive_report_uniqueness_mutex(
    db: AsyncSession,
    *,
    reporter_user_id: int | None,
    archive_id: int | None,
) -> str | None:
    """Serialize writers when both nullable uniqueness keys are present."""

    if reporter_user_id is None or archive_id is None:
        return None
    scope = archive_report_uniqueness_scope(
        reporter_user_id=reporter_user_id,
        archive_id=archive_id,
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": scope},
    )
    return scope


async def acquire_archive_report_uniqueness_mutex_for_report(
    db: AsyncSession,
    *,
    report_id: int,
) -> bool:
    """Discover one report scope before row locks and acquire its mutex."""

    row = (
        await db.execute(
            select(
                ArchiveReport.reporter_user_id,
                ArchiveReport.archive_id,
            ).where(ArchiveReport.id == report_id)
        )
    ).one_or_none()
    if row is None:
        return False
    await acquire_archive_report_uniqueness_mutex(
        db,
        reporter_user_id=row[0],
        archive_id=row[1],
    )
    return True


def is_archive_report_pending_unique_violation(error: BaseException) -> bool:
    """Match only PostgreSQL 23505 from the named pending-report index."""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current,
            "pgcode",
            None,
        )
        diagnostic = getattr(current, "diag", None)
        constraint_name = getattr(current, "constraint_name", None) or getattr(
            diagnostic,
            "constraint_name",
            None,
        )
        if (
            sqlstate == "23505"
            and constraint_name == ARCHIVE_REPORT_PENDING_UNIQUE_INDEX
        ):
            return True
        current = (
            getattr(current, "orig", None)
            or getattr(current, "__cause__", None)
            or getattr(current, "__context__", None)
        )
    return False


def archive_report_pending_conflict_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": ARCHIVE_REPORT_PENDING_CONFLICT_CODE,
            "message": ARCHIVE_REPORT_PENDING_CONFLICT_MESSAGE,
            "reload_required": False,
        },
    )


def archive_report_restore_pending_conflict_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": ARCHIVE_REPORT_RESTORE_PENDING_CONFLICT_CODE,
            "message": ARCHIVE_REPORT_RESTORE_PENDING_CONFLICT_MESSAGE,
            "reload_required": False,
        },
    )
