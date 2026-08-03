from datetime import datetime, timezone
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio.error import S3Error
from pydantic import BaseModel
from sqlalchemy import String, and_, cast, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveSubmission,
    CommentReport,
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    Notification,
    SubmissionStatus,
    SystemIssueReport,
    TrashEntityType,
    TrashItem,
    User,
)
from app.api.services.archive_submission_lifecycle import (
    archive_lifecycle_conflict_error,
    acquire_stable_submission_lifecycle_locks,
    LIFECYCLE_ARCHIVE_TRASHED,
    LIFECYCLE_COURSE_TRASHED,
    LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED,
    get_course_trash_course_id,
    get_course_trash_previous_status,
    is_course_trash_lifecycle_reason,
    collect_archive_submission_group,
    hard_delete_archive_submission_group,
    is_archive_submission_trashed,
    delete_archive_submission_events,
    mark_linked_submissions_archive_permanently_deleted,
    restore_archive_with_temporary_submissions,
    restore_archive_submission_group,
)
from app.utils.auth import get_current_user
from app.utils.course_text import (
    normalized_course_text_expr,
    normalize_course_search_text,
)
from app.utils.storage import get_minio_client
from app.services.archive_submission_links import (
    ensure_archive_submission_link_available,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    LifecyclePlanRetryExhausted,
    PlanRebuildBudget,
)

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


def _to_trash_item(
    *,
    item_type: TrashEntityType,
    item_id: int,
    display_name: str,
    deleted_at,
    deleted_by_id: Optional[int],
    deleted_by_name: Optional[str] = None,
    user_email: Optional[str] = None,
    status: Optional[str] = None,
    academic_year: Optional[int] = None,
    academic_term: Optional[str] = None,
    parent_type: Optional[str] = None,
    parent_id: Optional[int] = None,
    parent_name: Optional[str] = None,
    created_archive_id: Optional[int] = None,
    source_submission_id: Optional[int] = None,
    course_id: Optional[int] = None,
    course_name: Optional[str] = None,
    reason: Optional[str] = None,
    created_at: Optional[datetime] = None,
    reporter_name: Optional[str] = None,
    report_type: Optional[str] = None,
    github_issue_number: Optional[int] = None,
    github_issue_url: Optional[str] = None,
    comment_author_name: Optional[str] = None,
    comment_snapshot: Optional[str] = None,
    archive_name: Optional[str] = None,
    dependencies: Optional[list[str]] = None,
    can_restore: Optional[bool] = None,
    can_permanent_delete: Optional[bool] = None,
) -> TrashItem:
    return TrashItem(
        item_type=item_type,
        id=item_id,
        display_name=display_name,
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
        created_archive_id=created_archive_id,
        source_submission_id=source_submission_id,
        course_id=course_id,
        course_name=course_name,
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


def _format_academic_term(value: Optional[int]) -> Optional[str]:
    if not value:
        return None
    if 1000 <= value < 2000:
        year = value // 10
        semester = value % 10
        return f"{year}{'上' if semester == 1 else '下'}學期"
    return f"{value} 年"


def _format_deleted_by(users_by_id: dict[int, User], user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    user = users_by_id.get(user_id)
    if not user:
        return f"已刪除使用者 #{user_id}"
    return user.nickname or user.name or user.email or f"使用者 #{user_id}"


def _normalize_course_lookup_value(value: str | None) -> str:
    return normalize_course_search_text(value)


def _build_course_trash_submission_match_conditions(
    course_name: str,
    course_category: str,
) -> list:
    normalized_course_name = _normalize_course_lookup_value(course_name)
    if not normalized_course_name:
        return []

    requested_name_match = normalized_course_text_expr(ArchiveSubmission.requested_course_name) == normalized_course_name
    subject_match = normalized_course_text_expr(ArchiveSubmission.subject) == normalized_course_name
    name_match = or_(requested_name_match, subject_match)

    normalized_category = _normalize_course_lookup_value(course_category)
    if normalized_category:
        category_match = or_(
            func.lower(func.trim(ArchiveSubmission.requested_category_key)) == normalized_category,
            func.lower(func.trim(ArchiveSubmission.category)) == normalized_category,
        )
        return [and_(name_match, category_match)]

    return [name_match]


def _dependency_count(count: int, unit: str, singular_unit: Optional[str] = None) -> str:
    if count == 1 and singular_unit:
        return f"1 {singular_unit}"
    return f"{count} {unit}"


def _is_course_trash_temporary_submission(submission: ArchiveSubmission) -> bool:
    return (
        submission.deleted_at is None
        and submission.status == SubmissionStatus.TAKEDOWN
        and is_course_trash_lifecycle_reason(submission.lifecycle_reason)
    )


def _format_submission_status_label(status_value: Optional[SubmissionStatus]) -> str:
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


async def _get_category_dependency_messages(db: SQLModelAsyncSession, category: CourseCategoryConfig) -> list[str]:
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
            CourseSubmission.status != SubmissionStatus.DELETED,
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
    return [
        f"阻擋永久刪除：{_dependency_count(course_count, '門')}課程仍屬於此分類，請先永久刪除課程" if course_count else "",
        f"阻擋永久刪除：{_dependency_count(course_submissions, '筆')}啟用中課程投稿仍屬於此分類" if course_submissions else "",
        f"阻擋永久刪除：{_dependency_count(active_archive_submissions, '筆')}啟用中投稿仍屬於此分類" if active_archive_submissions else "",
    ]


async def _get_course_dependency_messages(db: SQLModelAsyncSession, course: Course) -> list[str]:
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

    return [
        *restore_blockers,
        f"阻擋永久刪除：{_dependency_count(active_archives, '筆')}啟用中考古題仍屬於此課程" if active_archives else "",
        f"一併永久刪除：{_dependency_count(trashed_archives, '筆')}已刪除考古題屬於此課程" if trashed_archives else "",
    ]


async def _get_archive_dependency_messages(
    db: SQLModelAsyncSession,
    archive: Archive,
    source_submission: Optional[ArchiveSubmission] = None,
    restore_parent_submission: Optional[ArchiveSubmission] = None,
) -> list[str]:
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
                        ArchiveSubmission.lifecycle_reason.in_([LIFECYCLE_ARCHIVE_TRASHED]),
                        is_course_trash_reason,
                    ),
                )
            )
        ).scalars().all()
        if item is not None
    ]

    return [
        (
            "阻擋還原：請先還原原課程"
            if restore_parent_submission and _is_course_trash_temporary_submission(restore_parent_submission)
            else "阻擋還原：請先還原上層投稿"
            if restore_parent_submission
            else ""
        ),
        *restore_blockers,
        f"一併永久刪除：{_dependency_count(linked_comments, '則')}留言將在考古題永久刪除時一併刪除" if linked_comments else "",
        f"阻擋永久刪除：{_dependency_count(active_linked_submissions, '筆')}啟用中投稿仍連到此考古題" if active_linked_submissions else "",
        f"關聯投稿：投稿編號 #{source_submission.id}" if source_submission and source_submission.id else "",
        (
            f"關聯投稿：投稿編號 #{temp_submission_ids[0]} 已暫時下架"
            if len(temp_submission_ids) == 1
            else f"關聯投稿：{_dependency_count(temporarily_takedown_submissions, '筆')}投稿已暫時下架"
            if temporarily_takedown_submissions
            else ""
        ),
    ]


async def _get_user_dependency_messages(db: SQLModelAsyncSession, user: User) -> list[str]:
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

    return [
        f"阻擋永久刪除：{_dependency_count(active_archives, '筆')}啟用中考古題仍屬於此使用者" if active_archives else "",
        f"一併永久刪除：{_dependency_count(trashed_archives, '筆')}已刪除考古題屬於此使用者" if trashed_archives else "",
        f"阻擋永久刪除：{_dependency_count(active_submissions, '筆')}啟用中投稿仍屬於此使用者" if active_submissions else "",
        f"一併永久刪除：{_dependency_count(trashed_submissions, '筆')}已刪除投稿屬於此使用者" if trashed_submissions else "",
    ]


async def _resolve_submission_linked_archive(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
) -> tuple[Optional[Archive], list[str]]:
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


async def _get_submission_dependency_messages(db: SQLModelAsyncSession, submission: ArchiveSubmission) -> list[str]:
    if submission.lifecycle_reason == LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED:
        return ["阻擋還原：關聯考古題已永久刪除"]

    if _is_course_trash_temporary_submission(submission):
        previous_status = get_course_trash_previous_status(submission.lifecycle_reason)
        return [
            "阻擋還原：請先還原原課程",
            f"隨課程復原：課程復原後回到{_format_submission_status_label(previous_status)}",
        ]

    linked_archive, fallback_warnings = await _resolve_submission_linked_archive(db, submission)
    if fallback_warnings or not linked_archive:
        return fallback_warnings

    linked_course = await db.get(Course, linked_archive.course_id) if linked_archive.course_id is not None else None
    linked_course_blocker = (
        "阻擋還原：原課程仍在垃圾桶"
        if linked_course is not None and linked_course.deleted_at is not None
        else ""
    )

    if linked_archive.deleted_at is not None:
        return [
            linked_course_blocker,
            "一併永久刪除：1 筆關聯考古題",
        ] if linked_course_blocker else ["一併永久刪除：1 筆關聯考古題"]

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

    return [
        *archive_status,
        f"一併永久刪除：{_dependency_count(linked_comments, '則')}留言將在關聯考古題永久刪除時一併刪除" if linked_comments else "",
        f"一併永久刪除：{_dependency_count(trashed_comments, '則')}已刪除留言將一併刪除" if trashed_comments else "",
        f"阻擋永久刪除：{_dependency_count(linked_other_submissions, '筆')}啟用中投稿仍連到關聯考古題" if linked_other_submissions else "",
        f"一併永久刪除：{_dependency_count(trashed_submissions, '筆')}已刪除投稿連到關聯考古題" if trashed_submissions else "",
    ]


def _build_trash_error(item_label: str, dependencies: list[str]) -> str:
    if not dependencies:
        return item_label
    if len(dependencies) == 1:
        return f"{item_label}: {dependencies[0]}"
    return f"{item_label}; blockers: {', '.join(dependencies)}"


def _is_submission_trashed(submission: ArchiveSubmission) -> bool:
    return is_archive_submission_trashed(submission)


def _blocker(item_type: str, item_id: int | None, name: str, status_value: str = "active") -> dict:
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
    reason: Optional[str] = None,
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
    except Exception:
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
    details: Optional[list[dict]] = None,
    warnings: Optional[list[str]] = None,
) -> dict:
    return {
        "success": True,
        "deleted": deleted,
        "deleted_count": deleted,
        "failed": 0,
        "failed_count": 0,
        "skipped": 0,
        "message": details[0].get("message") if details and details[0].get("message") else "永久刪除完成",
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


async def _get_active_course_blockers(db: SQLModelAsyncSession, category: CourseCategoryConfig) -> list[dict]:
    courses = (
        await db.execute(
            select(Course).where(
                Course.category == category.key,
                Course.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return [_blocker("course", course.id, course.name) for course in courses]


async def _get_active_archive_blockers(db: SQLModelAsyncSession, course: Course) -> list[dict]:
    archives = (
        await db.execute(
            select(Archive).where(
                Archive.course_id == course.id,
                Archive.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return [_blocker("archive", archive.id, archive.name) for archive in archives]


async def _get_active_category_submission_blockers(
    db: SQLModelAsyncSession,
    category: CourseCategoryConfig,
) -> list[dict]:
    course_submissions = (
        await db.execute(
            select(CourseSubmission).where(
                CourseSubmission.category == category.key,
                CourseSubmission.status != SubmissionStatus.DELETED,
            )
        )
    ).scalars().all()
    archive_submissions = (
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
    ).scalars().all()
    return [
        *[_blocker("course_submission", item.id, item.name, item.status.value) for item in course_submissions],
        *[
            _blocker("archive_submission", item.id, f"{item.subject} / {item.name}", item.status.value)
            for item in archive_submissions
        ],
    ]


async def _get_active_user_blockers(db: SQLModelAsyncSession, user: User) -> list[dict]:
    archives = (
        await db.execute(
            select(Archive).where(
                Archive.uploader_id == user.id,
                Archive.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    submissions = (
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
    ).scalars().all()
    return [
        *[_blocker("archive", item.id, item.name) for item in archives],
        *[
            _blocker("archive_submission", item.id, f"{item.subject} / {item.name}", item.status.value)
            for item in submissions
        ],
    ]


async def _remove_storage_object_if_unreferenced(
    db: SQLModelAsyncSession,
    object_name: Optional[str],
    warnings: list[str],
    *,
    exclude_archive_id: Optional[int] = None,
    exclude_submission_ids: Optional[list[int]] = None,
) -> int:
    if not object_name:
        return 0

    archive_query = select(func.count(Archive.id)).where(Archive.object_name == object_name)
    if exclude_archive_id is not None:
        archive_query = archive_query.where(Archive.id != exclude_archive_id)

    submission_query = select(func.count(ArchiveSubmission.id)).where(ArchiveSubmission.object_name == object_name)
    if exclude_submission_ids:
        submission_query = submission_query.where(~ArchiveSubmission.id.in_(exclude_submission_ids))

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
        live_submission_query = live_submission_query.where(~ArchiveSubmission.id.in_(exclude_submission_ids))
    live_refs = await _count_rows(db, live_archive_query) + await _count_rows(db, live_submission_query)
    all_refs = await _count_rows(db, archive_query) + await _count_rows(db, submission_query)
    trashed_refs = all_refs - live_refs

    if live_refs:
        warnings.append(f"Storage object kept because live records still reference it: {object_name}")
        return 0
    if trashed_refs:
        warnings.append(f"Storage object kept because trashed records still reference it: {object_name}")
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
        await db.execute(
            select(ArchiveDiscussionMessage).where(ArchiveDiscussionMessage.archive_id == archive.id)
        )
    ).scalars().all()
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
            [_blocker("archive_submission", submission.id, f"{submission.subject} / {submission.name}", submission.status.value)],
        )
    linked_archive = await db.get(Archive, submission.created_archive_id) if submission.created_archive_id else None
    if linked_archive and linked_archive.deleted_at is not None:
        return await _hard_delete_submission_archive_pair(db, submission, linked_archive, warnings)
    return await hard_delete_archive_submission_group(db, submission=submission, warnings=warnings)


async def _get_deleted_submission_parent_for_archive(
    db: SQLModelAsyncSession,
    archive_id: int | None,
) -> Optional[ArchiveSubmission]:
    if archive_id is None:
        return None
    return (
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
    ).scalars().first()


async def _hard_delete_submission_archive_pair(
    db: SQLModelAsyncSession,
    submission: ArchiveSubmission,
    archive: Archive,
    warnings: list[str],
) -> dict:
    timestamp = datetime.now(timezone.utc)
    linked_submissions = (
        await db.execute(
            select(ArchiveSubmission).where(ArchiveSubmission.created_archive_id == archive.id)
        )
    ).scalars().all()
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
    object_names = {item for item in [submission.object_name, archive.object_name] if item}
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
        await db.execute(
            select(ArchiveDiscussionMessage).where(ArchiveDiscussionMessage.archive_id == archive.id)
        )
    ).scalars().all()
    for message in messages:
        await db.delete(message)
    for item in submissions_to_delete:
        item.created_archive_id = None
        await db.delete(item)
    deleted_events = await delete_archive_submission_events(db, set(submission_ids))
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
            "submissionEvents": deleted_events,
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
        await db.execute(
            select(Archive).where(
                Archive.course_id == course.id,
                Archive.deleted_at.is_not(None),
            )
        )
    ).scalars().all()

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
        await db.execute(
            select(Course).where(Course.category == category.key)
        )
    ).scalars().all()
    if existing_courses:
        raise _blocked(
            f"阻擋永久刪除：{_dependency_count(len(existing_courses), '門')}課程仍屬於此分類，請先永久刪除課程",
            [_blocker("course", course.id, course.name) for course in existing_courses if course.id is not None],
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
        await db.execute(
            select(Archive).where(
                Archive.uploader_id == user.id,
                Archive.deleted_at.is_not(None),
            )
        )
    ).scalars().all()
    trashed_submissions = (
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
    ).scalars().all()

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


@router.get("", response_model=List[TrashItem])
async def list_trash_items(
    item_type: Optional[str] = Query(default=None),
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

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
            await db.execute(
                select(SystemIssueReport)
                .where(SystemIssueReport.deleted_at.is_not(None))
                .order_by(SystemIssueReport.deleted_at.desc())
            )
        ).scalars().all()
        for report in reports:
            reporter = users_by_id.get(report.reporter_user_id)
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.SYSTEM_ISSUE_REPORT,
                    item_id=report.id,
                    display_name=report.title,
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(users_by_id, report.deleted_by_id),
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
            await db.execute(
                select(CommentReport)
                .where(CommentReport.deleted_at.is_not(None))
                .order_by(CommentReport.deleted_at.desc())
            )
        ).scalars().all()
        for report in reports:
            items.append(
                _to_trash_item(
                    item_type=TrashEntityType.COMMENT_REPORT,
                    item_id=report.id,
                    display_name=COMMENT_REPORT_REASON_LABELS.get(report.reason, report.reason),
                    deleted_at=report.deleted_at,
                    deleted_by_id=report.deleted_by_id,
                    deleted_by_name=_format_deleted_by(users_by_id, report.deleted_by_id),
                    status=report.status,
                    reason=report.reason,
                    created_at=report.created_at,
                    reporter_name=_format_deleted_by(users_by_id, report.reporter_user_id),
                    comment_author_name=report.comment_author_name_snapshot,
                    comment_snapshot=report.comment_content_snapshot,
                    course_id=report.course_id,
                    course_name=report.course_name_snapshot,
                    archive_name=report.archive_name_snapshot,
                    dependencies=[],
                )
            )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE_REPORT):
        reports = (
            await db.execute(
                select(ArchiveReport)
                .where(ArchiveReport.deleted_at.is_not(None))
                .order_by(ArchiveReport.deleted_at.desc())
            )
        ).scalars().all()
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
            await db.execute(
                select(CourseCategoryConfig)
                .where(CourseCategoryConfig.deleted_at.is_not(None))
                .order_by(CourseCategoryConfig.deleted_at.desc())
            )
        ).scalars().all()
        for category in categories:
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.COURSE_CATEGORY,
                        item_id=category.id,
                        display_name=f"{category.name} ({category.key})",
                        deleted_at=category.deleted_at,
                        deleted_by_id=category.deleted_by_id,
                        deleted_by_name=_format_deleted_by(users_by_id, category.deleted_by_id),
                        status="deleted",
                        dependencies=await _get_category_dependency_messages(db, category),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed course category item (id=%s): %s",
                    getattr(category, "id", None),
                    exc,
                )

    if normalized_item_type in (None, TrashEntityType.COURSE):
        category_keys = {
            category_key
            for category_key in (
                await db.execute(select(Course.category).where(Course.deleted_at.is_not(None)))
            ).scalars()
            if category_key
        }
        course_categories = {}
        if category_keys:
            course_categories = {
                category.key: category
                for category in (
                    await db.execute(select(CourseCategoryConfig).where(CourseCategoryConfig.key.in_(category_keys)))
                ).scalars().all()
            }
        courses = (
            await db.execute(
                select(Course)
                .where(Course.deleted_at.is_not(None))
                .order_by(Course.deleted_at.desc())
            )
        ).scalars().all()
        for course in courses:
            category = course_categories.get(course.category)
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.COURSE,
                        item_id=course.id,
                        display_name=f"{course.name} ({course.category})",
                        deleted_at=course.deleted_at,
                        deleted_by_id=course.deleted_by_id,
                        deleted_by_name=_format_deleted_by(users_by_id, course.deleted_by_id),
                        status="deleted",
                        parent_type="course_category",
                        parent_id=category.id if category else None,
                        parent_name=category.name if category else course.category,
                        dependencies=await _get_course_dependency_messages(db, course),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed course item (id=%s): %s",
                    getattr(course, "id", None),
                    exc,
                )

    if normalized_item_type in (None, TrashEntityType.ARCHIVE):
        archive_course_ids = {
            archive_course_id
            for archive_course_id in (
                await db.execute(select(Archive.course_id).where(Archive.deleted_at.is_not(None)))
            ).scalars()
            if archive_course_id is not None
        }
        archive_courses = {}
        if archive_course_ids:
            archive_courses = {
                course.id: course
                for course in (
                    await db.execute(select(Course).where(Course.id.in_(archive_course_ids)))
                ).scalars().all()
            }
        archives = (
            await db.execute(
                select(Archive)
                .where(Archive.deleted_at.is_not(None))
                .order_by(Archive.deleted_at.desc())
            )
        ).scalars().all()
        archive_parent_submissions = {}
        archive_source_submissions = {}
        trashed_archive_ids = [archive.id for archive in archives if archive.id is not None]
        if trashed_archive_ids:
            linked_submissions = (
                await db.execute(
                    select(ArchiveSubmission).where(
                        ArchiveSubmission.created_archive_id.in_(trashed_archive_ids),
                    )
                    .order_by(
                        ArchiveSubmission.deleted_at.desc(),
                        ArchiveSubmission.reviewed_at.desc(),
                        ArchiveSubmission.created_at.desc(),
                    )
                )
            ).scalars().all()
            for submission in linked_submissions:
                if submission.created_archive_id is None:
                    continue
                archive_source_submissions.setdefault(submission.created_archive_id, submission)
                course_trash_parent_course = archive_courses.get(
                    get_course_trash_course_id(submission.lifecycle_reason)
                )
                if is_archive_submission_trashed(submission) or (
                    _is_course_trash_temporary_submission(submission)
                    and course_trash_parent_course is not None
                    and course_trash_parent_course.deleted_at is not None
                ):
                    archive_parent_submissions.setdefault(submission.created_archive_id, submission)
            course_trash_parent_course_ids = {
                course_id
                for submission in linked_submissions
                for course_id in (get_course_trash_course_id(submission.lifecycle_reason),)
                if course_id is not None and course_id not in archive_courses
            }
            if course_trash_parent_course_ids:
                archive_courses.update({
                    course.id: course
                    for course in (
                        await db.execute(select(Course).where(Course.id.in_(course_trash_parent_course_ids)))
                    ).scalars().all()
                    if course.id is not None
                })
        for archive in archives:
            parent_submission = archive_parent_submissions.get(archive.id)
            source_submission = parent_submission or archive_source_submissions.get(archive.id)
            course_trash_parent_course_id = (
                get_course_trash_course_id(source_submission.lifecycle_reason)
                if source_submission and is_course_trash_lifecycle_reason(source_submission.lifecycle_reason)
                else None
            )
            course = archive_courses.get(course_trash_parent_course_id or archive.course_id)
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
                        deleted_by_name=_format_deleted_by(users_by_id, archive.deleted_by_id),
                        status="deleted",
                        parent_type="archive_submission" if parent_submission else "course",
                        parent_id=parent_submission.id if parent_submission else archive.course_id,
                        parent_name=(
                            f"{parent_submission.subject} / {parent_submission.name}"
                            if parent_submission else course.name if course else None
                        ),
                        course_id=archive.course_id,
                        course_name=course.name if course else None,
                        source_submission_id=source_submission.id if source_submission else None,
                        dependencies=await _get_archive_dependency_messages(
                            db,
                            archive,
                            source_submission,
                            restore_parent_submission=parent_submission,
                        ),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed archive item (id=%s): %s",
                    getattr(archive, "id", None),
                    exc,
                )

    if normalized_item_type in (None, TrashEntityType.NOTIFICATION):
        notifications = (
            await db.execute(
                select(Notification)
                .where(Notification.deleted_at.is_not(None))
                .order_by(Notification.deleted_at.desc())
            )
        ).scalars().all()
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
                    "Failed to build trashed notification item (id=%s): %s",
                    getattr(notification, "id", None),
                    exc,
                )

    if normalized_item_type in (None, TrashEntityType.USER):
        users = (
            await db.execute(
                select(User).where(User.deleted_at.is_not(None)).order_by(User.deleted_at.desc())
            )
        ).scalars().all()
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
                        deleted_by_name=_format_deleted_by(users_by_id, user.deleted_by_id),
                        status="deleted",
                        dependencies=await _get_user_dependency_messages(db, user),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed user item (id=%s): %s",
                    getattr(user, "id", None),
                    exc,
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
            await db.execute(
                select(ArchiveSubmission)
                .where(
                    or_(
                        ArchiveSubmission.deleted_at.is_not(None),
                        func.lower(cast(ArchiveSubmission.status, String)) == SubmissionStatus.DELETED.value,
                        and_(
                            ArchiveSubmission.deleted_at.is_(None),
                            ArchiveSubmission.status == SubmissionStatus.TAKEDOWN,
                            is_course_trash_reason,
                        ),
                    )
                )
                .order_by(ArchiveSubmission.deleted_at.desc(), ArchiveSubmission.reviewed_at.desc(), ArchiveSubmission.created_at.desc())
            )
        ).scalars().all()
        archive_map = {}
        created_archive_ids = {
            submission.created_archive_id
            for submission in submissions
            if submission.created_archive_id is not None
        }
        if created_archive_ids:
            archive_rows = (
                await db.execute(
                    select(Archive).where(Archive.id.in_(created_archive_ids))
                )
            ).scalars().all()
            archive_map = {archive.id: archive for archive in archive_rows if archive.id is not None}

        submission_linked_archive_map: dict[int, Optional[Archive]] = {}
        for submission in submissions:
            is_course_trash_temporary = _is_course_trash_temporary_submission(submission)
            linked_archive = (
                archive_map.get(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            )
            if linked_archive is None and submission.id is not None and submission.id not in submission_linked_archive_map:
                linked_archive, _ = await _resolve_submission_linked_archive(db, submission)
                submission_linked_archive_map[submission.id] = linked_archive
            if linked_archive is None and submission.id is not None:
                linked_archive = submission_linked_archive_map[submission.id]
            linked_archive_id = linked_archive.id if linked_archive and linked_archive.id is not None else None
            linked_course = (
                await db.get(Course, linked_archive.course_id)
                if linked_archive and linked_archive.course_id is not None
                else None
            )
            course_trash_course_id = get_course_trash_course_id(submission.lifecycle_reason)
            course_trash_course = (
                await db.get(Course, course_trash_course_id)
                if is_course_trash_temporary and course_trash_course_id is not None
                else None
            )
            if is_course_trash_temporary and (not course_trash_course or course_trash_course.deleted_at is None):
                continue
            deleted_at = (
                submission.deleted_at
                or (course_trash_course.deleted_at if is_course_trash_temporary and course_trash_course else None)
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
                else linked_archive.name if linked_archive else None
            )
            try:
                items.append(
                    _to_trash_item(
                        item_type=TrashEntityType.ARCHIVE_SUBMISSION,
                        item_id=submission.id,
                        display_name=f"{submission.subject} / {submission.name}",
                        academic_year=submission.academic_year,
                        academic_term=_format_academic_term(submission.academic_year),
                        deleted_at=deleted_at,
                        deleted_by_id=submission.deleted_by_id,
                        deleted_by_name=_format_deleted_by(users_by_id, submission.deleted_by_id),
                        status=submission.status.value,
                        parent_type=parent_type,
                        parent_id=parent_id,
                        parent_name=parent_name,
                        created_archive_id=linked_archive_id,
                        source_submission_id=submission.id,
                        course_id=(
                            parent_course.id
                            if parent_course
                            else linked_archive.course_id if linked_archive else None
                        ),
                        course_name=(
                            parent_course.name
                            if parent_course
                            else linked_course.name if linked_course else submission.requested_course_name
                        ),
                        can_restore=False if is_course_trash_temporary else None,
                        can_permanent_delete=False if is_course_trash_temporary else None,
                        dependencies=await _get_submission_dependency_messages(db, submission),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build trashed archive submission item (id=%s): %s",
                    getattr(submission, "id", None),
                    exc,
                )

    return sorted(_dedupe_trash_items(items), key=lambda item: item.deleted_at, reverse=True)


@router.post("/restore")
async def restore_trash_item(
    payload: TrashActionRequest,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    now = datetime.now(timezone.utc)

    if payload.item_type == TrashEntityType.SYSTEM_ISSUE_REPORT:
        report = await db.get(SystemIssueReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System issue report not found",
            )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "系統問題回報已還原"}

    if payload.item_type == TrashEntityType.COMMENT_REPORT:
        report = await db.get(CommentReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment report not found",
            )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "留言回報已還原"}

    if payload.item_type == TrashEntityType.ARCHIVE_REPORT:
        report = await db.get(ArchiveReport, payload.item_id)
        if not report or report.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Archive report not found",
            )
        report.deleted_at = None
        report.deleted_by_id = None
        await db.commit()
        return {"message": "考古題回報已還原"}

    if payload.item_type == TrashEntityType.COURSE_CATEGORY:
        category = await db.get(CourseCategoryConfig, payload.item_id)
        if not category or category.deleted_at is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

        category.deleted_at = None
        category.restored_at = now
        category.restored_by_id = current_user.user_id
        category.deleted_by_id = None
        category.is_active = True
        await db.commit()
        return {
            "message": "已復原分類「" + category.name + "」，課程不會自動復原，若需要請另外復原課程。",
            "restoredCourses": 0,
        }

    if payload.item_type == TrashEntityType.COURSE:
        course = await db.get(Course, payload.item_id)
        if not course or course.deleted_at is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        category = (
            await db.execute(
                select(CourseCategoryConfig).where(CourseCategoryConfig.key == course.category)
            )
        ).scalar_one_or_none()
        if not category or category.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Category is deleted; restore category before restoring this course.",
            )

        course.deleted_at = None
        course.deleted_by_id = None
        course.restored_at = now
        course.restored_by_id = current_user.user_id

        course_id_pattern = f"course_id={course.id}"
        course_trashed_submission_archive_ids = {
            archive_id
            for archive_id in (
                await db.execute(
                    select(ArchiveSubmission.created_archive_id).where(
                        ArchiveSubmission.deleted_at.is_(None),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                        ArchiveSubmission.created_archive_id.is_not(None),
                        or_(
                            ArchiveSubmission.lifecycle_reason.like(f"%|{course_id_pattern}|%"),
                            ArchiveSubmission.lifecycle_reason.like(f"%|{course_id_pattern}"),
                        ),
                    )
                )
            ).scalars()
            if archive_id is not None
        }
        archive_restore_conditions = [Archive.course_id == course.id]
        if course_trashed_submission_archive_ids:
            archive_restore_conditions.append(Archive.id.in_(course_trashed_submission_archive_ids))

        archives = (
            await db.execute(
                select(Archive).where(
                    or_(*archive_restore_conditions),
                    Archive.deleted_at.is_not(None),
                )
            )
        ).scalars().all()
        restored_archives_count = 0
        skipped_submission_archive_count = 0
        restored_archive_ids = []
        for archive in archives:
            parent_submission = await _get_deleted_submission_parent_for_archive(db, archive.id)
            if parent_submission:
                skipped_submission_archive_count += 1
                continue

            archive.deleted_at = None
            archive.deleted_by_id = None
            archive.deleted_reason = None
            archive.restored_at = now
            archive.restored_by_id = current_user.user_id
            restored_archives_count += 1
            if archive.id is not None:
                restored_archive_ids.append(archive.id)

        restored_submission_count = 0
        skipped_submission_count = 0
        course_submission_match_conditions = _build_course_trash_submission_match_conditions(
            course.name, course.category
        )
        all_submission_match_conditions = []
        if restored_archive_ids:
            all_submission_match_conditions.append(ArchiveSubmission.created_archive_id.in_(restored_archive_ids))
        all_submission_match_conditions.extend(course_submission_match_conditions)

        if all_submission_match_conditions:
            submissions = (
                await db.execute(
                    select(ArchiveSubmission).where(
                        ArchiveSubmission.deleted_at.is_(None),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                        or_(*all_submission_match_conditions),
                        or_(
                            ArchiveSubmission.lifecycle_reason == LIFECYCLE_COURSE_TRASHED,
                            ArchiveSubmission.lifecycle_reason.like(f"{LIFECYCLE_COURSE_TRASHED}|%"),
                            ArchiveSubmission.lifecycle_reason.like(f"%|{course_id_pattern}|%"),
                            ArchiveSubmission.lifecycle_reason.like(f"%|{course_id_pattern}"),
                        ),
                    )
                )
            ).scalars().all()
            for submission in submissions:
                previous_status = get_course_trash_previous_status(submission.lifecycle_reason)
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
            message += (
                f"{skipped_submission_count} 筆投稿因缺少原本狀態仍維持已下架。"
            )
        if skipped_submission_archive_count:
            message += (
                f"另有 {skipped_submission_archive_count} 筆考古題仍屬於已刪除投稿，需還原投稿後才會復原。"
            )
        return {
            "message": message,
            "restoredArchivesCount": restored_archives_count,
            "restoredSubmissionsCount": restored_submission_count,
            "skippedSubmissionsCount": skipped_submission_count,
            "skippedSubmissionArchiveCount": skipped_submission_archive_count,
        }

    if payload.item_type == TrashEntityType.NOTIFICATION:
        notification = await db.get(Notification, payload.item_id)
        if not notification or notification.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
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
        user = await db.get(User, payload.item_id)
        if not user or user.deleted_at is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported trash item type")


@router.delete("/bulk")
async def bulk_permanently_delete_trash_items(
    item_type: Optional[TrashEntityType] = Query(default=None),
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    items = await list_trash_items(item_type=item_type, current_user=current_user, db=db)
    delete_order = {
        TrashEntityType.ARCHIVE_SUBMISSION: 0,
        TrashEntityType.ARCHIVE: 1,
        TrashEntityType.COURSE: 2,
        TrashEntityType.COURSE_CATEGORY: 3,
        TrashEntityType.NOTIFICATION: 4,
        TrashEntityType.USER: 5,
        TrashEntityType.SYSTEM_ISSUE_REPORT: 6,
        TrashEntityType.COMMENT_REPORT: 7,
        TrashEntityType.ARCHIVE_REPORT: 8,
    }
    sorted_items = sorted(
        items,
        key=lambda item: delete_order.get(TrashEntityType(item.item_type), 99),
    )
    details: list[dict] = []
    failures: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []
    deleted_count = 0

    for item in sorted_items:
        trash_type = TrashEntityType(item.item_type)
        try:
            result = await _permanently_delete_trash_item(
                item_type=trash_type,
                item_id=item.id,
                db=db,
                warnings=warnings,
            )
            await db.commit()
            details.extend(result.get("details", []))
            deleted_count += int(result.get("deleted", result.get("deleted_count", 0)) or 0)
        except HTTPException as error:
            await db.rollback()
            if error.status_code == status.HTTP_404_NOT_FOUND:
                skipped.append({"item_type": trash_type.value, "id": item.id, "display_name": item.display_name})
                continue
            detail = error.detail if isinstance(error.detail, dict) else {"message": error.detail}
            failures.append(
                {
                    "type": trash_type.value,
                    "id": item.id,
                    "name": item.display_name,
                    "reason": detail.get("message", error.detail),
                    "blockingDependencies": detail.get("blockingDependencies", []),
                }
            )
        except Exception:
            await db.rollback()
            failures.append(
                {
                    "type": trash_type.value,
                    "id": item.id,
                    "name": item.display_name,
                    "reason": "永久刪除失敗，請稍後再試或查看伺服器日誌。",
                    "blockingDependencies": [],
                }
            )

    return {
        "success": True,
        "scope": item_type.value if item_type else "all",
        "deleted": deleted_count,
        "deleted_count": deleted_count,
        "failed": len(failures),
        "failed_count": len(failures),
        "skipped": len(skipped),
        "message": (
            "部分項目因仍有未刪除的依賴資料而無法永久刪除"
            if failures
            else "永久刪除完成"
        ),
        "details": details,
        "failures": failures,
        "skipped_items": skipped,
        "warnings": warnings,
    }


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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

        detail = await _hard_delete_category(db, category, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=category.name,
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    if item_type == TrashEntityType.COURSE:
        course = await db.get(Course, item_id)
        if not course or course.deleted_at is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found")

        parent_submission = await _get_deleted_submission_parent_for_archive(db, archive.id)
        detail = (
            await _hard_delete_submission_archive_pair(db, parent_submission, archive, warnings)
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

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
            submission.deleted_at is None and submission.status != SubmissionStatus.DELETED
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

        detail = await _hard_delete_submission(db, submission, warnings)
        return _delete_result(
            item_type=item_type,
            item_id=item_id,
            name=f"{submission.subject} / {submission.name}",
            deleted=detail.get("deleted", 1),
            details=[detail],
            warnings=warnings,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported trash item type")


@router.delete("/{item_type}/{item_id}")
async def permanently_delete_trash_item(
    item_type: TrashEntityType,
    item_id: int,
    current_user=Depends(get_current_user),
    db: SQLModelAsyncSession = Depends(get_session),
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    warnings: list[str] = []
    try:
        result = await _permanently_delete_trash_item(
            item_type=item_type,
            item_id=item_id,
            db=db,
            warnings=warnings,
        )
        await db.commit()
        return result
    except HTTPException:
        await db.rollback()
        raise
    except Exception as error:
        await db.rollback()
        logger.exception("Failed to permanently delete trash item %s/%s", item_type, item_id)
        error_text = str(error)
        message = "永久刪除失敗，請稍後再試或查看伺服器日誌。"
        if "archive_discussion_messages" in error_text:
            message = "永久刪除失敗：仍有考古題留言引用此考古題，請查看伺服器日誌。"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "deleted": 0,
                "failed": 1,
                "message": message,
                "blockingDependencies": [],
                "warnings": warnings,
            },
        )
