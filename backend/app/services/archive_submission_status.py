from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    ArchiveSubmission,
    PersonalNotificationType,
    SubmissionStatus,
)
from app.services.personal_notifications import enqueue_personal_notification
from app.utils.course_text import format_course_display_name


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
