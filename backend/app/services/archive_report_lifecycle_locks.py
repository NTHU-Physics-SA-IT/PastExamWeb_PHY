"""Parent-first lock orchestration for ArchiveReport lifecycle writers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import Archive, ArchiveReport, ArchiveSubmission
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleMembershipFingerprint,
    LifecyclePlanRetryExhausted,
    LockedLifecycleRows,
    PlanRebuildBudget,
)
from app.services.archive_submission_links import (
    ArchiveSubmissionLinkOperation,
    validate_archive_source_membership,
)

logger = logging.getLogger(__name__)

ArchiveReportLifecycleOperation = Literal[
    "archive_report_review",
    "archive_report_trash",
    "archive_report_restore",
]


class ArchiveReportLifecycleInvariantError(RuntimeError):
    """A changing exact-parent relation could not be locked safely."""


@dataclass(frozen=True)
class ArchiveReportMembershipFingerprint:
    """Report state and exact FK identities observed before the first row lock."""

    report_id: int
    status: str
    deleted: bool
    reporter_user_id: int | None
    archive_id: int | None
    report_course_id: int | None
    archive_submission_id: int | None
    archive_present: bool
    archive_course_id: int | None
    submission_present: bool
    submission_created_archive_id: int | None
    archive_source_submission_ids: tuple[int, ...] | None


@dataclass(frozen=True)
class ArchiveReportLifecyclePlan:
    lock_plan: ArchiveLifecycleLockPlan
    fingerprint: ArchiveReportMembershipFingerprint


@dataclass(frozen=True)
class LockedArchiveReportLifecycle:
    rows: LockedLifecycleRows
    fingerprint: ArchiveReportMembershipFingerprint

    @property
    def report(self) -> ArchiveReport:
        report = self.rows.report(self.fingerprint.report_id)
        if report is None:
            raise ArchiveReportLifecycleInvariantError(
                "Locked ArchiveReport row is missing"
            )
        return report

    @property
    def archive(self) -> Archive | None:
        if self.fingerprint.archive_id is None:
            return None
        return self.rows.archive(self.fingerprint.archive_id)

    @property
    def submission(self) -> ArchiveSubmission | None:
        if self.fingerprint.archive_submission_id is None:
            return None
        return self.rows.submission(self.fingerprint.archive_submission_id)


def _status_value(report: ArchiveReport) -> str:
    return str(getattr(report.status, "value", report.status))


async def _discover_archive_source_ids(
    db: AsyncSession,
    *,
    archive_id: int,
    operation: ArchiveSubmissionLinkOperation,
) -> tuple[int, ...]:
    return validate_archive_source_membership(
        (
            (
                await db.execute(
                    select(ArchiveSubmission.id)
                    .where(ArchiveSubmission.created_archive_id == archive_id)
                    .order_by(ArchiveSubmission.id.asc())
                )
            )
            .scalars()
            .all()
        ),
        operation=operation,
    )


async def discover_archive_report_lifecycle_plan(
    db: AsyncSession,
    *,
    report_id: int,
    operation: ArchiveReportLifecycleOperation,
) -> ArchiveReportLifecyclePlan | None:
    """Discover one report and every exact parent before acquiring any row lock."""

    report = (
        await db.execute(
            select(ArchiveReport)
            .where(ArchiveReport.id == report_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if report is None or report.id is None:
        return None

    archive: Archive | None = None
    if report.archive_id is not None:
        archive = (
            await db.execute(
                select(Archive)
                .where(Archive.id == report.archive_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    submission: ArchiveSubmission | None = None
    if report.archive_submission_id is not None:
        submission = (
            await db.execute(
                select(ArchiveSubmission)
                .where(ArchiveSubmission.id == report.archive_submission_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    source_ids = (
        await _discover_archive_source_ids(
            db,
            archive_id=archive.id,
            operation=operation,
        )
        if archive is not None and archive.id is not None
        else None
    )
    fingerprint = ArchiveReportMembershipFingerprint(
        report_id=report.id,
        status=_status_value(report),
        deleted=report.deleted_at is not None,
        reporter_user_id=report.reporter_user_id,
        archive_id=report.archive_id,
        report_course_id=report.course_id,
        archive_submission_id=report.archive_submission_id,
        archive_present=archive is not None,
        archive_course_id=archive.course_id if archive is not None else None,
        submission_present=submission is not None,
        submission_created_archive_id=(
            submission.created_archive_id if submission is not None else None
        ),
        archive_source_submission_ids=source_ids,
    )
    lock_plan = ArchiveLifecycleLockPlan.build(
        course_ids=(archive.course_id,) if archive is not None else (),
        archive_ids=(archive.id,) if archive is not None else (),
        submission_ids=(submission.id,) if submission is not None else (),
        report_ids=(report.id,),
        fingerprint=LifecycleMembershipFingerprint(
            archive_course_pairs=(
                ((archive.id, archive.course_id),)
                if archive is not None and archive.id is not None
                else ()
            ),
            sibling_submission_ids=source_ids,
        ),
    )
    return ArchiveReportLifecyclePlan(
        lock_plan=lock_plan,
        fingerprint=fingerprint,
    )


async def _locked_fingerprint(
    db: AsyncSession,
    *,
    locked: LockedLifecycleRows,
    expected: ArchiveReportMembershipFingerprint,
    operation: ArchiveReportLifecycleOperation,
) -> ArchiveReportMembershipFingerprint | None:
    report = locked.report(expected.report_id)
    if report is None:
        return None

    archive = (
        locked.archive(report.archive_id) if report.archive_id is not None else None
    )
    submission = (
        locked.submission(report.archive_submission_id)
        if report.archive_submission_id is not None
        else None
    )
    source_ids = (
        await _discover_archive_source_ids(
            db,
            archive_id=archive.id,
            operation=operation,
        )
        if archive is not None and archive.id is not None
        else None
    )
    return ArchiveReportMembershipFingerprint(
        report_id=report.id,
        status=_status_value(report),
        deleted=report.deleted_at is not None,
        reporter_user_id=report.reporter_user_id,
        archive_id=report.archive_id,
        report_course_id=report.course_id,
        archive_submission_id=report.archive_submission_id,
        archive_present=archive is not None,
        archive_course_id=archive.course_id if archive is not None else None,
        submission_present=submission is not None,
        submission_created_archive_id=(
            submission.created_archive_id if submission is not None else None
        ),
        archive_source_submission_ids=source_ids,
    )


async def acquire_stable_archive_report_locks(
    db: AsyncSession,
    *,
    report_id: int,
    operation: ArchiveReportLifecycleOperation,
) -> LockedArchiveReportLifecycle | None:
    """Acquire one complete parent-first plan, rebuilding at most once."""

    budget = PlanRebuildBudget()
    while True:
        discovered = await discover_archive_report_lifecycle_plan(
            db,
            report_id=report_id,
            operation=operation,
        )
        if discovered is None:
            return None

        locked = await archive_lifecycle_locks.acquire_lifecycle_locks(
            db,
            discovered.lock_plan,
        )
        base_revalidation = (
            await archive_lifecycle_locks.revalidate_lifecycle_membership(
                db,
                locked,
            )
        )
        current = await _locked_fingerprint(
            db,
            locked=locked,
            expected=discovered.fingerprint,
            operation=operation,
        )
        if (
            base_revalidation.valid
            and current is not None
            and current == discovered.fingerprint
        ):
            return LockedArchiveReportLifecycle(
                rows=locked,
                fingerprint=current,
            )

        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted as error:
            logger.error(
                "archive_report_lifecycle_lock_revalidation_exhausted",
                extra={
                    "event": "archive_report_lifecycle_lock_revalidation_exhausted",
                    "operation": operation,
                    "invariant": "exact_parent_membership",
                },
            )
            raise ArchiveReportLifecycleInvariantError(
                "ArchiveReport exact parent membership did not stabilize"
            ) from error
