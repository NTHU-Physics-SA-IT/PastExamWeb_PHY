import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    ArchiveSubmission,
    ArchiveSubmissionAdminAction,
    PersonalNotificationType,
    SubmissionStatus,
)
from app.services.personal_notifications import enqueue_personal_notification
from app.utils.course_text import format_course_display_name

logger = logging.getLogger(__name__)

ARCHIVE_SUBMISSION_SELF_DELETE_CONSUMED_CODE = "archive_submission_self_delete_consumed"
ARCHIVE_SUBMISSION_SELF_DELETE_CONSUMED_MESSAGE = "此投稿的自助刪除資格已使用。"


class ArchiveSubmissionReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    TAKEDOWN = "takedown"
    REPUBLISH = "republish"


class ArchiveSubmissionTransitionClassification(str, Enum):
    TRANSITION = "transition"
    NO_OP = "no_op"
    ILLEGAL = "illegal"


class ArchiveSubmissionExpectedStateClassification(str, Enum):
    MISSING = "missing"
    MATCH = "match"
    STALE = "stale"


@dataclass(frozen=True)
class ArchiveSubmissionTransitionResult:
    action: ArchiveSubmissionReviewAction
    source_status: SubmissionStatus
    target_status: SubmissionStatus
    classification: ArchiveSubmissionTransitionClassification
    resulting_status: SubmissionStatus


_ACTION_TARGET_STATUS = {
    ArchiveSubmissionReviewAction.APPROVE: SubmissionStatus.APPROVED,
    ArchiveSubmissionReviewAction.REJECT: SubmissionStatus.REJECTED,
    ArchiveSubmissionReviewAction.TAKEDOWN: SubmissionStatus.TAKEDOWN,
    ArchiveSubmissionReviewAction.REPUBLISH: SubmissionStatus.APPROVED,
}

_ADMIN_ACTION_POLICY = {
    SubmissionStatus.PENDING: (
        ArchiveSubmissionAdminAction.APPROVE,
        ArchiveSubmissionAdminAction.REJECT,
        ArchiveSubmissionAdminAction.TAKEDOWN,
        ArchiveSubmissionAdminAction.DELETE,
    ),
    SubmissionStatus.APPROVED: (
        ArchiveSubmissionAdminAction.REJECT,
        ArchiveSubmissionAdminAction.TAKEDOWN,
        ArchiveSubmissionAdminAction.DELETE,
    ),
    SubmissionStatus.REJECTED: (
        ArchiveSubmissionAdminAction.APPROVE,
        ArchiveSubmissionAdminAction.DELETE,
    ),
    SubmissionStatus.TAKEDOWN: (
        ArchiveSubmissionAdminAction.REPUBLISH,
        ArchiveSubmissionAdminAction.DELETE,
    ),
    SubmissionStatus.DELETED: (),
}

_REVIEW_TRANSITION_POLICY = {
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.APPROVE,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.REJECT,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.TAKEDOWN,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.REPUBLISH,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.PENDING,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.APPROVE,
    ): (
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.REJECT,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.REPUBLISH,
    ): (
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.APPROVE,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.REJECT,
    ): (
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.REPUBLISH,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.APPROVE,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.REJECT,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.TAKEDOWN,
    ): (
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.REPUBLISH,
    ): (
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.APPROVE,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.REJECT,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.REPUBLISH,
    ): (
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
}


def classify_archive_submission_review_transition(
    source_status: SubmissionStatus,
    action: ArchiveSubmissionReviewAction,
) -> ArchiveSubmissionTransitionResult:
    classification, resulting_status = _REVIEW_TRANSITION_POLICY[
        (source_status, action)
    ]
    return ArchiveSubmissionTransitionResult(
        action=action,
        source_status=source_status,
        target_status=_ACTION_TARGET_STATUS[action],
        classification=classification,
        resulting_status=resulting_status,
    )


def classify_archive_submission_expected_state(
    expected_status: SubmissionStatus | None,
    actual_status: SubmissionStatus,
) -> ArchiveSubmissionExpectedStateClassification:
    if expected_status is None:
        return ArchiveSubmissionExpectedStateClassification.MISSING
    if expected_status == actual_status:
        return ArchiveSubmissionExpectedStateClassification.MATCH
    return ArchiveSubmissionExpectedStateClassification.STALE


def available_archive_submission_admin_actions(
    status: SubmissionStatus,
) -> tuple[ArchiveSubmissionAdminAction, ...]:
    return _ADMIN_ACTION_POLICY[status]


_SUBMISSION_NOTIFICATION_COPY = {
    SubmissionStatus.APPROVED: ("考古題審核通過", "已通過審核"),
    SubmissionStatus.REJECTED: ("考古題投稿已退回", "已退回"),
    SubmissionStatus.TAKEDOWN: ("考古題已下架", "已下架"),
}


def normalize_submission_status(value) -> SubmissionStatus | None:
    if isinstance(value, SubmissionStatus):
        return value
    try:
        return SubmissionStatus(str(value).strip().lower())
    except ValueError:
        return None


def resolve_archive_submission_delete_source_status(
    value,
    *,
    operation: str,
) -> SubmissionStatus:
    """Return an exact supported pre-delete state or fail as static corruption."""

    normalized = normalize_submission_status(value)
    if normalized not in {
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.TAKEDOWN,
    }:
        logger.error(
            "archive_submission_delete_static_invariant operation=%s status_type=%s",
            operation,
            type(value).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        )
    return normalized


def archive_submission_self_delete_consumed_error() -> HTTPException:
    """Return the stable public conflict for consumed owner delete eligibility."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": ARCHIVE_SUBMISSION_SELF_DELETE_CONSUMED_CODE,
            "message": ARCHIVE_SUBMISSION_SELF_DELETE_CONSUMED_MESSAGE,
            "reload_required": False,
        },
    )


def resolve_archive_submission_actual_status(
    value,
    *,
    deleted_at,
) -> SubmissionStatus | None:
    if deleted_at is not None:
        return SubmissionStatus.DELETED
    return normalize_submission_status(value)


async def enqueue_submission_status_notification(
    db: AsyncSession,
    submission: ArchiveSubmission,
    new_status: SubmissionStatus,
) -> None:
    title, status_label = _SUBMISSION_NOTIFICATION_COPY[new_status]
    type_by_status = {
        SubmissionStatus.APPROVED: PersonalNotificationType.ARCHIVE_SUBMISSION_APPROVED,
        SubmissionStatus.REJECTED: PersonalNotificationType.ARCHIVE_SUBMISSION_REJECTED,
        SubmissionStatus.TAKEDOWN: PersonalNotificationType.ARCHIVE_SUBMISSION_TAKEDOWN,
    }
    course_name = format_course_display_name(
        submission.requested_course_name or submission.subject
    )
    await enqueue_personal_notification(
        db,
        user_id=submission.requester_id,
        notification_type=type_by_status[new_status],
        title=title,
        message=(
            f"{course_name}－{submission.name}（投稿編號 #{submission.id}）{status_label}。"
            "請前往「我的投稿狀態」查看詳情。"
        ),
        source_type="archive_submission",
        source_id=submission.id,
        metadata={
            "submission_id": submission.id,
            "archive_id": submission.created_archive_id,
            "course_name": course_name,
            "archive_name": submission.name,
            "status": new_status.value,
            "destination": "my_submission_status",
        },
        dedupe_key=f"archive_submission_status:{submission.id}:{new_status.value}",
    )


async def take_down_archive_submission(
    db: AsyncSession,
    submission: ArchiveSubmission,
    *,
    reviewer_id: int,
    note: str | None = None,
) -> None:
    current_status = normalize_submission_status(submission.status)
    if submission.deleted_at is not None or current_status in {
        SubmissionStatus.DELETED,
        SubmissionStatus.TAKEDOWN,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission cannot be taken down from its current status",
        )
    submission.status = SubmissionStatus.TAKEDOWN
    submission.reviewer_id = reviewer_id
    submission.review_note = note if note is not None else submission.review_note
    submission.reviewed_at = datetime.now(timezone.utc)
    await enqueue_submission_status_notification(
        db, submission, SubmissionStatus.TAKEDOWN
    )


async def republish_archive_submission(
    db: AsyncSession,
    submission: ArchiveSubmission,
    *,
    reviewer_id: int,
    note: str | None = None,
) -> None:
    current_status = normalize_submission_status(submission.status)
    if submission.deleted_at is not None or current_status == SubmissionStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此投稿已刪除，無法重新上架。",
        )
    if current_status != SubmissionStatus.TAKEDOWN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only taken down submissions can be republished",
        )

    takedown_transition = (
        submission.reviewed_at.isoformat() if submission.reviewed_at else "unknown"
    )
    course_name = format_course_display_name(
        submission.requested_course_name or submission.subject
    )
    submission.status = SubmissionStatus.APPROVED
    submission.lifecycle_reason = None
    submission.reviewer_id = reviewer_id
    submission.review_note = note if note is not None else submission.review_note
    submission.reviewed_at = datetime.now(timezone.utc)
    await enqueue_personal_notification(
        db,
        user_id=submission.requester_id,
        notification_type=PersonalNotificationType.ARCHIVE_SUBMISSION_REPUBLISHED,
        title="考古題已重新上架",
        message=(
            f"{course_name}－{submission.name}（投稿編號 #{submission.id}）已重新上架，"
            "目前已恢復為「已通過」並公開。請前往「我的投稿狀態」查看詳情。"
        ),
        source_type="archive_submission",
        source_id=submission.id,
        metadata={
            "submission_id": submission.id,
            "archive_id": submission.created_archive_id,
            "course_name": course_name,
            "archive_name": submission.name,
            "status": SubmissionStatus.APPROVED.value,
            "action": "republished",
            "destination": "my_submission_status",
        },
        dedupe_key=(
            f"archive_submission_republished:{submission.id}:{takedown_transition}"
        ),
    )
