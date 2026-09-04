"""Owner-only authority for active existing-Course Archive submissions."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    ArchiveSubmission,
    ArchiveType,
    ArchiveWish,
    Course,
    OwnerPendingArchiveSubmissionEdit,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleMembershipFingerprint,
    LifecyclePlanRetryExhausted,
    LockedLifecycleRows,
    PlanRebuildBudget,
)
from app.utils.course_text import normalize_course_search_text

OWNER_PENDING_NOT_ELIGIBLE_DETAIL = {
    "code": "owner_pending_submission_not_eligible",
    "message": "This submission is not an eligible existing-course pending submission.",
    "reload_required": False,
}
OWNER_PENDING_STALE_STATE_DETAIL = {
    "code": "archive_submission_stale_state",
    "message": "投稿狀態已變更，請重新載入後再操作。",
    "reload_required": True,
}


def is_existing_course_submission(submission: ArchiveSubmission) -> bool:
    return (
        submission.requested_course_name is None
        and submission.requested_category_key is None
    )


def canonical_submission_owner_id(submission: ArchiveSubmission) -> int | None:
    if submission.owner_id is not None and submission.owner_id != submission.requester_id:
        return None
    return submission.requester_id


def is_owner_pending_overlay_eligible(
    submission: ArchiveSubmission,
    *,
    user_id: int,
) -> bool:
    return (
        canonical_submission_owner_id(submission) == user_id
        and is_existing_course_submission(submission)
        and submission.deleted_at is None
        and submission.status == SubmissionStatus.PENDING
        and submission.created_archive_id is None
    )


def require_owner_pending_submission(
    submission: ArchiveSubmission | None,
    *,
    current_user: UserRoles,
) -> ArchiveSubmission:
    if current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrators must use the review-center routes",
        )
    if submission is None or canonical_submission_owner_id(submission) != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    if not is_existing_course_submission(submission):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=dict(OWNER_PENDING_NOT_ELIGIBLE_DETAIL),
        )
    if (
        submission.deleted_at is not None
        or submission.status != SubmissionStatus.PENDING
        or submission.created_archive_id is not None
    ):
        detail = dict(OWNER_PENDING_STALE_STATE_DETAIL)
        detail["actual_status"] = submission.status.value
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return submission


async def acquire_owner_pending_edit_locks(
    db: AsyncSession,
    *,
    submission_id: int,
    course_id: int,
) -> LockedLifecycleRows | None:
    """Lock target Course before Submission and revalidate its stable identity."""

    budget = PlanRebuildBudget()
    while True:
        submission = (
            await db.execute(
                select(ArchiveSubmission)
                .where(ArchiveSubmission.id == submission_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if submission is None or submission.id is None:
            return None
        course = (
            await db.execute(
                select(Course)
                .where(Course.id == course_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if course is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found",
            )
        plan = ArchiveLifecycleLockPlan.build(
            course_ids=(course_id,),
            submission_ids=(submission_id,),
            fingerprint=LifecycleMembershipFingerprint(
                target_submission_id=submission.id,
                target_created_archive_id=submission.created_archive_id,
                target_requester_id=submission.requester_id,
                target_owner_id=submission.owner_id,
            ),
        )
        locked = await archive_lifecycle_locks.acquire_lifecycle_locks(db, plan)
        revalidation = await archive_lifecycle_locks.revalidate_lifecycle_membership(
            db, locked
        )
        if revalidation.valid:
            return locked
        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=dict(OWNER_PENDING_STALE_STATE_DETAIL),
            ) from None


def normalized_owner_exam_name(data: OwnerPendingArchiveSubmissionEdit) -> str:
    if data.archive_type == ArchiveType.MIDTERM:
        return f"midterm{data.sequence}"
    if data.archive_type == ArchiveType.QUIZ:
        return f"quiz{data.sequence}"
    if data.archive_type == ArchiveType.FINAL:
        return "final"
    if data.other_name is None:
        raise ValueError("Validated other exam name is missing")
    return data.other_name


async def ensure_source_wish_target_matches(
    db: AsyncSession,
    *,
    submission: ArchiveSubmission,
    course: Course,
    professor: str,
    archive_type: ArchiveType,
    name: str,
) -> None:
    if submission.source_wish_id is None:
        return
    wish = await db.get(ArchiveWish, submission.source_wish_id)
    if wish is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "wish_upload_target_mismatch",
                "message": "Help Upload target is no longer available",
            },
        )
    course_matches = (
        wish.course_id == course.id
        if wish.course_id is not None
        else normalize_course_search_text(wish.requested_course_name or wish.subject)
        == normalize_course_search_text(course.name)
    )
    target_matches = all(
        (
            course_matches,
            (wish.category or "").strip().lower()
            == (course.category or "").strip().lower(),
            (wish.professor or "").strip().lower() == professor.strip().lower(),
            wish.archive_type == archive_type,
            (wish.name or "").strip().lower() == name.strip().lower(),
        )
    )
    if not target_matches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "wish_upload_target_mismatch",
                "message": "Help Upload target must match the selected wish",
            },
        )
