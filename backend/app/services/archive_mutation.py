"""Archive metadata and reparent planning on canonical lifecycle locks."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import Archive, ArchiveSubmission, Course
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
from app.utils.course_text import normalized_course_text_expr


logger = logging.getLogger(__name__)

ARCHIVE_MOVE_TARGET_NOT_FOUND_DETAIL = {
    "code": "archive_move_target_course_not_found",
    "message": "目標課程不存在，請先建立課程。",
    "reload_required": False,
}
ARCHIVE_MOVE_TARGET_TRASHED_DETAIL = {
    "code": "course_lifecycle_conflict",
    "message": "目標課程已在垃圾桶，請先恢復課程。",
    "reload_required": False,
}


class ArchiveMoveTargetInvariantError(RuntimeError):
    """Normalized target data contains more than one active Course."""


class ArchiveMutationLifecycleConflict(RuntimeError):
    """Archive membership did not stabilize within the bounded retry."""


@dataclass(frozen=True)
class ArchiveMoveTarget:
    course_id: int
    normalized_name: str | None = None
    category: str | None = None


def archive_move_target_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=dict(ARCHIVE_MOVE_TARGET_NOT_FOUND_DETAIL),
    )


def archive_move_target_trashed_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=dict(ARCHIVE_MOVE_TARGET_TRASHED_DETAIL),
    )


def _raise_ambiguous_active_target(
    *,
    active_count: int,
    trashed_count: int,
) -> None:
    logger.error(
        "archive_move_target_course_invariant_violation",
        extra={
            "event": "archive_move_target_course_invariant_violation",
            "invariant": "multiple_active_normalized_courses",
            "active_match_count": active_count,
            "trashed_match_count": trashed_count,
        },
    )
    raise ArchiveMoveTargetInvariantError(
        "Archive move target Course identity is ambiguous"
    )


async def resolve_archive_move_target(
    db: AsyncSession,
    *,
    course_id: int | None,
    normalized_name: str | None,
    category: str | None,
) -> ArchiveMoveTarget:
    """Resolve one legal target without creating, restoring, or mutating a Course."""

    if course_id is not None:
        course = (
            await db.execute(select(Course).where(Course.id == course_id))
        ).scalar_one_or_none()
        if course is None:
            raise archive_move_target_not_found_error()
        if course.deleted_at is not None:
            raise archive_move_target_trashed_error()
        return ArchiveMoveTarget(course_id=course.id)

    if not normalized_name or not category:
        raise ValueError("Archive move target input is incomplete")

    matches = tuple(
        (
            await db.execute(
                select(Course)
                .where(
                    normalized_course_text_expr(Course.name) == normalized_name,
                    Course.category == category,
                )
                .order_by(Course.id.asc())
            )
        )
        .scalars()
        .all()
    )
    active = tuple(course for course in matches if course.deleted_at is None)
    trashed_count = len(matches) - len(active)

    if len(active) > 1:
        _raise_ambiguous_active_target(
            active_count=len(active),
            trashed_count=trashed_count,
        )
    if len(active) == 1:
        return ArchiveMoveTarget(
            course_id=active[0].id,
            normalized_name=normalized_name,
            category=category,
        )
    if matches:
        raise archive_move_target_trashed_error()
    raise archive_move_target_not_found_error()


async def _discover_archive_mutation_plan(
    db: AsyncSession,
    *,
    archive_id: int,
    target_course_id: int | None,
    operation: ArchiveSubmissionLinkOperation,
) -> ArchiveLifecycleLockPlan | None:
    archive = (
        await db.execute(
            select(Archive)
            .where(Archive.id == archive_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if archive is None or archive.id is None:
        return None

    sibling_ids = validate_archive_source_membership(
        (
            (
                await db.execute(
                    select(ArchiveSubmission.id)
                    .where(ArchiveSubmission.created_archive_id == archive.id)
                    .order_by(ArchiveSubmission.id.asc())
                )
            )
            .scalars()
            .all()
        ),
        operation=operation,
    )
    fingerprint = LifecycleMembershipFingerprint(
        archive_course_pairs=((archive.id, archive.course_id),),
        sibling_submission_ids=sibling_ids,
    )
    return ArchiveLifecycleLockPlan.build(
        course_ids=(archive.course_id, target_course_id),
        archive_ids=(archive.id,),
        submission_ids=sibling_ids,
        fingerprint=fingerprint,
    )


async def acquire_stable_archive_mutation_locks(
    db: AsyncSession,
    *,
    archive_id: int,
    target_course_id: int | None,
    operation: ArchiveSubmissionLinkOperation,
) -> LockedLifecycleRows | None:
    """Acquire a complete mutation plan, rebuilding once on relationship drift."""

    budget = PlanRebuildBudget()
    while True:
        plan = await _discover_archive_mutation_plan(
            db,
            archive_id=archive_id,
            target_course_id=target_course_id,
            operation=operation,
        )
        if plan is None:
            return None
        locked = await archive_lifecycle_locks.acquire_lifecycle_locks(db, plan)
        revalidation = await archive_lifecycle_locks.revalidate_lifecycle_membership(
            db,
            locked,
        )
        if revalidation.valid:
            return locked

        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted as error:
            logger.warning(
                "archive_mutation_lifecycle_revalidation_exhausted",
                extra={
                    "event": "archive_mutation_lifecycle_revalidation_exhausted",
                    "operation": operation,
                    "invariant": "exact_parent_membership",
                },
            )
            raise ArchiveMutationLifecycleConflict(
                "Archive mutation membership did not stabilize"
            ) from error
