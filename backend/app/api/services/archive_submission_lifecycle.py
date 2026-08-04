from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from fastapi import HTTPException, status
from minio.error import S3Error
from sqlalchemy import and_, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.core.config import settings
from app.models.models import (
    Archive,
    ArchiveDiscussionMessage,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    SubmissionStatus,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    LockedLifecycleRows,
    PlanRebuildBudget,
)
from app.services.archive_submission_links import ArchiveSubmissionLinkOperation
from app.services.archive_submission_status import (
    resolve_archive_submission_delete_source_status,
)
from app.utils.storage import get_minio_client

LIFECYCLE_ARCHIVE_TRASHED = "archive_trashed"
LIFECYCLE_COURSE_TRASHED = "course_trashed"
LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED = "linked_archive_permanently_deleted"
COURSE_TRASH_LIFECYCLE_PREFIX = f"{LIFECYCLE_COURSE_TRASHED}|"
COURSE_TRASH_PREVIOUS_STATUS_KEY = "previous_status"
COURSE_TRASH_COURSE_ID_KEY = "course_id"
COURSE_TRASH_ARCHIVE_ID_KEY = "archive_id"
ARCHIVE_LIFECYCLE_CONFLICT_CODE = "archive_lifecycle_conflict"
ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE = (
    "Archive lifecycle changed during this request. Please retry."
)
COURSE_LIFECYCLE_CONFLICT_CODE = "course_lifecycle_conflict"
COURSE_LIFECYCLE_CONFLICT_MESSAGE = (
    "Course lifecycle changed during this request. Please retry."
)


def archive_lifecycle_conflict_error() -> HTTPException:
    """Return the shared public contract for an exhausted Archive plan rebuild."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": ARCHIVE_LIFECYCLE_CONFLICT_CODE,
            "message": ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE,
        },
    )


def course_lifecycle_conflict_error() -> HTTPException:
    """Return the public contract for an exhausted Course plan rebuild."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": COURSE_LIFECYCLE_CONFLICT_CODE,
            "message": COURSE_LIFECYCLE_CONFLICT_MESSAGE,
        },
    )


def make_course_trash_lifecycle_reason(
    *,
    previous_status: SubmissionStatus,
    course_id: Optional[int],
    archive_id: Optional[int],
) -> str:
    fields: list[str] = [f"{COURSE_TRASH_PREVIOUS_STATUS_KEY}={previous_status.value}"]
    if course_id is not None:
        fields.append(f"{COURSE_TRASH_COURSE_ID_KEY}={course_id}")
    if archive_id is not None:
        fields.append(f"{COURSE_TRASH_ARCHIVE_ID_KEY}={archive_id}")
    return f"{COURSE_TRASH_LIFECYCLE_PREFIX}{'|'.join(fields)}"


def is_course_trash_lifecycle_reason(reason: Optional[str]) -> bool:
    if reason is None:
        return False
    return reason == LIFECYCLE_COURSE_TRASHED or reason.startswith(
        COURSE_TRASH_LIFECYCLE_PREFIX
    )


def get_course_trash_previous_status(
    reason: Optional[str],
) -> Optional[SubmissionStatus]:
    marker_data = _parse_course_trash_lifecycle_reason(reason)
    raw_status = marker_data.get(COURSE_TRASH_PREVIOUS_STATUS_KEY)
    if raw_status not in {
        SubmissionStatus.APPROVED.value,
        SubmissionStatus.PENDING.value,
        SubmissionStatus.TAKEDOWN.value,
        SubmissionStatus.REJECTED.value,
        SubmissionStatus.DELETED.value,
    }:
        return None
    return SubmissionStatus(raw_status)


def get_course_trash_course_id(reason: Optional[str]) -> Optional[int]:
    raw_course_id = _parse_course_trash_lifecycle_reason(reason).get(
        COURSE_TRASH_COURSE_ID_KEY
    )
    if raw_course_id is None:
        return None
    try:
        return int(raw_course_id)
    except (TypeError, ValueError):
        return None


def _parse_course_trash_lifecycle_reason(reason: Optional[str]) -> dict[str, str]:
    if reason is None:
        return {}
    marker_fields = reason.split("|")
    if not marker_fields:
        return {}
    if marker_fields[0] != LIFECYCLE_COURSE_TRASHED:
        return {}

    marker_data = {}
    for item in marker_fields[1:]:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        marker_data[key] = value
    return marker_data


@dataclass
class ArchiveSubmissionGroup:
    archives: list[Archive] = field(default_factory=list)
    submissions: list[ArchiveSubmission] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_archive_submission_trashed(submission: ArchiveSubmission) -> bool:
    return (
        submission.deleted_at is not None
        or submission.status == SubmissionStatus.DELETED
    )


async def acquire_stable_submission_lifecycle_locks(
    db: SQLModelAsyncSession,
    *,
    submission_id: int,
    operation: ArchiveSubmissionLinkOperation,
) -> LockedLifecycleRows | None:
    """Acquire one stable exact Submission plan with one transparent rebuild."""

    budget = PlanRebuildBudget()
    while True:
        (
            locked,
            revalidation,
        ) = await archive_lifecycle_locks.acquire_exact_submission_lifecycle_locks(
            db,
            submission_id=submission_id,
            operation=operation,
        )
        if locked is None:
            return None
        if revalidation is not None and revalidation.valid:
            return locked

        await db.rollback()
        budget = budget.consume()


async def delete_archive_submission_events(
    db: SQLModelAsyncSession,
    submission_ids: set[int],
) -> int:
    """Remove immutable ledger rows when their submissions are permanently deleted."""
    if not submission_ids:
        return 0

    result = await db.execute(
        delete(ArchiveSubmissionEvent).where(
            ArchiveSubmissionEvent.submission_id.in_(submission_ids)
        )
    )
    return int(result.rowcount or 0)


async def _resolve_linked_archive(
    db: SQLModelAsyncSession,
    *,
    submission: ArchiveSubmission,
) -> tuple[Optional[Archive], list[str]]:
    if submission.created_archive_id:
        linked_archive = await db.get(Archive, submission.created_archive_id)
        if linked_archive:
            return linked_archive, []
        return None, [f"關聯考古題 #{submission.created_archive_id} 已不存在"]

    if not submission.object_name:
        return None, []

    fallback_conditions = [
        Archive.object_name == submission.object_name,
        Archive.name == submission.name,
        Archive.academic_year == submission.academic_year,
        Archive.archive_type == submission.archive_type,
    ]
    if submission.professor:
        fallback_conditions.append(Archive.professor == submission.professor)

    fallback_archive = (
        (
            await db.execute(
                select(Archive)
                .where(and_(*fallback_conditions))
                .order_by(Archive.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    return (fallback_archive, []) if fallback_archive else (None, [])


async def collect_archive_submission_group(
    db: SQLModelAsyncSession,
    *,
    archive: Optional[Archive] = None,
    submission: Optional[ArchiveSubmission] = None,
    exact_link_only: bool = False,
) -> ArchiveSubmissionGroup:
    group = ArchiveSubmissionGroup()
    archive_ids: set[int] = set()
    submission_ids: set[int] = set()

    def add_archive(item: Optional[Archive]) -> None:
        if item and item.id is not None and item.id not in archive_ids:
            archive_ids.add(item.id)
            group.archives.append(item)

    def add_submission(item: Optional[ArchiveSubmission]) -> None:
        if item and item.id is not None and item.id not in submission_ids:
            submission_ids.add(item.id)
            group.submissions.append(item)

    add_archive(archive)
    add_submission(submission)

    linked_archive = archive
    if submission:
        if exact_link_only and submission.created_archive_id is None:
            linked_archive, link_warnings = None, []
        else:
            linked_archive, link_warnings = await _resolve_linked_archive(
                db,
                submission=submission,
            )
        group.warnings.extend(link_warnings)
        if linked_archive:
            add_archive(linked_archive)

    for item in list(group.archives):
        siblings = (
            (
                await db.execute(
                    select(ArchiveSubmission).where(
                        ArchiveSubmission.created_archive_id == item.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for sibling in siblings:
            add_submission(sibling)

    if linked_archive and not archive:
        add_archive(linked_archive)

    return group


def _soft_delete_archive(
    archive: Archive, *, now: datetime, user_id: Optional[int], reason: str
) -> bool:
    if archive.deleted_at is not None:
        return False
    archive.deleted_at = now
    archive.deleted_by_id = user_id
    archive.deleted_reason = reason
    archive.restored_at = None
    archive.restored_by_id = None
    return True


def _soft_delete_submission(
    submission: ArchiveSubmission,
    *,
    now: datetime,
    user_id: Optional[int],
    reason: str,
    consume_owner_self_delete: bool = False,
) -> bool:
    if is_archive_submission_trashed(submission):
        return False
    previous_status = resolve_archive_submission_delete_source_status(
        submission.status,
        operation="soft_delete",
    )
    submission.previous_status = previous_status
    if consume_owner_self_delete:
        submission.owner_self_delete_consumed = True
    submission.status = SubmissionStatus.DELETED
    submission.deleted_at = now
    submission.deleted_by_id = user_id
    submission.delete_reason = reason
    submission.lifecycle_reason = None
    submission.restored_at = None
    submission.restored_by_id = None
    return True


def _temporarily_takedown_submission(
    submission: ArchiveSubmission,
    *,
    reason: str,
    reviewer_id: Optional[int],
    now: datetime,
) -> bool:
    if is_archive_submission_trashed(submission):
        return False
    if submission.status == SubmissionStatus.TAKEDOWN:
        return False
    submission.status = SubmissionStatus.TAKEDOWN
    submission.lifecycle_reason = reason
    submission.reviewer_id = reviewer_id
    submission.reviewed_at = now
    return True


async def soft_delete_archive_with_submission_takedown(
    db: SQLModelAsyncSession,
    *,
    archive: Archive,
    submissions: Sequence[ArchiveSubmission],
    user_id: Optional[int],
    reason: str,
    now: Optional[datetime] = None,
) -> dict:
    timestamp = now or datetime.now(timezone.utc)
    archive_count = (
        1
        if _soft_delete_archive(archive, now=timestamp, user_id=user_id, reason=reason)
        else 0
    )
    submission_count = sum(
        1
        for item in submissions
        if item.deleted_at is None
        and item.status != SubmissionStatus.DELETED
        and _temporarily_takedown_submission(
            item,
            reason=LIFECYCLE_ARCHIVE_TRASHED,
            reviewer_id=user_id,
            now=timestamp,
        )
    )
    return {
        "archives": archive_count,
        "submissions_takedown": submission_count,
        "warnings": [],
    }


async def soft_delete_submission_with_linked_archive(
    db: SQLModelAsyncSession,
    *,
    submission: ArchiveSubmission,
    user_id: Optional[int],
    reason: str,
    now: Optional[datetime] = None,
    linked_archive: Optional[Archive] = None,
    exact_link_only: bool = False,
    consume_owner_self_delete: bool = False,
) -> dict:
    warnings: list[str] = []
    if exact_link_only:
        if submission.created_archive_id is not None and linked_archive is None:
            warnings.append(f"關聯考古題 #{submission.created_archive_id} 已不存在")
    else:
        linked_archive, link_warnings = await _resolve_linked_archive(
            db,
            submission=submission,
        )
        warnings.extend(link_warnings)

    timestamp = now or datetime.now(timezone.utc)
    submission_count = (
        1
        if _soft_delete_submission(
            submission,
            now=timestamp,
            user_id=user_id,
            reason=reason,
            consume_owner_self_delete=consume_owner_self_delete,
        )
        else 0
    )
    archive_count = 0
    if linked_archive:
        archive_count = (
            1
            if _soft_delete_archive(
                linked_archive, now=timestamp, user_id=user_id, reason=reason
            )
            else 0
        )
    return {
        "archives": archive_count,
        "submissions": submission_count,
        "warnings": warnings,
    }


async def restore_archive_with_temporary_submissions(
    db: SQLModelAsyncSession,
    *,
    archive: Archive,
    submissions: Sequence[ArchiveSubmission],
    user_id: Optional[int],
    now: Optional[datetime] = None,
) -> dict:
    timestamp = now or datetime.now(timezone.utc)
    restored_archives = 0
    if archive.deleted_at is not None:
        archive.deleted_at = None
        archive.deleted_by_id = None
        archive.deleted_reason = None
        archive.restored_at = timestamp
        archive.restored_by_id = user_id
        restored_archives = 1

    restored_submissions = [
        item
        for item in submissions
        if item.status == SubmissionStatus.TAKEDOWN
        and item.lifecycle_reason == LIFECYCLE_ARCHIVE_TRASHED
    ]
    for item in restored_submissions:
        item.status = SubmissionStatus.APPROVED
        item.lifecycle_reason = None
        item.reviewer_id = user_id
        item.reviewed_at = timestamp

    return {
        "archives": restored_archives,
        "submissions_restored": len(restored_submissions),
        "warnings": [],
    }


async def mark_linked_submissions_archive_permanently_deleted(
    db: SQLModelAsyncSession,
    *,
    archive: Archive,
    user_id: Optional[int],
    now: Optional[datetime] = None,
) -> int:
    timestamp = now or datetime.now(timezone.utc)
    submissions = (
        (
            await db.execute(
                select(ArchiveSubmission).where(
                    ArchiveSubmission.created_archive_id == archive.id
                )
            )
        )
        .scalars()
        .all()
    )
    for item in submissions:
        item.status = SubmissionStatus.DELETED
        item.deleted_at = item.deleted_at or timestamp
        item.deleted_by_id = item.deleted_by_id or user_id
        item.delete_reason = "linked archive permanently deleted"
        item.lifecycle_reason = LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED
        item.created_archive_id = None
        item.restored_at = None
        item.restored_by_id = None
        item.reviewed_at = timestamp
        item.reviewer_id = user_id
    return len(submissions)


async def soft_delete_archive_submission_group(
    db: SQLModelAsyncSession,
    *,
    archive: Optional[Archive] = None,
    submission: Optional[ArchiveSubmission] = None,
    user_id: Optional[int],
    reason: str,
    now: Optional[datetime] = None,
) -> dict:
    timestamp = now or datetime.now(timezone.utc)
    group = await collect_archive_submission_group(
        db, archive=archive, submission=submission
    )
    archive_count = sum(
        1
        for item in group.archives
        if _soft_delete_archive(item, now=timestamp, user_id=user_id, reason=reason)
    )
    submission_count = sum(
        1
        for item in group.submissions
        if _soft_delete_submission(item, now=timestamp, user_id=user_id, reason=reason)
    )
    return {
        "archives": archive_count,
        "submissions": submission_count,
        "warnings": group.warnings,
    }


async def restore_archive_submission_group(
    db: SQLModelAsyncSession,
    *,
    archive: Optional[Archive] = None,
    submission: Optional[ArchiveSubmission] = None,
    user_id: Optional[int],
    now: Optional[datetime] = None,
    exact_link_only: bool = False,
) -> dict:
    timestamp = now or datetime.now(timezone.utc)
    group = await collect_archive_submission_group(
        db,
        archive=archive,
        submission=submission,
        exact_link_only=exact_link_only,
    )
    restored_archives = 0
    restored_submissions = 0

    for item in group.archives:
        if item.deleted_at is None:
            continue
        item.deleted_at = None
        item.deleted_by_id = None
        item.deleted_reason = None
        item.restored_at = timestamp
        item.restored_by_id = user_id
        restored_archives += 1

    for item in group.submissions:
        if not is_archive_submission_trashed(item):
            continue
        item.deleted_at = None
        item.deleted_by_id = None
        item.delete_reason = None
        item.lifecycle_reason = None
        item.restored_at = timestamp
        item.restored_by_id = user_id
        item.status = (
            SubmissionStatus.APPROVED
            if item.created_archive_id
            else SubmissionStatus.PENDING
        )
        # S3A-1 records the exact delete source as provenance. The current
        # restore behavior remains unchanged until S3A-2, but active rows must
        # consume that delete-only provenance to satisfy the existing model
        # invariant.
        item.previous_status = None
        if item.created_archive_id:
            item.reviewed_at = timestamp
            item.reviewer_id = user_id
        restored_submissions += 1

    return {
        "archives": restored_archives,
        "submissions": restored_submissions,
        "warnings": group.warnings,
    }


async def _count_rows(db: SQLModelAsyncSession, statement) -> int:
    result = await db.execute(statement)
    return int(result.scalar() or 0)


async def _remove_storage_object_if_unreferenced(
    db: SQLModelAsyncSession,
    object_name: Optional[str],
    warnings: list[str],
    *,
    exclude_archive_ids: Optional[set[int]] = None,
    exclude_submission_ids: Optional[set[int]] = None,
) -> int:
    if not object_name:
        return 0

    exclude_archive_ids = exclude_archive_ids or set()
    exclude_submission_ids = exclude_submission_ids or set()

    archive_query = select(func.count(Archive.id)).where(
        Archive.object_name == object_name
    )
    live_archive_query = archive_query.where(Archive.deleted_at.is_(None))
    if exclude_archive_ids:
        archive_query = archive_query.where(~Archive.id.in_(exclude_archive_ids))
        live_archive_query = live_archive_query.where(
            ~Archive.id.in_(exclude_archive_ids)
        )

    submission_query = select(func.count(ArchiveSubmission.id)).where(
        ArchiveSubmission.object_name == object_name
    )
    live_submission_query = submission_query.where(
        ArchiveSubmission.deleted_at.is_(None),
        ArchiveSubmission.status != SubmissionStatus.DELETED,
    )
    if exclude_submission_ids:
        submission_query = submission_query.where(
            ~ArchiveSubmission.id.in_(exclude_submission_ids)
        )
        live_submission_query = live_submission_query.where(
            ~ArchiveSubmission.id.in_(exclude_submission_ids)
        )

    live_refs = await _count_rows(db, live_archive_query) + await _count_rows(
        db, live_submission_query
    )
    all_refs = await _count_rows(db, archive_query) + await _count_rows(
        db, submission_query
    )
    if live_refs:
        warnings.append(
            f"Storage object kept because live records still reference it: {object_name}"
        )
        return 0
    if all_refs:
        warnings.append(
            f"Storage object kept because other trashed records still reference it: {object_name}"
        )
        return 0

    try:
        get_minio_client().remove_object(settings.MINIO_BUCKET_NAME, object_name)
        return 1
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            warnings.append(f"Storage object was already missing: {object_name}")
            return 0
        warnings.append(f"Storage object delete warning for {object_name}: {exc}")
        return 0
    except Exception as exc:
        warnings.append(f"Storage object delete warning for {object_name}: {exc}")
        return 0


async def hard_delete_archive_submission_group(
    db: SQLModelAsyncSession,
    *,
    archive: Optional[Archive] = None,
    submission: Optional[ArchiveSubmission] = None,
    warnings: list[str],
) -> dict:
    group = await collect_archive_submission_group(
        db, archive=archive, submission=submission
    )
    group.warnings.extend(warnings)
    timestamp = datetime.now(timezone.utc)

    for item in group.archives:
        _soft_delete_archive(
            item,
            now=timestamp,
            user_id=item.deleted_by_id,
            reason=item.deleted_reason or "group hard delete",
        )
    for item in group.submissions:
        _soft_delete_submission(
            item,
            now=timestamp,
            user_id=item.deleted_by_id,
            reason=item.delete_reason or "group hard delete",
        )

    archive_ids = {item.id for item in group.archives if item.id is not None}
    submission_ids = {item.id for item in group.submissions if item.id is not None}
    object_names = {
        item.object_name
        for item in [*group.archives, *group.submissions]
        if item.object_name
    }

    deleted_objects = 0
    for object_name in object_names:
        deleted_objects += await _remove_storage_object_if_unreferenced(
            db,
            object_name,
            group.warnings,
            exclude_archive_ids=archive_ids,
            exclude_submission_ids=submission_ids,
        )

    messages = []
    if archive_ids:
        messages = (
            (
                await db.execute(
                    select(ArchiveDiscussionMessage).where(
                        ArchiveDiscussionMessage.archive_id.in_(archive_ids)
                    )
                )
            )
            .scalars()
            .all()
        )

    for item in group.submissions:
        await db.delete(item)
    deleted_events = await delete_archive_submission_events(db, submission_ids)
    for message in messages:
        await db.delete(message)
    await db.flush()
    for item in group.archives:
        await db.delete(item)

    warnings[:] = group.warnings
    archive_count = len(group.archives)
    submission_count = len(group.submissions)
    return {
        "type": "archive_submission_group",
        "id": archive.id if archive else submission.id if submission else None,
        "name": archive.name
        if archive
        else f"{submission.subject} / {submission.name}"
        if submission
        else "archive group",
        "deletedChildren": {
            "archives": archive_count,
            "linkedSubmissionsDeleted": submission_count,
            "submissionEvents": deleted_events,
            "comments": len(messages),
            "files": deleted_objects,
        },
        "deleted": archive_count + submission_count + len(messages),
        "message": f"已永久刪除考古題與 {submission_count} 筆關聯投稿，並清除相關檔案。",
    }
