import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from minio.error import S3Error
from pydantic import BaseModel
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_ARCHIVE_TRASHED,
    LIFECYCLE_COURSE_TRASHED,
    LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED,
    acquire_stable_archive_submission_group_locks,
    acquire_stable_submission_lifecycle_locks,
    archive_lifecycle_conflict_error,
    collect_archive_submission_group,
    course_lifecycle_conflict_error,
    detach_archive_submission_events,
    get_course_trash_course_id,
    get_course_trash_previous_status,
    hard_delete_archive_submission_group,
    is_archive_submission_trashed,
    is_course_trash_lifecycle_reason,
    mark_linked_submissions_archive_permanently_deleted,
    restore_archive_submission_group,
    restore_archive_with_temporary_submissions,
)
from app.core.config import settings
from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveWishReport,
    CommentReport,
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    Notification,
    PermanentDeletionBulkItemResult,
    PermanentDeletionBulkOutcome,
    PermanentDeletionBulkRead,
    PermanentDeletionOperation,
    PermanentDeletionRead,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    SubmissionStatus,
    SystemIssueReport,
    TrashEntityType,
    TrashItem,
    User,
)
from app.services import archive_lifecycle_locks, course_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    LifecyclePlanRetryExhausted,
    PlanRebuildBudget,
)
from app.services.archive_report_lifecycle_locks import (
    acquire_stable_archive_report_locks,
)
from app.services.archive_report_uniqueness import (
    acquire_archive_report_uniqueness_mutex_for_report,
    archive_report_restore_pending_conflict_error,
    is_archive_report_pending_unique_violation,
)
from app.services.archive_submission_links import (
    ensure_archive_submission_link_available,
)
from app.services.course_lifecycle_locks import CourseLifecycleOperation
from app.services.permanent_deletion import (
    PermanentDeletionError,
    accept_permanent_deletion,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_storage import (
    ExactVersionMinioAdapter,
    StorageSafetyError,
)
from app.utils.auth import get_current_user
from app.utils.exception_logging import redacted_exc_info
from app.utils.storage import get_minio_client

router = APIRouter()
logger = logging.getLogger(__name__)

COMMENT_REPORT_REASON_LABELS = {
    "spam_or_duplicate": "垃圾訊息或重複洗版",
    "harassment_or_hostility": "攻擊、騷擾或不友善內容",
    "inappropriate_or_illegal": "不當或違法內容",
    "privacy_violation": "洩漏個人資料或隱私",
    "misinformation": "錯誤或誤導資訊",
    "other": "其他",
}
ARCHIVE_REPORT_REASON_LABELS = {
    "file_unavailable_or_corrupt": "檔案無法開啟或檔案損毀",
    "metadata_mismatch": "考古題內容與課程／考試資訊不符",
    "duplicate_archive": "重複的考古題",
    "incomplete_or_low_quality": "檔案模糊、缺頁或內容不完整",
    "personal_information": "含有不適合公開的個人資訊",
    "other": "其他問題",
}


class TrashActionRequest(BaseModel):
    item_type: TrashEntityType
    item_id: int


@dataclass(frozen=True)
class TrashActionAuthority:
    dependencies: tuple[str, ...] = ()
    can_restore: bool = True
    can_permanent_delete: bool = True


_DURABLE_DELETE_TYPES = frozenset(TrashEntityType)
_STORAGE_CAPABLE_DURABLE_DELETE_TYPES = frozenset(
    {
        TrashEntityType.ARCHIVE,
        TrashEntityType.ARCHIVE_SUBMISSION,
        TrashEntityType.COURSE,
        TrashEntityType.USER,
    }
)

_PUBLIC_PERMANENT_DELETION_ROOT_MODELS = {
    TrashEntityType.ARCHIVE: Archive,
    TrashEntityType.ARCHIVE_SUBMISSION: ArchiveSubmission,
    TrashEntityType.COURSE_CATEGORY: CourseCategoryConfig,
    TrashEntityType.COURSE: Course,
    TrashEntityType.COURSE_SUBMISSION: CourseSubmission,
    TrashEntityType.SYSTEM_ISSUE_REPORT: SystemIssueReport,
    TrashEntityType.COMMENT_REPORT: CommentReport,
    TrashEntityType.ARCHIVE_REPORT: ArchiveReport,
    TrashEntityType.ARCHIVE_WISH_REPORT: ArchiveWishReport,
    TrashEntityType.NOTIFICATION: Notification,
    TrashEntityType.USER: User,
}


def _is_trashed_permanent_deletion_root(
    item_type: TrashEntityType,
    root,
) -> bool:
    if root is None:
        return False
    if item_type == TrashEntityType.ARCHIVE_SUBMISSION:
        return is_archive_submission_trashed(root)
    if item_type == TrashEntityType.COURSE_SUBMISSION:
        return root.deleted_at is not None or root.status == SubmissionStatus.DELETED
    return root.deleted_at is not None


def _permanent_deletion_idempotency_key(
    item_type: TrashEntityType, item_id: int
) -> str:
    return f"trash-root:{item_type.value}:{item_id}"


def _to_permanent_deletion_read(
    operation: PermanentDeletionOperation, *, now: datetime | None = None
) -> PermanentDeletionRead:
    timestamp = now or datetime.now(UTC)
    operation_status = PermanentDeletionStatus(operation.status)
    can_retry = operation_status in {
        PermanentDeletionStatus.ACCEPTED,
        PermanentDeletionStatus.VERIFICATION_REQUIRED,
    } or (
        operation_status == PermanentDeletionStatus.RETRYABLE_FAILED
        and operation.next_attempt_at is not None
        and operation.next_attempt_at <= timestamp
    )
    return PermanentDeletionRead(
        operation_id=int(operation.id),
        root_type=TrashEntityType(operation.root_entity_type),
        root_id=operation.root_entity_id,
        status=operation_status,
        accepted_at=operation.accepted_at,
        completed_at=operation.completed_at,
        next_attempt_at=operation.next_attempt_at,
        result_code=operation.result_code,
        can_retry=can_retry,
        can_inspect_reason=bool(operation.result_code),
        restore_available=False,
    )


async def _permanent_deletion_for_root(
    db: SQLModelAsyncSession,
    *,
    item_type: TrashEntityType,
    item_id: int,
) -> PermanentDeletionOperation | None:
    return (
        await db.execute(
            select(PermanentDeletionOperation).where(
                PermanentDeletionOperation.idempotency_key
                == _permanent_deletion_idempotency_key(item_type, item_id)
            )
        )
    ).scalar_one_or_none()


async def _apply_permanent_deletion_projections(
    db: SQLModelAsyncSession, items: list[TrashItem]
) -> None:
    relevant = {(item.item_type.value, item.id) for item in items}
    if not relevant:
        return
    ids_by_type: dict[str, list[int]] = {}
    for entity_type, entity_id in relevant:
        ids_by_type.setdefault(entity_type, []).append(entity_id)
    root_scope = or_(
        *(
            and_(
                PermanentDeletionOperation.root_entity_type == entity_type,
                PermanentDeletionOperation.root_entity_id.in_(entity_ids),
            )
            for entity_type, entity_ids in ids_by_type.items()
        )
    )
    target_scope = or_(
        *(
            and_(
                PermanentDeletionTarget.entity_type == entity_type,
                PermanentDeletionTarget.entity_id.in_(entity_ids),
            )
            for entity_type, entity_ids in ids_by_type.items()
        )
    )
    operations = (
        (
            await db.execute(
                select(PermanentDeletionOperation).where(
                    root_scope,
                    PermanentDeletionOperation.status
                    != PermanentDeletionStatus.COMPLETED,
                )
            )
        )
        .scalars()
        .all()
    )
    by_root = {
        (operation.root_entity_type, operation.root_entity_id): operation
        for operation in operations
        if (operation.root_entity_type, operation.root_entity_id) in relevant
    }
    targets = (
        await db.execute(
            select(PermanentDeletionTarget, PermanentDeletionOperation)
            .join(
                PermanentDeletionOperation,
                PermanentDeletionOperation.id == PermanentDeletionTarget.operation_id,
            )
            .where(
                target_scope,
                PermanentDeletionTarget.reservation_released_at.is_(None),
                PermanentDeletionOperation.status != PermanentDeletionStatus.COMPLETED,
            )
        )
    ).all()
    by_target = {
        (target.entity_type, target.entity_id): operation
        for target, operation in targets
        if (target.entity_type, target.entity_id) in relevant
    }
    now = datetime.now(UTC)
    for item in items:
        identity = (item.item_type.value, item.id)
        operation = by_root.get(identity) or by_target.get(identity)
        if operation is None:
            continue
        item.permanent_deletion = _to_permanent_deletion_read(operation, now=now)
        item.canRestore = False
        item.canPermanentDelete = False


async def _reject_restore_after_acceptance(
    db: SQLModelAsyncSession,
    *,
    item_type: TrashEntityType,
    item_id: int,
) -> None:
    operation = await _proven_covering_permanent_deletion(
        db,
        item_type=item_type,
        item_id=item_id,
        operation_ids=None,
        include_released=False,
    )
    if operation is None or operation.status == PermanentDeletionStatus.COMPLETED:
        return
    await db.rollback()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "permanent_deletion_already_accepted",
            "message": "永久刪除已接受，無法還原",
        },
    )


async def _proven_covering_permanent_deletion(
    db: SQLModelAsyncSession,
    *,
    item_type: TrashEntityType,
    item_id: int,
    operation_ids: set[int] | None,
    include_released: bool,
) -> PermanentDeletionRead | None:
    statement = (
        select(PermanentDeletionOperation)
        .join(
            PermanentDeletionTarget,
            PermanentDeletionTarget.operation_id == PermanentDeletionOperation.id,
        )
        .where(
            PermanentDeletionTarget.entity_type == item_type.value,
            PermanentDeletionTarget.entity_id == item_id,
        )
        .order_by(PermanentDeletionOperation.id.desc())
    )
    if operation_ids is not None:
        if not operation_ids:
            return None
        statement = statement.where(PermanentDeletionOperation.id.in_(operation_ids))
    if not include_released:
        statement = statement.where(
            PermanentDeletionTarget.reservation_released_at.is_(None),
            PermanentDeletionOperation.status != PermanentDeletionStatus.COMPLETED,
        )
    operation = (await db.execute(statement.limit(1))).scalar_one_or_none()
    return _to_permanent_deletion_read(operation) if operation is not None else None


def _permanent_deletion_storage() -> ExactVersionMinioAdapter:
    return ExactVersionMinioAdapter(
        get_minio_client(), bucket_name=settings.MINIO_BUCKET_NAME
    )


def _permanent_deletion_storage_for_root(
    item_type: TrashEntityType,
) -> ExactVersionMinioAdapter | None:
    if item_type not in _STORAGE_CAPABLE_DURABLE_DELETE_TYPES:
        return None
    return _permanent_deletion_storage()


async def _lock_simple_trash_root(
    db: SQLModelAsyncSession,
    model,
    item_id: int,
):
    return (
        await db.execute(select(model).where(model.id == item_id).with_for_update())
    ).scalar_one_or_none()


def _build_trash_action_authority(
    dependencies: list[str],
    *,
    restore_blocked: bool = False,
    permanent_delete_blocked: bool = False,
) -> TrashActionAuthority:
    return TrashActionAuthority(
        dependencies=tuple(item for item in dependencies if item),
        can_restore=not restore_blocked,
        can_permanent_delete=not permanent_delete_blocked,
    )


def _to_trash_item(
    *,
    item_type: TrashEntityType,
    item_id: int,
    display_name: str,
    display_name_en: str | None = None,
    deleted_at,
    deleted_by_id: int | None,
    deleted_by_name: str | None = None,
    user_email: str | None = None,
    status: str | None = None,
    academic_year: int | None = None,
    academic_term: str | None = None,
    parent_type: str | None = None,
    parent_id: int | None = None,
    parent_name: str | None = None,
    parent_name_en: str | None = None,
    created_archive_id: int | None = None,
    source_submission_id: int | None = None,
    course_id: int | None = None,
    course_name: str | None = None,
    course_name_en: str | None = None,
    requested_course_name: str | None = None,
    requested_course_name_en: str | None = None,
    requested_category_name: str | None = None,
    requested_category_name_en: str | None = None,
    requested_category_label: str | None = None,
    requested_category_label_en: str | None = None,
    reason: str | None = None,
    created_at: datetime | None = None,
    reporter_name: str | None = None,
    report_type: str | None = None,
    github_issue_number: int | None = None,
    github_issue_url: str | None = None,
    comment_author_name: str | None = None,
    comment_snapshot: str | None = None,
    archive_name: str | None = None,
    dependencies: list[str] | None = None,
    can_restore: bool = True,
    can_permanent_delete: bool = True,
    action_authority: TrashActionAuthority | None = None,
) -> TrashItem:
    if action_authority is not None:
        dependencies = list(action_authority.dependencies)
        can_restore = action_authority.can_restore
        can_permanent_delete = action_authority.can_permanent_delete
    return TrashItem(
        item_type=item_type,
        id=item_id,
        display_name=display_name,
        display_name_en=display_name_en,
        academic_year=academic_year,
        academic_term=academic_term,
        deleted_at=deleted_at,
        deleted_by_id=deleted_by_id,
        deleted_by_name=deleted_by_name,
        user_email=user_email,
        status=status,
        parent_type=parent_type,
        parent_id=parent_id,
        parent_name=parent_name,
        parent_name_en=parent_name_en,
        created_archive_id=created_archive_id,
        source_submission_id=source_submission_id,
        course_id=course_id,
        course_name=course_name,
        course_name_en=course_name_en,
        requested_course_name=requested_course_name,
        requested_course_name_en=requested_course_name_en,
        requested_category_name=requested_category_name,
        requested_category_name_en=requested_category_name_en,
        requested_category_label=requested_category_label,
        requested_category_label_en=requested_category_label_en,
        reason=reason,
        created_at=created_at,
        reporter_name=reporter_name,
        report_type=report_type,
        github_issue_number=github_issue_number,
        github_issue_url=github_issue_url,
        comment_author_name=comment_author_name,
        comment_snapshot=comment_snapshot,
        archive_name=archive_name,
        canRestore=can_restore,
        canPermanentDelete=can_permanent_delete,
        dependencies=_build_dependencies(dependencies or []),
    )


def _build_dependencies(messages: list[str]) -> list[str]:
    return [item for item in messages if item]


def _dedupe_trash_items(items: list[TrashItem]) -> list[TrashItem]:
    deduped: dict[tuple[TrashEntityType, int], TrashItem] = {}
    passthrough: list[TrashItem] = []
    for item in items:
        if item.id is None:
            passthrough.append(item)
            continue
        key = (item.item_type, item.id)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
            continue
        existing_dependencies = list(existing.dependencies or [])
        for dependency in item.dependencies or []:
            if dependency not in existing_dependencies:
                existing_dependencies.append(dependency)
        existing.dependencies = existing_dependencies
        if item.deleted_at and item.deleted_at > existing.deleted_at:
            existing.deleted_at = item.deleted_at
            existing.deleted_by_id = item.deleted_by_id
            existing.deleted_by_name = item.deleted_by_name
    return [*deduped.values(), *passthrough]


def _format_academic_term(value: int | None) -> str | None:
    if not value:
        return None
    year = value // 10
    semester = value % 10
    if year > 0 and semester in (1, 2):
        return f"{year}{'上' if semester == 1 else '下'}學期"
    return f"{value} 年"


def _format_deleted_by(users_by_id: dict[int, User], user_id: int | None) -> str | None:
    if not user_id:
        return None
    user = users_by_id.get(user_id)
    if not user:
        return f"已刪除使用者 #{user_id}"
    return user.nickname or user.name or user.email or f"使用者 #{user_id}"


def _dependency_count(count: int, unit: str, singular_unit: str | None = None) -> str:
    if count == 1 and singular_unit:
        return f"1 {singular_unit}"
    return f"{count} {unit}"


def _is_course_trash_temporary_submission(submission: ArchiveSubmission) -> bool:
    return (
        submission.deleted_at is None
        and submission.status == SubmissionStatus.TAKEDOWN
        and is_course_trash_lifecycle_reason(submission.lifecycle_reason)
    )


def _format_submission_status_label(status_value: SubmissionStatus | None) -> str:
    return {
        SubmissionStatus.PENDING: "待審核",
        SubmissionStatus.APPROVED: "已通過",
        SubmissionStatus.REJECTED: "未通過",
        SubmissionStatus.TAKEDOWN: "已下架",
        SubmissionStatus.DELETED: "已刪除",
    }.get(status_value, "—")


async def _count_rows(db: SQLModelAsyncSession, statement) -> int:
    result = await db.execute(statement)
    return int(result.scalar() or 0)


async def _get_category_action_authority(
    db: SQLModelAsyncSession,
    category: CourseCategoryConfig,
) -> TrashActionAuthority:
    active_courses = await _count_rows(
        db,
        select(func.count(Course.id)).where(
            Course.category == category.key,
            Course.deleted_at.is_(None),
        ),
    )
    trashed_courses = await _count_rows(
        db,
        select(func.count(Course.id)).where(
            Course.category == category.key,
            Course.deleted_at.is_not(None),
        ),
    )
    course_submissions = await _count_rows(
        db,
        select(func.count(CourseSubmission.id)).where(
            CourseSubmission.category == category.key,
            CourseSubmission.status == SubmissionStatus.PENDING,
            CourseSubmission.deleted_at.is_(None),
        ),
    )
    active_archive_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            or_(
                ArchiveSubmission.category == category.key,
                ArchiveSubmission.requested_category_key == category.key,
            ),
            ArchiveSubmission.status != SubmissionStatus.DELETED,
            ArchiveSubmission.deleted_at.is_(None),
        ),
    )
    course_count = active_courses + trashed_courses
    return _build_trash_action_authority(
        [
            f"阻擋永久刪除：{_dependency_count(course_count, '門')}課程仍屬於此分類，請先永久刪除課程"
            if course_count
            else "",
            f"阻擋永久刪除：{_dependency_count(course_submissions, '筆')}啟用中課程投稿仍屬於此分類"
            if course_submissions
            else "",
            f"阻擋永久刪除：{_dependency_count(active_archive_submissions, '筆')}啟用中投稿仍屬於此分類"
            if active_archive_submissions
            else "",
        ],
        permanent_delete_blocked=bool(
            course_count or course_submissions or active_archive_submissions
        ),
    )


async def _get_course_action_authority(
    db: SQLModelAsyncSession,
    course: Course,
) -> TrashActionAuthority:
    category_is_trashed = await _count_rows(
        db,
        select(func.count(CourseCategoryConfig.id)).where(
            CourseCategoryConfig.key == course.category,
            CourseCategoryConfig.deleted_at.is_not(None),
        ),
    )

    active_archives = await _count_rows(
        db,
        select(func.count(Archive.id)).where(
            Archive.course_id == course.id,
            Archive.deleted_at.is_(None),
        ),
    )
    trashed_archives = await _count_rows(
        db,
        select(func.count(Archive.id)).where(
            Archive.course_id == course.id,
            Archive.deleted_at.is_not(None),
        ),
    )

    restore_blockers = [
        "阻擋還原：原分類仍在垃圾桶" if category_is_trashed else "",
    ]

    return _build_trash_action_authority(
        [
            *restore_blockers,
            f"阻擋永久刪除：{_dependency_count(active_archives, '筆')}啟用中考古題仍屬於此課程"
            if active_archives
            else "",
            f"一併永久刪除：{_dependency_count(trashed_archives, '筆')}已刪除考古題屬於此課程"
            if trashed_archives
            else "",
        ],
        restore_blocked=bool(category_is_trashed),
        permanent_delete_blocked=bool(active_archives),
    )


async def _get_archive_action_authority(
    db: SQLModelAsyncSession,
    archive: Archive,
    source_submission: ArchiveSubmission | None = None,
    restore_parent_submission: ArchiveSubmission | None = None,
) -> TrashActionAuthority:
    course_is_trashed = await _count_rows(
        db,
        select(func.count(Course.id)).where(
            Course.id == archive.course_id,
            Course.deleted_at.is_not(None),
        ),
    )
    restore_blockers = [
        "阻擋還原：原課程仍在垃圾桶" if course_is_trashed else "",
    ]

    is_course_trash_reason = or_(
        ArchiveSubmission.lifecycle_reason == LIFECYCLE_COURSE_TRASHED,
        ArchiveSubmission.lifecycle_reason.like(f"{LIFECYCLE_COURSE_TRASHED}|%"),
    )
    linked_comments = await _count_rows(
        db,
        select(func.count(ArchiveDiscussionMessage.id)).where(
            ArchiveDiscussionMessage.archive_id == archive.id,
            ArchiveDiscussionMessage.deleted_at.is_(None),
        ),
    )
    active_linked_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            ArchiveSubmission.created_archive_id == archive.id,
            ArchiveSubmission.deleted_at.is_(None),
            ArchiveSubmission.status != SubmissionStatus.DELETED,
            or_(
                ArchiveSubmission.status != SubmissionStatus.TAKEDOWN,
                ~or_(
                    ArchiveSubmission.lifecycle_reason.in_([LIFECYCLE_ARCHIVE_TRASHED]),
                    is_course_trash_reason,
                ),
                ArchiveSubmission.lifecycle_reason.is_(None),
            ),
        ),
    )
    temporarily_takedown_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            ArchiveSubmission.created_archive_id == archive.id,
            ArchiveSubmission.deleted_at.is_(None),
            ArchiveSubmission.status == SubmissionStatus.TAKEDOWN,
            or_(
                ArchiveSubmission.lifecycle_reason.in_([LIFECYCLE_ARCHIVE_TRASHED]),
                is_course_trash_reason,
            ),
        ),
    )
    temp_submission_ids = [
        item
        for item in (
            await db.execute(
                select(ArchiveSubmission.id).where(
                    ArchiveSubmission.created_archive_id == archive.id,
                    ArchiveSubmission.deleted_at.is_(None),
                    ArchiveSubmission.status == SubmissionStatus.TAKEDOWN,
                    or_(
                        ArchiveSubmission.lifecycle_reason.in_(
                            [LIFECYCLE_ARCHIVE_TRASHED]
                        ),
                        is_course_trash_reason,
                    ),
                )
            )
        )
        .scalars()
        .all()
        if item is not None
    ]

    return _build_trash_action_authority(
        [
            (
                "阻擋還原：請先還原原課程"
                if restore_parent_submission
                and _is_course_trash_temporary_submission(restore_parent_submission)
                else "阻擋還原：請先還原上層投稿"
                if restore_parent_submission
                else ""
            ),
            *restore_blockers,
            f"一併永久刪除：{_dependency_count(linked_comments, '則')}留言將在考古題永久刪除時一併刪除"
            if linked_comments
            else "",
            f"阻擋永久刪除：{_dependency_count(active_linked_submissions, '筆')}啟用中投稿仍連到此考古題"
            if active_linked_submissions
            else "",
            f"關聯投稿：投稿編號 #{source_submission.id}"
            if source_submission and source_submission.id
            else "",
            (
                f"關聯投稿：投稿編號 #{temp_submission_ids[0]} 已暫時下架"
                if len(temp_submission_ids) == 1
                else f"關聯投稿：{_dependency_count(temporarily_takedown_submissions, '筆')}投稿已暫時下架"
                if temporarily_takedown_submissions
                else ""
            ),
        ],
        restore_blocked=bool(restore_parent_submission or course_is_trashed),
        permanent_delete_blocked=bool(active_linked_submissions),
    )


async def _get_user_action_authority(
    db: SQLModelAsyncSession,
    user: User,
) -> TrashActionAuthority:
    active_archives = await _count_rows(
        db,
        select(func.count(Archive.id)).where(
            Archive.uploader_id == user.id,
            Archive.deleted_at.is_(None),
        ),
    )
    trashed_archives = await _count_rows(
        db,
        select(func.count(Archive.id)).where(
            Archive.uploader_id == user.id,
            Archive.deleted_at.is_not(None),
        ),
    )
    active_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            or_(
                ArchiveSubmission.owner_id == user.id,
                ArchiveSubmission.requester_id == user.id,
            ),
            ArchiveSubmission.status != SubmissionStatus.DELETED,
            ArchiveSubmission.deleted_at.is_(None),
        ),
    )
    trashed_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            or_(
                ArchiveSubmission.owner_id == user.id,
                ArchiveSubmission.requester_id == user.id,
            ),
            or_(
                ArchiveSubmission.deleted_at.is_not(None),
                ArchiveSubmission.status == SubmissionStatus.DELETED,
            ),
        ),
    )

    return _build_trash_action_authority(
        [
            f"阻擋永久刪除：{_dependency_count(active_archives, '筆')}啟用中考古題仍屬於此使用者"
            if active_archives
            else "",
            f"一併永久刪除：{_dependency_count(trashed_archives, '筆')}已刪除考古題屬於此使用者"
            if trashed_archives
            else "",
            f"阻擋永久刪除：{_dependency_count(active_submissions, '筆')}啟用中投稿仍屬於此使用者"
            if active_submissions
            else "",
            f"一併永久刪除：{_dependency_count(trashed_submissions, '筆')}已刪除投稿屬於此使用者"
            if trashed_submissions
            else "",
        ],
        permanent_delete_blocked=bool(active_archives or active_submissions),
    )


async def _resolve_submission_linked_archive(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
) -> tuple[Archive | None, list[str]]:
    if submission.created_archive_id:
        linked_archive = await db.get(Archive, submission.created_archive_id)
        if linked_archive:
            return linked_archive, []
        return None, [f"關聯考古題 #{submission.created_archive_id} 已不存在"]

    if not submission.object_name:
        return None, []

    fallback_query = (
        select(Archive)
        .where(
            Archive.object_name == submission.object_name,
            Archive.name == submission.name,
            Archive.academic_year == submission.academic_year,
            Archive.archive_type == submission.archive_type,
        )
        .order_by(Archive.created_at.desc())
    )
    if submission.professor:
        fallback_query = fallback_query.where(Archive.professor == submission.professor)
    linked_archive = (await db.execute(fallback_query)).scalars().first()
    return (linked_archive, []) if linked_archive else (None, [])


async def _get_submission_action_authority(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
) -> TrashActionAuthority:
    if submission.lifecycle_reason == LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED:
        return _build_trash_action_authority(
            ["阻擋還原：關聯考古題已永久刪除"],
            restore_blocked=True,
        )

    if _is_course_trash_temporary_submission(submission):
        previous_status = get_course_trash_previous_status(submission.lifecycle_reason)
        return _build_trash_action_authority(
            [
                "阻擋還原：請先還原原課程",
                f"隨課程復原：課程復原後回到{_format_submission_status_label(previous_status)}",
            ],
            restore_blocked=True,
            permanent_delete_blocked=True,
        )

    linked_archive, fallback_warnings = await _resolve_submission_linked_archive(
        db, submission
    )
    if fallback_warnings or not linked_archive:
        return _build_trash_action_authority(fallback_warnings)

    linked_course = (
        await db.get(Course, linked_archive.course_id)
        if linked_archive.course_id is not None
        else None
    )
    linked_course_blocker = (
        "阻擋還原：原課程仍在垃圾桶"
        if linked_course is not None and linked_course.deleted_at is not None
        else ""
    )

    if linked_archive.deleted_at is not None:
        return _build_trash_action_authority(
            [
                linked_course_blocker,
                "一併永久刪除：1 筆關聯考古題",
            ],
            restore_blocked=bool(linked_course_blocker),
        )

    linked_comments = await _count_rows(
        db,
        select(func.count(ArchiveDiscussionMessage.id)).where(
            ArchiveDiscussionMessage.archive_id == linked_archive.id,
            ArchiveDiscussionMessage.deleted_at.is_(None),
        ),
    )
    trashed_comments = await _count_rows(
        db,
        select(func.count(ArchiveDiscussionMessage.id)).where(
            ArchiveDiscussionMessage.archive_id == linked_archive.id,
            ArchiveDiscussionMessage.deleted_at.is_not(None),
        ),
    )
    linked_other_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            ArchiveSubmission.created_archive_id == linked_archive.id,
            ArchiveSubmission.id != submission.id,
            ArchiveSubmission.deleted_at.is_(None),
            ArchiveSubmission.status != SubmissionStatus.DELETED,
        ),
    )
    trashed_submissions = await _count_rows(
        db,
        select(func.count(ArchiveSubmission.id)).where(
            ArchiveSubmission.created_archive_id == linked_archive.id,
            ArchiveSubmission.id != submission.id,
            or_(
                ArchiveSubmission.deleted_at.is_not(None),
                ArchiveSubmission.status == SubmissionStatus.DELETED,
            ),
        ),
    )
    archive_status = [f"關聯考古題：{linked_archive.name}"]
    if linked_archive.deleted_at is None:
        archive_status.append("關聯考古題仍啟用中")

    return _build_trash_action_authority(
        [
            *archive_status,
            f"一併永久刪除：{_dependency_count(linked_comments, '則')}留言將在關聯考古題永久刪除時一併刪除"
            if linked_comments
            else "",
            f"一併永久刪除：{_dependency_count(trashed_comments, '則')}已刪除留言將一併刪除"
            if trashed_comments
            else "",
            f"阻擋永久刪除：{_dependency_count(linked_other_submissions, '筆')}啟用中投稿仍連到關聯考古題"
            if linked_other_submissions
            else "",
            f"一併永久刪除：{_dependency_count(trashed_submissions, '筆')}已刪除投稿連到關聯考古題"
            if trashed_submissions
            else "",
        ],
        restore_blocked=bool(linked_course_blocker),
        permanent_delete_blocked=bool(linked_other_submissions),
    )


def _build_trash_error(item_label: str, dependencies: list[str]) -> str:
    if not dependencies:
        return item_label
    if len(dependencies) == 1:
        return f"{item_label}: {dependencies[0]}"
    return f"{item_label}; blockers: {', '.join(dependencies)}"


def _is_submission_trashed(submission: ArchiveSubmission) -> bool:
    return is_archive_submission_trashed(submission)


def _blocker(
    item_type: str, item_id: int | None, name: str, status_value: str = "active"
) -> dict:
    return {
        "type": item_type,
        "id": item_id,
        "name": name,
        "status": status_value,
    }


def _blocker_with_reason(
    item_type: str,
    item_id: int | None,
    name: str,
    status_value: str = "active",
    *,
    reason: str | None = None,
) -> dict:
    blocker = _blocker(item_type, item_id, name, status_value)
    if reason:
        blocker["reason"] = reason
    return blocker


def _is_created_archive_id_nullable() -> bool:
    try:
        column = ArchiveSubmission.__table__.c.get("created_archive_id")
        if column is None:
            return True
        return bool(column.nullable)
    except Exception as exc:
        logger.warning(
            "Unable to inspect archive-link nullability; using conservative fallback",
            exc_info=redacted_exc_info(exc),
        )
        return True


def _blocked(message: str, blockers: list[dict]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "success": False,
            "deleted": 0,
            "failed": 1,
            "message": message,
            "blockingDependencies": blockers,
            "warnings": [],
        },
    )


def _delete_result(
    *,
    item_type: TrashEntityType,
    item_id: int,
    name: str,
    deleted: int,
    details: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "success": True,
        "deleted": deleted,
        "deleted_count": deleted,
        "failed": 0,
        "failed_count": 0,
        "skipped": 0,
        "message": details[0].get("message")
        if details and details[0].get("message")
        else "永久刪除完成",
        "details": details
        or [
            {
                "type": item_type.value,
                "id": item_id,
                "name": name,
            }
        ],
        "warnings": warnings or [],
    }


async def _get_active_course_blockers(
    db: SQLModelAsyncSession, category: CourseCategoryConfig
) -> list[dict]:
    courses = (
        (
            await db.execute(
                select(Course).where(
                    Course.category == category.key,
                    Course.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [_blocker("course", course.id, course.name) for course in courses]


async def _get_active_archive_blockers(
    db: SQLModelAsyncSession, course: Course
) -> list[dict]:
    archives = (
        (
            await db.execute(
                select(Archive).where(
                    Archive.course_id == course.id,
                    Archive.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [_blocker("archive", archive.id, archive.name) for archive in archives]


async def _get_active_category_submission_blockers(
    db: SQLModelAsyncSession,
    category: CourseCategoryConfig,
) -> list[dict]:
    course_submissions = (
        (
            await db.execute(
                select(CourseSubmission).where(
                    CourseSubmission.category == category.key,
                    CourseSubmission.status == SubmissionStatus.PENDING,
                    CourseSubmission.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    archive_submissions = (
        (
            await db.execute(
                select(ArchiveSubmission).where(
                    or_(
                        ArchiveSubmission.category == category.key,
                        ArchiveSubmission.requested_category_key == category.key,
                    ),
                    ArchiveSubmission.status != SubmissionStatus.DELETED,
                    ArchiveSubmission.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        *[
            _blocker("course_submission", item.id, item.name, item.status.value)
            for item in course_submissions
        ],
        *[
            _blocker(
                "archive_submission",
                item.id,
                f"{item.subject} / {item.name}",
                item.status.value,
            )
            for item in archive_submissions
        ],
    ]


async def _get_active_user_blockers(db: SQLModelAsyncSession, user: User) -> list[dict]:
    archives = (
        (
            await db.execute(
                select(Archive).where(
                    Archive.uploader_id == user.id,
                    Archive.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    submissions = (
        (
            await db.execute(
                select(ArchiveSubmission).where(
                    or_(
                        ArchiveSubmission.owner_id == user.id,
                        ArchiveSubmission.requester_id == user.id,
                    ),
                    ArchiveSubmission.status != SubmissionStatus.DELETED,
                    ArchiveSubmission.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        *[_blocker("archive", item.id, item.name) for item in archives],
        *[
            _blocker(
                "archive_submission",
                item.id,
                f"{item.subject} / {item.name}",
                item.status.value,
            )
            for item in submissions
        ],
    ]


async def _remove_storage_object_if_unreferenced(
    db: SQLModelAsyncSession,
    object_name: str | None,
    warnings: list[str],
    *,
    exclude_archive_id: int | None = None,
    exclude_submission_ids: list[int] | None = None,
) -> int:
    if not object_name:
        return 0

    archive_query = select(func.count(Archive.id)).where(
        Archive.object_name == object_name
    )
    if exclude_archive_id is not None:
        archive_query = archive_query.where(Archive.id != exclude_archive_id)

    submission_query = select(func.count(ArchiveSubmission.id)).where(
        ArchiveSubmission.object_name == object_name
    )
    if exclude_submission_ids:
        submission_query = submission_query.where(
            ~ArchiveSubmission.id.in_(exclude_submission_ids)
        )

    # Count references only used for message context.
    live_archive_query = select(func.count(Archive.id)).where(
        Archive.object_name == object_name,
        Archive.deleted_at.is_(None),
    )
    if exclude_archive_id is not None:
        live_archive_query = live_archive_query.where(Archive.id != exclude_archive_id)

    live_submission_query = select(func.count(ArchiveSubmission.id)).where(
        ArchiveSubmission.object_name == object_name,
        ArchiveSubmission.deleted_at.is_(None),
        ArchiveSubmission.status != SubmissionStatus.DELETED,
    )
    if exclude_submission_ids:
        live_submission_query = live_submission_query.where(
            ~ArchiveSubmission.id.in_(exclude_submission_ids)
        )
    live_refs = await _count_rows(db, live_archive_query) + await _count_rows(
        db, live_submission_query
    )
    all_refs = await _count_rows(db, archive_query) + await _count_rows(
        db, submission_query
    )
    trashed_refs = all_refs - live_refs

    if live_refs:
        warnings.append(
            f"Storage object kept because live records still reference it: {object_name}"
        )
        return 0
    if trashed_refs:
        warnings.append(
            f"Storage object kept because trashed records still reference it: {object_name}"
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
        logger.warning(
            "Unexpected storage deletion failure; preserving best-effort cleanup",
            exc_info=redacted_exc_info(exc),
        )
        warnings.append(f"Storage object delete warning for {object_name}: {exc}")
        return 0


async def _hard_delete_archive(
    db: SQLModelAsyncSession,
    archive: Archive,
    warnings: list[str],
) -> dict:
    if archive.deleted_at is None:
        raise _blocked(
            "仍有未刪除的考古題依附於此項目",
            [_blocker("archive", archive.id, archive.name)],
        )

    marked_submissions = await mark_linked_submissions_archive_permanently_deleted(
        db,
        archive=archive,
        user_id=archive.deleted_by_id,
    )
    object_deleted = await _remove_storage_object_if_unreferenced(
        db,
        archive.object_name,
        warnings,
        exclude_archive_id=archive.id,
    )
    messages = (
        (
            await db.execute(
                select(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
        )
        .scalars()
        .all()
    )
    for message in messages:
        await db.delete(message)
    await db.flush()
    await db.delete(archive)
    return {
        "deleted": 1,
        "archives": 1,
        "messages": len(messages),
        "submissions_marked_deleted": marked_submissions,
        "objects": object_deleted,
        "warnings": warnings,
    }


async def _hard_delete_submission(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
    warnings: list[str],
) -> dict:
    if not _is_submission_trashed(submission):
        raise _blocked(
            "仍有未刪除的投稿資料依附於此項目",
            [
                _blocker(
                    "archive_submission",
                    submission.id,
                    f"{submission.subject} / {submission.name}",
                    submission.status.value,
                )
            ],
        )
    linked_archive = (
        await db.get(Archive, submission.created_archive_id)
        if submission.created_archive_id
        else None
    )
    if linked_archive and linked_archive.deleted_at is not None:
        return await _hard_delete_submission_archive_pair(
            db, submission, linked_archive, warnings
        )
    return await hard_delete_archive_submission_group(
        db, submission=submission, warnings=warnings
    )


async def _get_deleted_submission_parent_for_archive(
    db: SQLModelAsyncSession,
    archive_id: int | None,
) -> ArchiveSubmission | None:
    if archive_id is None:
        return None
    return (
        (
            await db.execute(
                select(ArchiveSubmission)
                .where(
                    ArchiveSubmission.created_archive_id == archive_id,
                    or_(
                        ArchiveSubmission.deleted_at.is_not(None),
                        ArchiveSubmission.status == SubmissionStatus.DELETED,
                    ),
                )
                .order_by(
                    ArchiveSubmission.deleted_at.desc(),
                    ArchiveSubmission.reviewed_at.desc(),
                    ArchiveSubmission.created_at.desc(),
                )
            )
        )
        .scalars()
        .first()
    )


async def _hard_delete_submission_archive_pair(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
    archive: Archive,
    warnings: list[str],
) -> dict:
    group = await acquire_stable_archive_submission_group_locks(
        db, archive=archive, submission=submission
    )
    warnings.extend(group.warnings)
    archive = next(item for item in group.archives if item.id == archive.id)
    submission = next(item for item in group.submissions if item.id == submission.id)
    timestamp = datetime.now(UTC)
    linked_submissions = (
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
    submissions_to_delete: list[ArchiveSubmission] = []
    marked_unrecoverable = 0
    for item in linked_submissions:
        if is_archive_submission_trashed(item):
            submissions_to_delete.append(item)
            continue
        item.status = SubmissionStatus.DELETED
        item.deleted_at = timestamp
        item.deleted_by_id = item.deleted_by_id or archive.deleted_by_id
        item.delete_reason = "linked archive permanently deleted"
        item.lifecycle_reason = LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED
        item.created_archive_id = None
        item.restored_at = None
        item.restored_by_id = None
        marked_unrecoverable += 1
    if submission not in submissions_to_delete:
        submissions_to_delete.append(submission)

    submission_ids = [item.id for item in submissions_to_delete if item.id is not None]
    object_names = {
        item for item in [submission.object_name, archive.object_name] if item
    }
    deleted_objects = 0
    for object_name in object_names:
        deleted_objects += await _remove_storage_object_if_unreferenced(
            db,
            object_name,
            warnings,
            exclude_archive_id=archive.id,
            exclude_submission_ids=submission_ids,
        )

    messages = (
        (
            await db.execute(
                select(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
        )
        .scalars()
        .all()
    )
    for message in messages:
        await db.delete(message)
    for item in submissions_to_delete:
        item.created_archive_id = None
        await db.delete(item)
    retained_events = await detach_archive_submission_events(db, set(submission_ids))
    await db.flush()
    await db.delete(archive)
    return {
        "type": "archive_submission_group",
        "id": submission.id,
        "name": f"{submission.subject} / {submission.name}",
        "deletedChildren": {
            "archives": 1,
            "linkedSubmissionsDeleted": len(submissions_to_delete),
            "linkedSubmissionsMarkedDeleted": marked_unrecoverable,
            "submissionEventsRetained": retained_events,
            "comments": len(messages),
            "files": deleted_objects,
        },
        "deleted": 1 + len(submissions_to_delete) + len(messages),
        "message": "已永久刪除考古題投稿與關聯考古題，並清除相關檔案。",
    }


async def _hard_delete_course(
    db: SQLModelAsyncSession,
    course: Course,
    warnings: list[str],
) -> dict:
    blockers = await _get_active_archive_blockers(db, course)
    if blockers:
        raise _blocked("仍有未刪除的考古題依附於此課程", blockers)

    trashed_archives = (
        (
            await db.execute(
                select(Archive).where(
                    Archive.course_id == course.id,
                    Archive.deleted_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    details = []
    deleted_count = 1
    for archive in trashed_archives:
        detail = await _hard_delete_archive(db, archive, warnings)
        details.append(detail)
        deleted_count += detail.get("deleted", 0)

    await db.delete(course)
    return {
        "type": "course",
        "id": course.id,
        "name": course.name,
        "deletedChildren": {
            "archives": len(trashed_archives),
        },
        "children": details,
        "deleted": deleted_count,
    }


async def _hard_delete_category(
    db: SQLModelAsyncSession,
    category: CourseCategoryConfig,
    warnings: list[str],
) -> dict:
    existing_courses = (
        (await db.execute(select(Course).where(Course.category == category.key)))
        .scalars()
        .all()
    )
    if existing_courses:
        raise _blocked(
            f"阻擋永久刪除：{_dependency_count(len(existing_courses), '門')}課程仍屬於此分類，請先永久刪除課程",
            [
                _blocker("course", course.id, course.name)
                for course in existing_courses
                if course.id is not None
            ],
        )

    blockers = [
        *(await _get_active_category_submission_blockers(db, category)),
    ]
    if blockers:
        raise _blocked("仍有未刪除的投稿依附於此分類", blockers)

    await db.delete(category)
    return {
        "type": "course_category",
        "id": category.id,
        "name": category.name,
        "deletedChildren": {},
        "children": [],
        "deleted": 1,
    }


async def _hard_delete_user(
    db: SQLModelAsyncSession,
    user: User,
    warnings: list[str],
) -> dict:
    blockers = await _get_active_user_blockers(db, user)
    if blockers:
        raise _blocked("仍有未刪除的上傳或投稿依附於此使用者", blockers)

    trashed_archives = (
        (
            await db.execute(
                select(Archive).where(
                    Archive.uploader_id == user.id,
                    Archive.deleted_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    trashed_submissions = (
        (
            await db.execute(
                select(ArchiveSubmission).where(
                    or_(
                        ArchiveSubmission.owner_id == user.id,
                        ArchiveSubmission.requester_id == user.id,
                    ),
                    or_(
                        ArchiveSubmission.deleted_at.is_not(None),
                        ArchiveSubmission.status == SubmissionStatus.DELETED,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    details = []
    deleted_count = 1
    for submission in trashed_submissions:
        current_submission = await db.get(ArchiveSubmission, submission.id)
        if not current_submission:
            continue
        detail = await _hard_delete_submission(db, current_submission, warnings)
        details.append(detail)
        deleted_count += detail.get("deleted", 0)

    for archive in trashed_archives:
        current_archive = await db.get(Archive, archive.id)
        if not current_archive:
            continue
        detail = await _hard_delete_archive(db, current_archive, warnings)
        details.append(detail)
        deleted_count += detail.get("deleted", 0)

    await db.delete(user)
    return {
        "type": "user",
        "id": user.id,
        "name": user.name,
        "deletedChildren": {
            "archives": len(trashed_archives),
            "submissions": len(trashed_submissions),
        },
        "children": details,
        "deleted": deleted_count,
    }


@router.get("", response_model=list[TrashItem])
async def list_trash_items(
    item_type: str | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    normalized_item_type = item_type
    if isinstance(item_type, str):
        if item_type.lower() == "all":
            normalized_item_type = None
        else:
            try:
                normalized_item_type = TrashEntityType(item_type)
            except ValueError:
                logger.warning("Unknown trash item_type filter received: %s", item_type)
                normalized_item_type = None

    users_by_id = {
        user.id: user
        for user in (await db.execute(select(User))).scalars().all()
        if user.id is not None
    }
    items: list[TrashItem] = []

    if normalized_item_type in (None, TrashEntityType.SYSTEM_ISSUE_REPORT):
        reports = (
            (
                await db.execute(
                    select(SystemIssueReport)
                    .where(SystemIssueReport.deleted_at.is_not(None))
                    .order_by(SystemIssueReport.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for report in reports:
            reporter = users_by_id.get(report.reporter_user_id)
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.SYSTEM_ISSUE_REPORT,
                    item_id=report.id,
                    display_name=report.title,
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(
                        users_by_id, report.deleted_by_id
                    ),
                    status=report.status,
                    created_at=report.created_at,
                    reporter_name=(
                        _format_deleted_by(users_by_id, report.reporter_user_id)
                        if reporter is not None
                        else "已刪除使用者"
                    ),
                    report_type=report.report_type,
                    github_issue_number=report.github_issue_number,
                    github_issue_url=report.github_issue_url,
                    dependencies=[],
                )
            )

    if normalized_item_type in (None, TrashEntityType.COMMENT_REPORT):
        reports = (
            (
                await db.execute(
                    select(CommentReport)
                    .where(CommentReport.deleted_at.is_not(None))
                    .order_by(CommentReport.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for report in reports:
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.COMMENT_REPORT,
                    item_id=report.id,
                    display_name=COMMENT_REPORT_REASON_LABELS.get(
                        report.reason, report.reason
                    ),
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(
                        users_by_id, report.deleted_by_id
                    ),
                    status=report.status,
                    reason=report.reason,
                    created_at=report.created_at,
                    reporter_name=_format_deleted_by(
                        users_by_id, report.reporter_user_id
                    ),
                    comment_author_name=report.comment_author_name_snapshot,
                    comment_snapshot=report.comment_content_snapshot,
                    course_id=report.course_id,
                    course_name=report.course_name_snapshot,
                    archive_name=report.archive_name_snapshot,
                    dependencies=[],
                )
            )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE_WISH_REPORT):
        reports = (
            (
                await db.execute(
                    select(ArchiveWishReport)
                    .where(ArchiveWishReport.deleted_at.is_not(None))
                    .order_by(ArchiveWishReport.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for report in reports:
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.ARCHIVE_WISH_REPORT,
                    item_id=report.id,
                    display_name=report.wish_title_snapshot,
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(
                        users_by_id, report.deleted_by_id
                    ),
                    status=report.status,
                    reason=report.reason,
                    created_at=report.created_at,
                    reporter_name=_format_deleted_by(
                        users_by_id, report.reporter_user_id
                    ),
                    comment_snapshot=report.target_summary_snapshot,
                    dependencies=[],
                )
            )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE_REPORT):
        reports = (
            (
                await db.execute(
                    select(ArchiveReport)
                    .where(ArchiveReport.deleted_at.is_not(None))
                    .order_by(ArchiveReport.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for report in reports:
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.ARCHIVE_REPORT,
                    item_id=report.id,
                    display_name=ARCHIVE_REPORT_REASON_LABELS.get(
                        report.reason, report.reason
                    ),
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(
                        users_by_id, report.deleted_by_id
                    ),
                    status=report.status,
                    reason=report.reason,
                    created_at=report.created_at,
                    reporter_name=report.reporter_name_snapshot,
                    course_id=report.course_id,
                    course_name=report.course_name_snapshot,
                    archive_name=report.archive_name_snapshot,
                    dependencies=[],
                )
            )

    if normalized_item_type in (None, TrashEntityType.COURSE_CATEGORY):
        categories = (
            (
                await db.execute(
                    select(CourseCategoryConfig)
                    .where(CourseCategoryConfig.deleted_at.is_not(None))
                    .order_by(CourseCategoryConfig.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for category in categories:
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.COURSE_CATEGORY,
                        item_id=category.id,
                        display_name=f"{category.name} ({category.key})",
                        display_name_en=(
                            f"{category.name_en.strip()} ({category.key})"
                            if category.name_en and category.name_en.strip()
                            else None
                        ),
                        deleted_at=category.deleted_at,
                        deleted_by_id=category.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, category.deleted_by_id
                        ),
                        status="deleted",
                        action_authority=await _get_category_action_authority(
                            db, category
                        ),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed course category item (id=%s)",
                    getattr(category, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    if normalized_item_type in (None, TrashEntityType.COURSE):
        category_keys = {
            category_key
            for category_key in (
                await db.execute(
                    select(Course.category).where(Course.deleted_at.is_not(None))
                )
            ).scalars()
            if category_key
        }
        course_categories = {}
        if category_keys:
            course_categories = {
                category.key: category
                for category in (
                    await db.execute(
                        select(CourseCategoryConfig).where(
                            CourseCategoryConfig.key.in_(category_keys)
                        )
                    )
                )
                .scalars()
                .all()
            }
        courses = (
            (
                await db.execute(
                    select(Course)
                    .where(Course.deleted_at.is_not(None))
                    .order_by(Course.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for course in courses:
            category = course_categories.get(course.category)
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.COURSE,
                        item_id=course.id,
                        display_name=f"{course.name} ({course.category})",
                        display_name_en=(
                            f"{course.name_en.strip()} ({course.category})"
                            if course.name_en and course.name_en.strip()
                            else None
                        ),
                        deleted_at=course.deleted_at,
                        deleted_by_id=course.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, course.deleted_by_id
                        ),
                        status="deleted",
                        parent_type="course_category",
                        parent_id=category.id if category else None,
                        parent_name=category.name if category else course.category,
                        parent_name_en=(
                            category.name_en.strip()
                            if category
                            and category.name_en
                            and category.name_en.strip()
                            else None
                        ),
                        action_authority=await _get_course_action_authority(db, course),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed course item (id=%s)",
                    getattr(course, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE):
        archive_course_ids = {
            archive_course_id
            for archive_course_id in (
                await db.execute(
                    select(Archive.course_id).where(Archive.deleted_at.is_not(None))
                )
            ).scalars()
            if archive_course_id is not None
        }
        archive_courses = {}
        if archive_course_ids:
            archive_courses = {
                course.id: course
                for course in (
                    await db.execute(
                        select(Course).where(Course.id.in_(archive_course_ids))
                    )
                )
                .scalars()
                .all()
            }
        archives = (
            (
                await db.execute(
                    select(Archive)
                    .where(Archive.deleted_at.is_not(None))
                    .order_by(Archive.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        archive_parent_submissions = {}
        archive_source_submissions = {}
        trashed_archive_ids = [
            archive.id for archive in archives if archive.id is not None
        ]
        if trashed_archive_ids:
            linked_submissions = (
                (
                    await db.execute(
                        select(ArchiveSubmission)
                        .where(
                            ArchiveSubmission.created_archive_id.in_(
                                trashed_archive_ids
                            ),
                        )
                        .order_by(
                            ArchiveSubmission.deleted_at.desc(),
                            ArchiveSubmission.reviewed_at.desc(),
                            ArchiveSubmission.created_at.desc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for submission in linked_submissions:
                if submission.created_archive_id is None:
                    continue
                archive_source_submissions.setdefault(
                    submission.created_archive_id, submission
                )
                course_trash_parent_course = archive_courses.get(
                    get_course_trash_course_id(submission.lifecycle_reason)
                )
                if is_archive_submission_trashed(submission) or (
                    _is_course_trash_temporary_submission(submission)
                    and course_trash_parent_course is not None
                    and course_trash_parent_course.deleted_at is not None
                ):
                    archive_parent_submissions.setdefault(
                        submission.created_archive_id, submission
                    )
            course_trash_parent_course_ids = {
                course_id
                for submission in linked_submissions
                for course_id in (
                    get_course_trash_course_id(submission.lifecycle_reason),
                )
                if course_id is not None and course_id not in archive_courses
            }
            if course_trash_parent_course_ids:
                archive_courses.update(
                    {
                        course.id: course
                        for course in (
                            await db.execute(
                                select(Course).where(
                                    Course.id.in_(course_trash_parent_course_ids)
                                )
                            )
                        )
                        .scalars()
                        .all()
                        if course.id is not None
                    }
                )
        for archive in archives:
            parent_submission = archive_parent_submissions.get(archive.id)
            source_submission = parent_submission or archive_source_submissions.get(
                archive.id
            )
            course_trash_parent_course_id = (
                get_course_trash_course_id(source_submission.lifecycle_reason)
                if source_submission
                and is_course_trash_lifecycle_reason(source_submission.lifecycle_reason)
                else None
            )
            course = archive_courses.get(
                course_trash_parent_course_id or archive.course_id
            )
            snapshot_course_name = (
                source_submission.requested_course_name
                if source_submission and source_submission.requested_course_name
                else course.name
                if course
                else None
            )
            snapshot_course_name_en = (
                source_submission.requested_course_name_en.strip()
                if source_submission
                and source_submission.requested_course_name_en
                and source_submission.requested_course_name_en.strip()
                else None
                if source_submission and source_submission.requested_course_name
                else course.name_en.strip()
                if course and course.name_en and course.name_en.strip()
                else None
            )
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.ARCHIVE,
                        item_id=archive.id,
                        display_name=archive.name,
                        academic_year=archive.academic_year,
                        academic_term=_format_academic_term(archive.academic_year),
                        deleted_at=archive.deleted_at,
                        deleted_by_id=archive.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, archive.deleted_by_id
                        ),
                        status="deleted",
                        parent_type="archive_submission"
                        if parent_submission
                        else "course",
                        parent_id=parent_submission.id
                        if parent_submission
                        else archive.course_id,
                        parent_name=(
                            f"{parent_submission.subject} / {parent_submission.name}"
                            if parent_submission
                            else course.name
                            if course
                            else None
                        ),
                        parent_name_en=(
                            f"{snapshot_course_name_en} / {parent_submission.name}"
                            if parent_submission and snapshot_course_name_en
                            else course.name_en.strip()
                            if not parent_submission
                            and course
                            and course.name_en
                            and course.name_en.strip()
                            else None
                        ),
                        course_id=archive.course_id,
                        course_name=snapshot_course_name,
                        course_name_en=snapshot_course_name_en,
                        source_submission_id=source_submission.id
                        if source_submission
                        else None,
                        action_authority=await _get_archive_action_authority(
                            db,
                            archive,
                            source_submission,
                            restore_parent_submission=parent_submission,
                        ),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed archive item (id=%s)",
                    getattr(archive, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    if normalized_item_type in (None, TrashEntityType.NOTIFICATION):
        notifications = (
            (
                await db.execute(
                    select(Notification)
                    .where(Notification.deleted_at.is_not(None))
                    .order_by(Notification.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for notification in notifications:
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.NOTIFICATION,
                        item_id=notification.id,
                        display_name=notification.title,
                        deleted_at=notification.deleted_at,
                        deleted_by_id=notification.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, notification.deleted_by_id
                        ),
                        status="deleted",
                        dependencies=[],
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed notification item (id=%s)",
                    getattr(notification, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    if normalized_item_type in (None, TrashEntityType.USER):
        users = (
            (
                await db.execute(
                    select(User)
                    .where(User.deleted_at.is_not(None))
                    .order_by(User.deleted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for user in users:
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.USER,
                        item_id=user.id,
                        display_name=user.name,
                        user_email=user.email,
                        deleted_at=user.deleted_at,
                        deleted_by_id=user.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, user.deleted_by_id
                        ),
                        status="deleted",
                        action_authority=await _get_user_action_authority(db, user),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed user item (id=%s)",
                    getattr(user, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    if normalized_item_type in (None, TrashEntityType.COURSE_SUBMISSION):
        course_submissions = (
            (
                await db.execute(
                    select(CourseSubmission)
                    .where(
                        or_(
                            CourseSubmission.deleted_at.is_not(None),
                            CourseSubmission.status == SubmissionStatus.DELETED,
                        )
                    )
                    .order_by(
                        CourseSubmission.deleted_at.desc().nullslast(),
                        CourseSubmission.created_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        created_course_ids = {
            submission.created_course_id
            for submission in course_submissions
            if submission.created_course_id is not None
        }
        courses_by_id = (
            {
                course.id: course
                for course in (
                    await db.execute(
                        select(Course).where(Course.id.in_(created_course_ids))
                    )
                )
                .scalars()
                .all()
            }
            if created_course_ids
            else {}
        )
        for submission in course_submissions:
            linked_course = courses_by_id.get(submission.created_course_id)
            restore_available = (
                submission.status == SubmissionStatus.DELETED
                and submission.deleted_at is not None
                and submission.previous_status is not None
            )
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.COURSE_SUBMISSION,
                    item_id=submission.id,
                    display_name=f"{submission.name} ({submission.category})",
                    deleted_at=submission.deleted_at,
                    deleted_by_id=submission.deleted_by_id,
                    deleted_by_name=_format_deleted_by(
                        users_by_id, submission.deleted_by_id
                    ),
                    status=submission.status.value,
                    parent_type="course" if linked_course else None,
                    parent_id=linked_course.id if linked_course else None,
                    parent_name=linked_course.name if linked_course else None,
                    course_id=linked_course.id if linked_course else None,
                    course_name=linked_course.name if linked_course else None,
                    created_at=submission.created_at,
                    can_restore=restore_available,
                    dependencies=(
                        []
                        if restore_available
                        else ["無法還原：舊資料缺少可驗證的原始審核狀態"]
                    ),
                )
            )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE_SUBMISSION):
        is_course_trash_reason = or_(
            ArchiveSubmission.lifecycle_reason == LIFECYCLE_COURSE_TRASHED,
            ArchiveSubmission.lifecycle_reason.like(f"{LIFECYCLE_COURSE_TRASHED}|%"),
        )
        trashed_archive_ids = {
            archive_id
            for archive_id in (
                await db.execute(
                    select(Archive.id).where(Archive.deleted_at.is_not(None))
                )
            ).scalars()
            if archive_id is not None
        }
        submissions = (
            (
                await db.execute(
                    select(ArchiveSubmission)
                    .where(
                        or_(
                            ArchiveSubmission.deleted_at.is_not(None),
                            func.lower(cast(ArchiveSubmission.status, String))
                            == SubmissionStatus.DELETED.value,
                            and_(
                                ArchiveSubmission.deleted_at.is_(None),
                                ArchiveSubmission.status == SubmissionStatus.TAKEDOWN,
                                is_course_trash_reason,
                            ),
                        )
                    )
                    .order_by(
                        ArchiveSubmission.deleted_at.desc(),
                        ArchiveSubmission.reviewed_at.desc(),
                        ArchiveSubmission.created_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        archive_map = {}
        created_archive_ids = {
            submission.created_archive_id
            for submission in submissions
            if submission.created_archive_id is not None
        }
        if created_archive_ids:
            archive_rows = (
                (
                    await db.execute(
                        select(Archive).where(Archive.id.in_(created_archive_ids))
                    )
                )
                .scalars()
                .all()
            )
            archive_map = {
                archive.id: archive
                for archive in archive_rows
                if archive.id is not None
            }

        submission_linked_archive_map: dict[int, Archive | None] = {}
        for submission in submissions:
            is_course_trash_temporary = _is_course_trash_temporary_submission(
                submission
            )
            linked_archive = (
                archive_map.get(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            )
            if (
                linked_archive is None
                and submission.id is not None
                and submission.id not in submission_linked_archive_map
            ):
                linked_archive, _ = await _resolve_submission_linked_archive(
                    db, submission
                )
                submission_linked_archive_map[submission.id] = linked_archive
            if linked_archive is None and submission.id is not None:
                linked_archive = submission_linked_archive_map[submission.id]
            linked_archive_id = (
                linked_archive.id
                if linked_archive and linked_archive.id is not None
                else None
            )
            linked_course = (
                await db.get(Course, linked_archive.course_id)
                if linked_archive and linked_archive.course_id is not None
                else None
            )
            course_trash_course_id = get_course_trash_course_id(
                submission.lifecycle_reason
            )
            course_trash_course = (
                await db.get(Course, course_trash_course_id)
                if is_course_trash_temporary and course_trash_course_id is not None
                else None
            )
            if is_course_trash_temporary and (
                not course_trash_course or course_trash_course.deleted_at is None
            ):
                continue
            deleted_at = (
                submission.deleted_at
                or (
                    course_trash_course.deleted_at
                    if is_course_trash_temporary and course_trash_course
                    else None
                )
                or submission.reviewed_at
                or submission.created_at
            )
            parent_course = course_trash_course or linked_course
            parent_type = (
                "course"
                if parent_course is not None and parent_course.deleted_at is not None
                else None
            )
            parent_id = parent_course.id if parent_type == "course" else None
            parent_name = (
                parent_course.name
                if parent_type == "course"
                else linked_archive.name
                if linked_archive
                else None
            )
            snapshot_course_name = (
                submission.requested_course_name
                or (parent_course.name if parent_course else None)
                or (linked_course.name if linked_course else None)
                or submission.subject
            )
            snapshot_course_name_en = (
                submission.requested_course_name_en.strip()
                if submission.requested_course_name_en
                and submission.requested_course_name_en.strip()
                else None
                if submission.requested_course_name
                else parent_course.name_en.strip()
                if parent_course
                and parent_course.name_en
                and parent_course.name_en.strip()
                else linked_course.name_en.strip()
                if linked_course
                and linked_course.name_en
                and linked_course.name_en.strip()
                else None
            )
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.ARCHIVE_SUBMISSION,
                        item_id=submission.id,
                        display_name=f"{submission.subject} / {submission.name}",
                        display_name_en=(
                            f"{snapshot_course_name_en} / {submission.name}"
                            if snapshot_course_name_en
                            else None
                        ),
                        academic_year=submission.academic_year,
                        academic_term=_format_academic_term(submission.academic_year),
                        deleted_at=deleted_at,
                        deleted_by_id=submission.deleted_by_id,
                        deleted_by_name=_format_deleted_by(
                            users_by_id, submission.deleted_by_id
                        ),
                        status=submission.status.value,
                        parent_type=parent_type,
                        parent_id=parent_id,
                        parent_name=parent_name,
                        parent_name_en=(
                            parent_course.name_en.strip()
                            if parent_type == "course"
                            and parent_course
                            and parent_course.name_en
                            and parent_course.name_en.strip()
                            else None
                        ),
                        created_archive_id=linked_archive_id,
                        source_submission_id=submission.id,
                        course_id=(
                            parent_course.id
                            if parent_course
                            else linked_archive.course_id
                            if linked_archive
                            else None
                        ),
                        course_name=snapshot_course_name,
                        course_name_en=snapshot_course_name_en,
                        requested_course_name=submission.requested_course_name,
                        requested_course_name_en=submission.requested_course_name_en,
                        requested_category_name=submission.requested_category_name,
                        requested_category_name_en=submission.requested_category_name_en,
                        requested_category_label=submission.requested_category_label,
                        requested_category_label_en=submission.requested_category_label_en,
                        action_authority=await _get_submission_action_authority(
                            db, submission
                        ),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed archive submission item (id=%s)",
                    getattr(submission, "id", None),
                    exc_info=redacted_exc_info(exc),
                )

    deduped_items = _dedupe_trash_items(items)
    await _apply_permanent_deletion_projections(db, deduped_items)
    return sorted(
        deduped_items,
        key=lambda item: item.deleted_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


@router.post("/restore")
async def restore_trash_item(
    payload: TrashActionRequest,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    now = datetime.now(UTC)

    if payload.item_type == TrashEntityType.SYSTEM_ISSUE_REPORT:
        report = await _lock_simple_trash_root(db, SystemIssueReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System issue report not found",
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "系統問題回報已還原"}

    if payload.item_type == TrashEntityType.COMMENT_REPORT:
        report = await _lock_simple_trash_root(db, CommentReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment report not found",
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "留言回報已還原"}

    if payload.item_type == TrashEntityType.ARCHIVE_WISH_REPORT:
        report = await _lock_simple_trash_root(db, ArchiveWishReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wish report not found",
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "許願回報已還原"}

    if payload.item_type == TrashEntityType.ARCHIVE_REPORT:
        await acquire_archive_report_uniqueness_mutex_for_report(
            db,
            report_id=payload.item_id,
        )
        locked = await acquire_stable_archive_report_locks(
            db,
            report_id=payload.item_id,
            operation="archive_report_restore",
        )
        if locked is None or locked.report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Archive report not found",
            )
        report = locked.report
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        if (
            report.status == "pending"
            and report.reporter_user_id is not None
            and report.archive_id is not None
        ):
            conflict = await db.scalar(
                select(ArchiveReport.id).where(
                    ArchiveReport.id != report.id,
                    ArchiveReport.reporter_user_id == report.reporter_user_id,
                    ArchiveReport.archive_id == report.archive_id,
                    ArchiveReport.status == "pending",
                    ArchiveReport.deleted_at.is_(None),
                )
            )
            if conflict is not None:
                await db.rollback()
                raise archive_report_restore_pending_conflict_error()
        report.deleted_at = None
        report.deleted_by_id = None
        try:
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            if is_archive_report_pending_unique_violation(error):
                raise archive_report_restore_pending_conflict_error() from error
            raise
        return {"message": "考古題回報已還原"}

    if payload.item_type == TrashEntityType.COURSE_CATEGORY:
        category = await _lock_simple_trash_root(
            db, CourseCategoryConfig, payload.item_id
        )
        if not category or category.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        if category.pre_delete_is_active is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Category restore state is unavailable",
            )

        category.is_active = category.pre_delete_is_active
        category.deleted_at = None
        category.restored_at = now
        category.restored_by_id = current_user.user_id
        category.deleted_by_id = None
        category.pre_delete_is_active = None
        await db.commit()
        return {
            "message": "已復原分類「"
            + category.name
            + "」，課程不會自動復原，若需要請另外復原課程。",
            "restoredCourses": 0,
        }

    if payload.item_type == TrashEntityType.COURSE_SUBMISSION:
        submission = (
            await db.execute(
                select(CourseSubmission)
                .where(CourseSubmission.id == payload.item_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if submission is None or submission.status != SubmissionStatus.DELETED:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course request not found",
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )
        if submission.deleted_at is None or submission.previous_status is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Course request restore state is unavailable",
            )

        submission.status = submission.previous_status
        submission.previous_status = None
        submission.deleted_at = None
        submission.deleted_by_id = None
        submission.restored_at = now
        submission.restored_by_id = current_user.user_id
        await db.commit()
        return {"message": "Course request restored"}

    if payload.item_type == TrashEntityType.COURSE:
        budget = PlanRebuildBudget()
        locked_course_plan = None
        while True:
            (
                locked_course_plan,
                revalidation,
            ) = await course_lifecycle_locks.acquire_course_lifecycle_plan_once(
                db,
                course_id=payload.item_id,
                operation=CourseLifecycleOperation.RESTORE,
            )
            if locked_course_plan is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course not found",
                )
            if revalidation is not None and revalidation.valid:
                break

            await db.rollback()
            try:
                budget = budget.consume()
            except LifecyclePlanRetryExhausted:
                raise course_lifecycle_conflict_error()

        course = locked_course_plan.rows.course(payload.item_id)
        if course is None or course.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found",
            )
        await _reject_restore_after_acceptance(
            db,
            item_type=TrashEntityType.COURSE,
            item_id=payload.item_id,
        )
        category_ids = locked_course_plan.plan.lock_plan.ids_for(
            archive_lifecycle_locks.LifecycleResourceClass.COURSE_CATEGORY
        )
        category = (
            locked_course_plan.rows.category(category_ids[0]) if category_ids else None
        )
        if not category or category.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Category is deleted; restore category before restoring this course.",
            )

        course.deleted_at = None
        course.deleted_by_id = None
        course.restored_at = now
        course.restored_by_id = current_user.user_id

        mutable_archive_ids = set(locked_course_plan.plan.mutable_archive_ids)
        archives = [
            archive
            for archive in locked_course_plan.rows.archives
            if archive.id in mutable_archive_ids
        ]
        restored_archives_count = 0
        skipped_submission_archive_count = len(
            locked_course_plan.plan.blocked_archive_ids
        )
        for archive in archives:
            archive.deleted_at = None
            archive.deleted_by_id = None
            archive.deleted_reason = None
            archive.restored_at = now
            archive.restored_by_id = current_user.user_id
            restored_archives_count += 1

        restored_submission_count = 0
        skipped_submission_count = 0
        mutable_submission_ids = set(locked_course_plan.plan.mutable_submission_ids)
        submissions = [
            submission
            for submission in locked_course_plan.rows.submissions
            if submission.id in mutable_submission_ids
        ]
        for submission in submissions:
            previous_status = get_course_trash_previous_status(
                submission.lifecycle_reason
            )
            if previous_status in {
                SubmissionStatus.APPROVED,
                SubmissionStatus.PENDING,
                SubmissionStatus.REJECTED,
                SubmissionStatus.TAKEDOWN,
            }:
                submission.status = previous_status
                restored_submission_count += 1
            else:
                skipped_submission_count += 1

            submission.lifecycle_reason = None
            submission.reviewer_id = current_user.user_id
            submission.reviewed_at = now

        await db.commit()
        message = (
            f"已復原課程「{course.name}」，並復原 {restored_archives_count} 筆考古題；"
        )
        message += f"{restored_submission_count} 筆投稿已回到原本狀態。"
        if skipped_submission_count:
            message += f"{skipped_submission_count} 筆投稿因缺少原本狀態仍維持已下架。"
        if skipped_submission_archive_count:
            message += f"另有 {skipped_submission_archive_count} 筆考古題仍屬於已刪除投稿，需還原投稿後才會復原。"
        return {
            "message": message,
            "restoredArchivesCount": restored_archives_count,
            "restoredSubmissionsCount": restored_submission_count,
            "skippedSubmissionsCount": skipped_submission_count,
            "skippedSubmissionArchiveCount": skipped_submission_archive_count,
        }

    if payload.item_type == TrashEntityType.NOTIFICATION:
        notification = await _lock_simple_trash_root(db, Notification, payload.item_id)
        if not notification or notification.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )

        notification.deleted_at = None
        notification.deleted_by_id = None
        await db.commit()
        return {"message": "Notification restored"}

    if payload.item_type == TrashEntityType.ARCHIVE:
        budget = PlanRebuildBudget()
        locked = None
        while True:
            (
                locked,
                revalidation,
            ) = await archive_lifecycle_locks.acquire_exact_archive_lifecycle_locks(
                db,
                archive_id=payload.item_id,
                operation="archive_restore",
            )
            if locked is None:
                break
            if revalidation is not None and revalidation.valid:
                break
            conflict_archive = locked.archive(payload.item_id)
            terminal_error = (
                HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Archive not found",
                )
                if conflict_archive is None or conflict_archive.deleted_at is None
                else None
            )
            await db.rollback()
            try:
                budget = budget.consume()
            except LifecyclePlanRetryExhausted:
                if terminal_error is not None:
                    raise terminal_error
                raise archive_lifecycle_conflict_error()

        archive = locked.archive(payload.item_id) if locked is not None else None
        if not archive or archive.deleted_at is None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
            )
        await _reject_restore_after_acceptance(
            db,
            item_type=TrashEntityType.ARCHIVE,
            item_id=payload.item_id,
        )

        parent_submission = next(
            (
                submission
                for submission in locked.submissions
                if is_archive_submission_trashed(submission)
            ),
            None,
        )
        if parent_submission:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="此考古題需隨上層投稿一起還原，請先還原投稿。",
            )

        course = locked.course(archive.course_id)
        if not course or course.deleted_at is not None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Course is deleted; restore course before restoring this archive.",
            )

        result = await restore_archive_with_temporary_submissions(
            db,
            archive=archive,
            submissions=locked.submissions,
            user_id=current_user.user_id,
            now=now,
        )

        await db.commit()
        restored_archives = int(result.get("archives", 0))
        restored_submissions = int(result.get("submissions_restored", 0))
        message = f"已復原考古題「{archive.name}」"
        if restored_submissions:
            message += f"；已恢復 {restored_submissions} 筆投稿可用狀態。"
        elif restored_archives:
            message += "；未找到因下架而停用的投稿。"
        return {
            "message": message,
            "restoredArchivesCount": restored_archives,
            "restoredSubmissionsCount": restored_submissions,
            "restored": result,
        }

    if payload.item_type == TrashEntityType.USER:
        user = await _lock_simple_trash_root(db, User, payload.item_id)
        if not user or user.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        await _reject_restore_after_acceptance(
            db, item_type=payload.item_type, item_id=payload.item_id
        )

        user.deleted_at = None
        user.deleted_by_id = None
        await db.commit()
        return {"message": "User restored"}

    if payload.item_type == TrashEntityType.ARCHIVE_SUBMISSION:
        locked = await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=payload.item_id,
            operation="submission_restore",
        )
        submission = locked.submission(payload.item_id) if locked is not None else None
        if not submission or (
            submission.deleted_at is None
            and submission.status != SubmissionStatus.DELETED
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )
        await _reject_restore_after_acceptance(
            db,
            item_type=TrashEntityType.ARCHIVE_SUBMISSION,
            item_id=payload.item_id,
        )
        if submission.lifecycle_reason == LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法復原：關聯考古題已永久刪除",
            )

        try:
            await ensure_archive_submission_link_available(
                db,
                submission_id=submission.id,
                current_archive_id=submission.created_archive_id,
                target_archive_id=submission.created_archive_id,
                operation="restore",
            )
        except Exception:
            await db.rollback()
            raise

        group = await collect_archive_submission_group(
            db,
            archive=(
                locked.archive(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            ),
            submission=submission,
            exact_link_only=True,
        )
        for linked_archive in group.archives:
            course = locked.course(linked_archive.course_id)
            if not course or course.deleted_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot restore: linked course is deleted. Restore course first.",
                )

        result = await restore_archive_submission_group(
            db,
            archive=(
                locked.archive(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            ),
            submission=submission,
            user_id=current_user.user_id,
            now=now,
            exact_link_only=True,
        )

        await db.commit()
        restored_submissions = int(result.get("submissions", 0))
        message = f"已復原投稿 #{submission.id}"
        if restored_submissions:
            message += "，關聯投稿已一併復原。"
        return {
            "message": message,
            "restoredSubmissionsCount": restored_submissions,
            "restored": result,
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported trash item type"
    )


async def _get_public_permanent_deletion_operation(
    db: SQLModelAsyncSession, operation_id: int
) -> PermanentDeletionOperation:
    operation = await db.get(PermanentDeletionOperation, operation_id)
    if operation is None or operation.root_entity_type not in {
        item.value for item in _DURABLE_DELETE_TYPES
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permanent deletion operation not found",
        )
    return operation


async def _process_public_permanent_deletion_once(
    db: SQLModelAsyncSession, operation: PermanentDeletionOperation
) -> PermanentDeletionOperation:
    try:
        await process_one_permanent_deletion(
            db,
            operation_id=int(operation.id),
            storage=_permanent_deletion_storage_for_root(
                TrashEntityType(operation.root_entity_type)
            ),
        )
    except Exception as exc:
        await db.rollback()
        logger.error(
            "Bounded permanent-delete progression failed for operation %s",
            operation.id,
            exc_info=redacted_exc_info(exc),
        )
    refreshed = await db.get(PermanentDeletionOperation, int(operation.id))
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "accepted_operation_unavailable",
                "message": "永久刪除狀態暫時無法確認",
            },
        )
    return refreshed


@router.get("/permanent-deletions/{operation_id}", response_model=PermanentDeletionRead)
async def get_permanent_deletion_status(
    operation_id: int,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    operation = await _get_public_permanent_deletion_operation(db, operation_id)
    return _to_permanent_deletion_read(operation)


@router.post(
    "/permanent-deletions/{operation_id}/retry",
    response_model=PermanentDeletionRead,
)
async def retry_permanent_deletion(
    operation_id: int,
    response: Response,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    operation = await _get_public_permanent_deletion_operation(db, operation_id)
    current = _to_permanent_deletion_read(operation)
    if not current.can_retry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "permanent_deletion_retry_not_available",
                "message": "目前不可重新嘗試永久刪除",
            },
        )
    operation = await _process_public_permanent_deletion_once(db, operation)
    projection = _to_permanent_deletion_read(operation)
    response.status_code = (
        status.HTTP_200_OK
        if projection.status == PermanentDeletionStatus.COMPLETED
        else status.HTTP_202_ACCEPTED
    )
    return projection


def _bulk_outcome_for_projection(
    projection: PermanentDeletionRead,
) -> PermanentDeletionBulkOutcome:
    if projection.status == PermanentDeletionStatus.COMPLETED:
        return PermanentDeletionBulkOutcome.COMPLETED
    if projection.status == PermanentDeletionStatus.MANUAL_REVIEW:
        return PermanentDeletionBulkOutcome.MANUAL_REVIEW
    return PermanentDeletionBulkOutcome.PENDING


def _safe_bulk_failure_detail(error: HTTPException) -> tuple[str, str]:
    code = (
        str(error.detail.get("code"))
        if isinstance(error.detail, dict) and error.detail.get("code")
        else "permanent_deletion_not_accepted"
    )
    safe_messages = {
        "root_not_permanently_deletable": "垃圾桶項目不存在",
        "versioning_state_unavailable": "永久刪除未接受，請稍後再試",
        "object_history_unavailable": "永久刪除未接受，請稍後再試",
        "exact_stat_failed": "永久刪除未接受，請稍後再試",
        "exact_stat_unavailable": "永久刪除未接受，請稍後再試",
        "current_identity_unavailable": "永久刪除未接受，請稍後再試",
        "target_reservation_conflict": "目前無法接受永久刪除",
        "category_has_blocking_dependencies": "仍有依賴資料阻擋永久刪除",
        "course_has_active_archives": "仍有依賴資料阻擋永久刪除",
        "user_has_active_storage_children": "仍有依賴資料阻擋永久刪除",
        "permanent_deletion_acceptance_unavailable": "永久刪除未接受，請稍後再試",
    }
    return code[:64], safe_messages.get(code, "永久刪除未接受")


@router.delete("/bulk", response_model=PermanentDeletionBulkRead)
async def bulk_permanently_delete_trash_items(
    item_type: TrashEntityType | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    items = await list_trash_items(
        item_type=item_type, current_user=current_user, db=db
    )
    delete_order = {
        TrashEntityType.COURSE_SUBMISSION: 0,
        TrashEntityType.ARCHIVE_SUBMISSION: 1,
        TrashEntityType.ARCHIVE: 2,
        TrashEntityType.COURSE: 3,
        TrashEntityType.COURSE_CATEGORY: 4,
        TrashEntityType.NOTIFICATION: 5,
        TrashEntityType.USER: 6,
        TrashEntityType.SYSTEM_ISSUE_REPORT: 7,
        TrashEntityType.COMMENT_REPORT: 8,
        TrashEntityType.ARCHIVE_WISH_REPORT: 9,
        TrashEntityType.ARCHIVE_REPORT: 10,
    }
    sorted_items = sorted(
        items,
        key=lambda item: delete_order.get(TrashEntityType(item.item_type), 99),
    )
    results: list[PermanentDeletionBulkItemResult] = []
    batch_operation_ids: set[int] = set()

    for item in sorted_items:
        trash_type = TrashEntityType(item.item_type)
        try:
            projection = await _initiate_public_permanent_deletion(
                item_type=trash_type,
                item_id=item.id,
                current_user=current_user,
                db=db,
            )
            batch_operation_ids.add(projection.operation_id)
            results.append(
                PermanentDeletionBulkItemResult(
                    item_type=trash_type,
                    item_id=item.id,
                    display_name=item.display_name,
                    outcome=_bulk_outcome_for_projection(projection),
                    operation=projection,
                )
            )
        except HTTPException as error:
            await db.rollback()
            code, message = _safe_bulk_failure_detail(error)
            covering: PermanentDeletionRead | None = None
            include_released = False
            operation_ids: set[int] | None = None
            if code == "target_reservation_conflict":
                covering = await _proven_covering_permanent_deletion(
                    db,
                    item_type=trash_type,
                    item_id=item.id,
                    operation_ids=None,
                    include_released=False,
                )
            elif error.status_code == status.HTTP_404_NOT_FOUND:
                operation_ids = batch_operation_ids
                include_released = True
            if covering is None and operation_ids:
                covering = await _proven_covering_permanent_deletion(
                    db,
                    item_type=trash_type,
                    item_id=item.id,
                    operation_ids=operation_ids,
                    include_released=include_released,
                )
            if covering is not None:
                results.append(
                    PermanentDeletionBulkItemResult(
                        item_type=trash_type,
                        item_id=item.id,
                        display_name=item.display_name,
                        outcome=PermanentDeletionBulkOutcome.SKIPPED,
                        operation=covering,
                        reason_code="covered_by_permanent_deletion",
                        reason_message="已由另一筆永久刪除作業涵蓋",
                    )
                )
                continue
            results.append(
                PermanentDeletionBulkItemResult(
                    item_type=trash_type,
                    item_id=item.id,
                    display_name=item.display_name,
                    outcome=PermanentDeletionBulkOutcome.FAILED,
                    reason_code=code,
                    reason_message=message,
                )
            )
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Unexpected permanent-delete failure for %s/%s",
                trash_type.value,
                item.id,
                exc_info=redacted_exc_info(exc),
            )
            results.append(
                PermanentDeletionBulkItemResult(
                    item_type=trash_type,
                    item_id=item.id,
                    display_name=item.display_name,
                    outcome=PermanentDeletionBulkOutcome.FAILED,
                    reason_code="permanent_deletion_evaluation_failed",
                    reason_message="永久刪除未接受，請稍後再試",
                )
            )

    counts = {
        outcome: sum(result.outcome == outcome for result in results)
        for outcome in PermanentDeletionBulkOutcome
    }
    return PermanentDeletionBulkRead(
        scope=item_type,
        requested_count=len(sorted_items),
        completed_count=counts[PermanentDeletionBulkOutcome.COMPLETED],
        pending_count=counts[PermanentDeletionBulkOutcome.PENDING],
        manual_review_count=counts[PermanentDeletionBulkOutcome.MANUAL_REVIEW],
        failed_count=counts[PermanentDeletionBulkOutcome.FAILED],
        skipped_count=counts[PermanentDeletionBulkOutcome.SKIPPED],
        results=results,
    )


async def _permanently_delete_trash_item(
    *,
    item_type: TrashEntityType,
    item_id: int,
    db: SQLModelAsyncSession,
    warnings: list[str],
):
    if item_type == TrashEntityType.SYSTEM_ISSUE_REPORT:
        report = await db.get(SystemIssueReport, item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System issue report not found",
            )

        await db.delete(report)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=report.title,
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.COMMENT_REPORT:
        report = await db.get(CommentReport, item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment report not found",
            )

        await db.delete(report)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=COMMENT_REPORT_REASON_LABELS.get(report.reason, report.reason),
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.ARCHIVE_WISH_REPORT:
        report = await db.get(ArchiveWishReport, item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wish report not found",
            )

        await db.delete(report)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=report.wish_title_snapshot,
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.ARCHIVE_REPORT:
        report = await db.get(ArchiveReport, item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Archive report not found",
            )

        await db.delete(report)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=ARCHIVE_REPORT_REASON_LABELS.get(report.reason, report.reason),
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.COURSE_CATEGORY:
        category = await db.get(CourseCategoryConfig, item_id)
        if not category or category.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
            )

        detail = await _hard_delete_category(db, category, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=category.name,
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    if item_type == TrashEntityType.COURSE_SUBMISSION:
        submission = await db.get(CourseSubmission, item_id)
        if submission is None or (
            submission.deleted_at is None
            and submission.status != SubmissionStatus.DELETED
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course request not found",
            )

        name = submission.name
        await db.delete(submission)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=name,
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.COURSE:
        course = await db.get(Course, item_id)
        if not course or course.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )

        detail = await _hard_delete_course(db, course, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=course.name,
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    if item_type == TrashEntityType.USER:
        user = await db.get(User, item_id)
        if not user or user.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        detail = await _hard_delete_user(db, user, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=user.name,
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    if item_type == TrashEntityType.ARCHIVE:
        archive = await db.get(Archive, item_id)
        if not archive or archive.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
            )

        parent_submission = await _get_deleted_submission_parent_for_archive(
            db, archive.id
        )
        detail = (
            await _hard_delete_submission_archive_pair(
                db, parent_submission, archive, warnings
            )
            if parent_submission
            else await _hard_delete_archive(db, archive, warnings)
        )
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=archive.name,
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    if item_type == TrashEntityType.NOTIFICATION:
        notification = await db.get(Notification, item_id)
        if not notification or notification.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
            )

        await db.delete(notification)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=notification.title,
            deleted=1,
            warnings=warnings,
        )

    if item_type == TrashEntityType.ARCHIVE_SUBMISSION:
        submission = await db.get(ArchiveSubmission, item_id)
        if not submission or (
            submission.deleted_at is None
            and submission.status != SubmissionStatus.DELETED
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )

        detail = await _hard_delete_submission(db, submission, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=f"{submission.subject} / {submission.name}",
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported trash item type"
    )


def _raise_permanent_deletion_acceptance_error(code: str) -> None:
    if code == "root_not_permanently_deletable":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": code, "message": "垃圾桶項目不存在"},
        )
    if code in {
        "versioning_state_unavailable",
        "object_history_unavailable",
        "exact_stat_failed",
        "exact_stat_unavailable",
        "current_identity_unavailable",
    }:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": code, "message": "永久刪除失敗，請稍後再試"},
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": "目前無法接受永久刪除"},
    )


async def _initiate_public_permanent_deletion(
    *,
    item_type: TrashEntityType,
    item_id: int,
    current_user,
    db: SQLModelAsyncSession,
) -> PermanentDeletionRead:
    operation = await _permanent_deletion_for_root(
        db, item_type=item_type, item_id=item_id
    )
    if operation is None:
        root = await db.get(_PUBLIC_PERMANENT_DELETION_ROOT_MODELS[item_type], item_id)
        if not _is_trashed_permanent_deletion_root(item_type, root):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trash item not found",
            )
        try:
            storage = _permanent_deletion_storage_for_root(item_type)
            operation = await accept_permanent_deletion(
                db,
                root_entity_type=item_type,
                root_entity_id=item_id,
                idempotency_key=_permanent_deletion_idempotency_key(item_type, item_id),
                requested_by_user_id=getattr(current_user, "user_id", None),
                storage=storage,
            )
        except PermanentDeletionError as exc:
            _raise_permanent_deletion_acceptance_error(exc.code)
        except StorageSafetyError as exc:
            _raise_permanent_deletion_acceptance_error(exc.code)
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Pre-accept permanent-delete failure for %s/%s",
                item_type.value,
                item_id,
                exc_info=redacted_exc_info(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "permanent_deletion_acceptance_unavailable",
                    "message": "永久刪除失敗，請稍後再試",
                },
            ) from exc

    projection = _to_permanent_deletion_read(operation)
    if projection.can_retry:
        operation = await _process_public_permanent_deletion_once(db, operation)
        projection = _to_permanent_deletion_read(operation)
    return projection


@router.delete("/{item_type}/{item_id}")
async def permanently_delete_trash_item(
    item_type: TrashEntityType,
    item_id: int,
    response: Response,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    projection = await _initiate_public_permanent_deletion(
        item_type=item_type,
        item_id=item_id,
        current_user=current_user,
        db=db,
    )
    response.status_code = (
        status.HTTP_200_OK
        if projection.status == PermanentDeletionStatus.COMPLETED
        else status.HTTP_202_ACCEPTED
    )
    return projection
