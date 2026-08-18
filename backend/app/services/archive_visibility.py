"""Canonical effective-public Archive predicates shared by archive consumers."""

from sqlalchemy import exists, or_

from app.models.models import Archive, ArchiveSubmission, SubmissionStatus


def public_archive_conditions(
    course_id: int | None = None,
    archive_id: int | None = None,
) -> list:
    trashed_submission_exists = exists().where(
        ArchiveSubmission.created_archive_id == Archive.id,
        or_(
            ArchiveSubmission.deleted_at.is_not(None),
            ArchiveSubmission.status == SubmissionStatus.DELETED,
        ),
    )
    non_public_submission_exists = exists().where(
        ArchiveSubmission.created_archive_id == Archive.id,
        ArchiveSubmission.deleted_at.is_(None),
        ArchiveSubmission.status != SubmissionStatus.APPROVED,
    )
    conditions = [
        Archive.deleted_at.is_(None),
        ~trashed_submission_exists,
        ~non_public_submission_exists,
    ]
    if course_id is not None:
        conditions.append(Archive.course_id == course_id)
    if archive_id is not None:
        conditions.append(Archive.id == archive_id)
    return conditions
