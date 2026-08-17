import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from sqlalchemy import and_, delete, exists, func, or_
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.archive_submission_lifecycle import (
    archive_lifecycle_conflict_error,
    course_lifecycle_conflict_error,
    is_course_trash_lifecycle_reason,
    make_course_trash_lifecycle_reason,
    soft_delete_archive_with_submission_takedown,
)
from app.core.config import settings
from app.db.course_categories import (
    DEFAULT_COURSE_CATEGORY_DEFINITIONS,
    LEGACY_COURSE_CATEGORY_ALIASES,
    RESERVED_LEGACY_COURSE_CATEGORY_KEYS,
    canonicalize_course_category_key,
    normalize_course_category_key,
    normalize_course_category_name,
)
from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveDiscussionLike,
    ArchiveDiscussionMessage,
    ArchiveDiscussionMessageRead,
    ArchiveRead,
    ArchiveSubmission,
    ArchiveType,
    ArchiveUpdateCourse,
    Course,
    CourseCategoryConfig,
    CourseCategoryCreate,
    CourseCategoryRead,
    CourseCategoryReorder,
    CourseCategoryUpdate,
    CourseCreate,
    CourseInfo,
    CourseRead,
    CourseReorder,
    CourseSubmission,
    CourseSubmissionCreate,
    CourseSubmissionRead,
    CourseSubmissionUpdate,
    CourseUpdate,
    PersonalNotificationType,
    PublicArchiveRead,
    SubmissionDecision,
    SubmissionStatus,
    User,
    UserRoles,
)
from app.services import archive_lifecycle_locks, course_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    LifecyclePlanRetryExhausted,
    LockedLifecycleRows,
    PlanRebuildBudget,
)
from app.services.archive_mutation import (
    ArchiveMutationLifecycleConflict,
    acquire_stable_archive_mutation_locks,
    archive_move_target_not_found_error,
    archive_move_target_trashed_error,
    resolve_archive_move_target,
)
from app.services.archive_submission_links import (
    validate_archive_source_submission_rows,
)
from app.services.course_lifecycle_locks import CourseLifecycleOperation
from app.services.discussions import soft_delete_discussion_message
from app.services.personal_notifications import enqueue_personal_notification
from app.utils.auth import get_current_user
from app.utils.auth_ws import get_ws_token_payload
from app.utils.course_text import (
    format_course_display_name,
    normalize_course_search_text,
    normalized_course_text_expr,
)
from app.utils.exception_logging import redacted_exc_info
from app.utils.storage import get_minio_client, presigned_get_url

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory connection registry (single-process broadcast).
_discussion_connections_by_archive: dict[int, set[WebSocket]] = {}
DISCUSSION_MESSAGE_MAX_LENGTH = 200
ARCHIVE_FILE_MISSING_DETAIL = {
    "code": "archive_file_missing",
    "message": "此筆考古題的 PDF 檔案缺失，無法預覽或下載。",
}
DEFAULT_CATEGORIES = [
    (category.key, category.name, category.label, category.icon)
    for category in DEFAULT_COURSE_CATEGORY_DEFINITIONS
]
DEFAULT_CATEGORY_ORDER = {
    item[0]: index for index, item in enumerate(DEFAULT_CATEGORIES)
}
DEFAULT_CATEGORY_BADGE_COLOR = "slate"
CATEGORY_BADGE_COLOR_TOKENS = {
    "navy",
    "teal",
    "forest",
    "amber",
    "burgundy",
    "violet",
    "slate",
    "indigo",
}
CATEGORY_BADGE_COLOR_ALIASES = {
    "blue": "navy",
    "green": "forest",
    "purple": "violet",
    "rose": "burgundy",
    "gray": "slate",
}
DEFAULT_CATEGORY_BADGE_COLORS = {
    category.key: category.badge_color
    for category in DEFAULT_COURSE_CATEGORY_DEFINITIONS
}
LEGACY_CATEGORY_ALIASES = LEGACY_COURSE_CATEGORY_ALIASES


class CategorizedCourses(dict):
    def model_dump(self):
        return {
            category: [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in courses
            ]
            for category, courses in self.items()
        }


def _course_category_value(course: Course) -> str:
    return getattr(course.category, "value", course.category)


def _course_sort_key(
    course: Course, category_order: dict[str, int] | None = None
) -> tuple[int, int, int]:
    order = category_order or DEFAULT_CATEGORY_ORDER
    category = _course_category_value(course)
    return (
        order.get(category, 999),
        course.order_index,
        course.id or 0,
    )


def _visible_courses(
    courses: list[Course], category_order: dict[str, int] | None = None
) -> list[Course]:
    seen: set[tuple[str, str]] = set()
    selected: list[Course] = []
    allowed_categories = set((category_order or DEFAULT_CATEGORY_ORDER).keys())
    for course in sorted(
        courses, key=lambda item: _course_sort_key(item, category_order)
    ):
        category = _course_category_value(course)
        if category not in allowed_categories:
            continue
        key = (category, normalize_course_search_text(course.name))
        if key in seen:
            continue
        seen.add(key)
        selected.append(course)
    return selected


def _normalize_category_badge_color(color: str | None) -> str:
    normalized = (color or DEFAULT_CATEGORY_BADGE_COLOR).strip().lower()
    if not normalized:
        return DEFAULT_CATEGORY_BADGE_COLOR
    normalized = CATEGORY_BADGE_COLOR_ALIASES.get(normalized, normalized)
    if normalized not in CATEGORY_BADGE_COLOR_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category badge color",
        )
    return normalized


def _public_archive_conditions(
    course_id: int | None = None, archive_id: int | None = None
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


def _public_catalog_course_conditions() -> list:
    active_category_exists = exists().where(
        CourseCategoryConfig.key == Course.category,
        CourseCategoryConfig.is_active.is_(True),
        CourseCategoryConfig.deleted_at.is_(None),
    )
    return [
        Course.deleted_at.is_(None),
        active_category_exists,
    ]


async def _category_order_map(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(CourseCategoryConfig)
        .where(CourseCategoryConfig.is_active.is_(True))
        .order_by(CourseCategoryConfig.order_index, CourseCategoryConfig.id)
    )
    categories = result.scalars().all()
    if not categories:
        return DEFAULT_CATEGORY_ORDER.copy()
    return {category.key: index for index, category in enumerate(categories)}


async def _admin_category_order_map(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(CourseCategoryConfig)
        .where(CourseCategoryConfig.deleted_at.is_(None))
        .order_by(CourseCategoryConfig.order_index, CourseCategoryConfig.id)
    )
    categories = result.scalars().all()
    if not categories:
        return DEFAULT_CATEGORY_ORDER.copy()
    return {category.key: index for index, category in enumerate(categories)}


async def _ensure_category(db: AsyncSession, category_key: str) -> CourseCategoryConfig:
    category_key = canonicalize_course_category_key(category_key)
    result = await db.execute(
        select(CourseCategoryConfig).where(
            CourseCategoryConfig.key == category_key,
        )
    )
    category = result.scalar_one_or_none()
    if category and category.deleted_at is None and category.is_active:
        return category
    if category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course category is not available",
        )
    if category_key in DEFAULT_CATEGORY_ORDER:
        return CourseCategoryConfig(
            key=category_key,
            name=category_key,
            label=category_key,
            badge_color=DEFAULT_CATEGORY_BADGE_COLORS.get(
                category_key,
                DEFAULT_CATEGORY_BADGE_COLOR,
            ),
            order_index=DEFAULT_CATEGORY_ORDER[category_key],
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Course category does not exist"
    )


def _validated_admin_category_key(value: str) -> str:
    key = normalize_course_category_key(value)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category key is required",
        )
    if key in RESERVED_LEGACY_COURSE_CATEGORY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy category keys are reserved",
        )
    return key


async def _ensure_unique_category_name(
    db: AsyncSession,
    value: str,
    *,
    exclude_category_id: int | None = None,
) -> str:
    name = value.strip()
    normalized_name = normalize_course_category_name(name)
    if not normalized_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name is required",
        )
    query = select(CourseCategoryConfig).where(
        func.lower(func.trim(CourseCategoryConfig.name)) == normalized_name
    )
    if exclude_category_id is not None:
        query = query.where(CourseCategoryConfig.id != exclude_category_id)
    if (await db.execute(query)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name already exists",
        )
    return name


async def _next_order_index(db: AsyncSession, category) -> int:
    result = await db.execute(
        select(func.max(Course.order_index)).where(
            Course.category == category,
            Course.deleted_at.is_(None),
        )
    )
    current_max = result.scalar()
    return 0 if current_max is None else int(current_max) + 1


COURSE_SUBMISSION_APPROVAL_IDENTITY_CONFLICT = {
    "code": "course_submission_approval_identity_conflict",
    "message": "Course request identity changed; reload and retry.",
    "reload_required": True,
}
COURSE_SUBMISSION_APPROVAL_RESULT_CONFLICT = {
    "code": "course_submission_approval_result_conflict",
    "message": "Approved course request has an inconsistent result.",
    "reload_required": False,
}
COURSE_SUBMISSION_COURSE_IDENTITY_CONFLICT = {
    "code": "course_submission_course_identity_conflict",
    "message": "Course identity is ambiguous.",
    "reload_required": False,
}


def _course_submission_identity(submission: CourseSubmission) -> tuple[str, str]:
    return (
        canonicalize_course_category_key(submission.category),
        normalize_course_search_text(submission.name),
    )


async def _live_courses_for_submission_identity(
    db: AsyncSession,
    *,
    category_key: str,
    normalized_course_name: str,
) -> list[Course]:
    return list(
        (
            await db.execute(
                select(Course)
                .where(
                    normalized_course_text_expr(Course.name) == normalized_course_name,
                    Course.category == category_key,
                    Course.deleted_at.is_(None),
                )
                .order_by(Course.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def _coherent_approved_course_submission(
    db: AsyncSession,
    submission: CourseSubmission,
    *,
    expected_category_key: str,
    expected_normalized_course_name: str,
) -> CourseSubmissionRead | None:
    if (
        submission.created_course_id is None
        or submission.reviewer_id is None
        or submission.reviewed_at is None
    ):
        return None
    course = await db.get(Course, submission.created_course_id)
    if course is None:
        return None
    course_category = canonicalize_course_category_key(_course_category_value(course))
    if (
        course_category != expected_category_key
        or normalize_course_search_text(course.name) != expected_normalized_course_name
    ):
        return None
    return CourseSubmissionRead.model_validate(submission)


def _discussion_public_display_name(
    *, user_id: int, nickname: str | None, name: str | None
) -> str:
    nickname_norm = (nickname or "").strip()
    if nickname_norm:
        return nickname_norm
    return (name or "").strip()


async def _list_course_categories_data(db: AsyncSession) -> list[CourseCategoryRead]:
    result = await db.execute(
        select(CourseCategoryConfig)
        .where(
            CourseCategoryConfig.is_active.is_(True),
            CourseCategoryConfig.deleted_at.is_(None),
        )
        .order_by(CourseCategoryConfig.order_index, CourseCategoryConfig.id)
    )
    categories = result.scalars().all()
    if categories:
        return categories
    return [
        CourseCategoryRead(
            id=index + 1,
            key=category.key,
            name=category.name,
            name_en=category.name_en,
            label=category.label,
            label_en=category.label_en,
            icon=category.icon,
            badge_color=category.badge_color,
            order_index=category.order_index,
            is_active=True,
        )
        for index, category in enumerate(DEFAULT_COURSE_CATEGORY_DEFINITIONS)
    ]


@router.get("/categories", response_model=list[CourseCategoryRead])
async def list_course_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await _list_course_categories_data(db)


@router.get("/public/categories", response_model=list[CourseCategoryRead])
async def list_public_course_categories(db: AsyncSession = Depends(get_session)):
    return await _list_course_categories_data(db)


async def _get_categorized_courses_data(
    db: AsyncSession, *, public_only: bool, search: str | None = None
) -> CategorizedCourses:
    query = select(Course)
    if public_only:
        query = query.where(*_public_catalog_course_conditions())
    else:
        query = query.where(Course.deleted_at.is_(None))
    normalized_search = normalize_course_search_text(search)
    if normalized_search:
        query = query.where(
            or_(
                normalized_course_text_expr(Course.name).contains(normalized_search),
                normalized_course_text_expr(Course.name_en).contains(normalized_search),
            )
        )
    result = await db.execute(query)
    category_order = await _category_order_map(db)
    courses = _visible_courses(result.scalars().all(), category_order)

    categorized_courses = CategorizedCourses(
        {category: [] for category in category_order}
    )
    for course in courses:
        course_info = CourseInfo(
            id=course.id,
            name=format_course_display_name(course.name),
            name_en=(course.name_en or "").strip() or None,
            order_index=course.order_index,
        )
        categorized_courses.setdefault(_course_category_value(course), []).append(
            course_info
        )

    if not public_only:
        for legacy_key, canonical_key in LEGACY_CATEGORY_ALIASES.items():
            if canonical_key in categorized_courses:
                categorized_courses[legacy_key] = categorized_courses[canonical_key]

    return categorized_courses


@router.get("", response_model=dict[str, list[CourseInfo]])
async def get_categorized_courses(
    search: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Return the authenticated application course catalog."""
    return await _get_categorized_courses_data(db, public_only=False, search=search)


@router.get("/public", response_model=dict[str, list[CourseInfo]])
async def get_public_categorized_courses(
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    """Return canonical active courses for anonymous human discovery."""
    return await _get_categorized_courses_data(db, public_only=True, search=search)


@router.get("/public/{course_id}/archives", response_model=list[PublicArchiveRead])
async def get_public_course_archives(
    course_id: int,
    db: AsyncSession = Depends(get_session),
):
    course = (
        await db.execute(
            select(Course).where(
                Course.id == course_id,
                *_public_catalog_course_conditions(),
            )
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    archives = (
        (
            await db.execute(
                select(Archive)
                .where(*_public_archive_conditions(course_id=course_id))
                .order_by(
                    Archive.academic_year.desc(),
                    Archive.archive_type.asc(),
                    Archive.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [PublicArchiveRead.model_validate(archive) for archive in archives]


@router.post("/requests", response_model=CourseSubmissionRead)
async def create_course_request(
    course_data: CourseSubmissionCreate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    normalized_category = canonicalize_course_category_key(course_data.category)
    normalized_name = normalize_course_search_text(course_data.name)
    formatted_name = format_course_display_name(course_data.name)

    if current_user.is_admin:
        try:
            await archive_lifecycle_locks.acquire_approval_namespace_mutex(
                db,
                category_key=normalized_category,
                course_name=normalized_name,
            )
            await _ensure_category(db, normalized_category)
            existing_courses = await _live_courses_for_submission_identity(
                db,
                category_key=normalized_category,
                normalized_course_name=normalized_name,
            )
            if existing_courses:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Course already exists",
                )
            existing_pending = (
                await db.execute(
                    select(CourseSubmission).where(
                        normalized_course_text_expr(CourseSubmission.name)
                        == normalized_name,
                        CourseSubmission.category == normalized_category,
                        CourseSubmission.status == SubmissionStatus.PENDING,
                    )
                )
            ).scalar_one_or_none()
            if existing_pending:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Course request already pending",
                )

            course = Course(
                name=formatted_name,
                category=normalized_category,
                order_index=await _next_order_index(db, normalized_category),
            )
            db.add(course)
            await db.flush()
            submission = CourseSubmission(
                name=course.name,
                category=course.category,
                requester_id=current_user.user_id,
                reviewer_id=current_user.user_id,
                status=SubmissionStatus.APPROVED,
                created_course_id=course.id,
                reviewed_at=datetime.now(UTC),
            )
            db.add(submission)
            await db.commit()
            return submission
        except Exception:
            await db.rollback()
            raise

    await _ensure_category(db, normalized_category)
    existing_courses = await _live_courses_for_submission_identity(
        db,
        category_key=normalized_category,
        normalized_course_name=normalized_name,
    )
    if existing_courses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course already exists",
        )
    existing_pending = (
        await db.execute(
            select(CourseSubmission).where(
                normalized_course_text_expr(CourseSubmission.name) == normalized_name,
                CourseSubmission.category == normalized_category,
                CourseSubmission.status == SubmissionStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if existing_pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course request already pending",
        )

    submission = CourseSubmission(
        name=formatted_name,
        category=normalized_category,
        requester_id=current_user.user_id,
    )

    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return submission


@router.get("/requests/me", response_model=list[CourseSubmissionRead])
async def list_my_course_requests(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(
        select(CourseSubmission)
        .where(CourseSubmission.requester_id == current_user.user_id)
        .order_by(CourseSubmission.created_at.desc())
    )
    return result.scalars().all()


@router.get("/admin/requests", response_model=list[CourseSubmissionRead])
async def list_course_requests_for_admin(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    result = await db.execute(
        select(CourseSubmission).order_by(
            CourseSubmission.status.asc(),
            CourseSubmission.created_at.desc(),
        )
    )
    return result.scalars().all()


@router.put("/admin/requests/{request_id}", response_model=CourseSubmissionRead)
async def update_course_request_for_admin(
    request_id: int,
    request_data: CourseSubmissionUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    submission = await db.get(CourseSubmission, request_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    if submission.status != SubmissionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request already reviewed"
        )

    if request_data.name is not None:
        submission.name = format_course_display_name(request_data.name)
    if request_data.category is not None:
        category = await _ensure_category(db, request_data.category)
        submission.category = category.key

    await db.commit()
    await db.refresh(submission)
    return submission


@router.post(
    "/admin/requests/{request_id}/approve", response_model=CourseSubmissionRead
)
async def approve_course_request(
    request_id: int,
    decision: SubmissionDecision | None = None,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    discovered_submission = (
        await db.execute(
            select(CourseSubmission).where(CourseSubmission.id == request_id)
        )
    ).scalar_one_or_none()
    if not discovered_submission:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    discovered_identity = _course_submission_identity(discovered_submission)

    try:
        await archive_lifecycle_locks.acquire_approval_namespace_mutex(
            db,
            category_key=discovered_identity[0],
            course_name=discovered_identity[1],
        )
        submission = (
            await db.execute(
                select(CourseSubmission)
                .where(CourseSubmission.id == request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if submission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            )

        locked_identity = _course_submission_identity(submission)
        if locked_identity != discovered_identity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=COURSE_SUBMISSION_APPROVAL_IDENTITY_CONFLICT,
            )

        if submission.status == SubmissionStatus.APPROVED:
            approved_result = await _coherent_approved_course_submission(
                db,
                submission,
                expected_category_key=locked_identity[0],
                expected_normalized_course_name=locked_identity[1],
            )
            if approved_result is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=COURSE_SUBMISSION_APPROVAL_RESULT_CONFLICT,
                )
            await db.rollback()
            return approved_result
        if submission.status != SubmissionStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request already reviewed",
            )

        await _ensure_category(db, locked_identity[0])
        matching_courses = await _live_courses_for_submission_identity(
            db,
            category_key=locked_identity[0],
            normalized_course_name=locked_identity[1],
        )
        if len(matching_courses) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=COURSE_SUBMISSION_COURSE_IDENTITY_CONFLICT,
            )
        if matching_courses:
            course = matching_courses[0]
        else:
            course = Course(
                name=format_course_display_name(submission.name),
                category=locked_identity[0],
                order_index=await _next_order_index(db, locked_identity[0]),
            )
            db.add(course)
            await db.flush()

        submission.status = SubmissionStatus.APPROVED
        submission.reviewer_id = current_user.user_id
        submission.review_note = decision.note if decision else None
        submission.created_course_id = course.id
        submission.reviewed_at = datetime.now(UTC)
        await db.commit()
        return submission
    except Exception:
        await db.rollback()
        raise


@router.post("/admin/requests/{request_id}/reject", response_model=CourseSubmissionRead)
async def reject_course_request(
    request_id: int,
    decision: SubmissionDecision | None = None,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    submission = await db.get(CourseSubmission, request_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    if submission.status != SubmissionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request already reviewed"
        )

    submission.status = SubmissionStatus.REJECTED
    submission.reviewer_id = current_user.user_id
    submission.review_note = decision.note if decision else None
    submission.reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(submission)
    return submission


@router.get("/{course_id}/archives", response_model=list[ArchiveRead])
async def get_course_archives(
    course_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Get all archives for a specific course.
    """
    course_query = select(Course).where(
        Course.id == course_id, Course.deleted_at.is_(None)
    )
    result = await db.execute(course_query)
    course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course with id {course_id} not found",
        )

    query = (
        select(Archive)
        .where(*_public_archive_conditions(course_id=course_id))
        .order_by(Archive.created_at.desc())
    )
    result = await db.execute(query)
    archives = result.scalars().all()

    source_submission_ids_by_archive: dict[int, list[int]] = {}
    archive_ids = [archive.id for archive in archives if archive.id is not None]
    if archive_ids:
        submission_visibility_conditions = [
            ArchiveSubmission.created_archive_id.in_(archive_ids),
            ArchiveSubmission.deleted_at.is_(None),
            ArchiveSubmission.status != SubmissionStatus.DELETED,
        ]
        linked_submissions = (
            await db.execute(
                select(
                    ArchiveSubmission.id,
                    ArchiveSubmission.created_archive_id,
                    ArchiveSubmission.requester_id,
                ).where(*submission_visibility_conditions)
            )
        ).all()
        validated_sources = validate_archive_source_submission_rows(
            [
                (created_archive_id, submission_id)
                for submission_id, created_archive_id, _requester_id in linked_submissions
            ],
            operation="source_lookup",
        )
        for submission_id, created_archive_id, requester_id in linked_submissions:
            if created_archive_id in validated_sources and (
                current_user.is_admin or requester_id == current_user.user_id
            ):
                source_submission_ids_by_archive[created_archive_id] = (
                    validated_sources[created_archive_id]
                )

    return [
        ArchiveRead.model_validate(archive).model_copy(
            update={
                "source_submission_ids": source_submission_ids_by_archive.get(
                    archive.id, []
                )
            }
        )
        for archive in archives
    ]


@router.get("/{course_id}/archives/{archive_id}/preview")
async def get_archive_preview_url(
    course_id: int,
    archive_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Get presigned URL for previewing an archive (30 minutes expiry)
    """
    query = select(Archive).where(
        *_public_archive_conditions(course_id=course_id, archive_id=archive_id)
    )
    result = await db.execute(query)
    archive = result.scalar_one_or_none()

    if not archive:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )

    try:
        get_minio_client().stat_object(
            settings.MINIO_BUCKET_NAME,
            archive.object_name,
        )
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ARCHIVE_FILE_MISSING_DETAIL,
            ) from exc
        raise

    return {
        "url": presigned_get_url(archive.object_name, expires=timedelta(minutes=30))
    }


@router.get("/{course_id}/archives/{archive_id}/preview-file")
async def get_archive_preview_file(
    course_id: int,
    archive_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Stream PDF through the API origin for browser preview. This avoids MinIO/CORS
    edge cases in PDF.js while keeping the normal download endpoint unchanged.
    """
    query = select(Archive).where(
        *_public_archive_conditions(course_id=course_id, archive_id=archive_id)
    )
    result = await db.execute(query)
    archive = result.scalar_one_or_none()

    if not archive:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )

    try:
        response = get_minio_client().get_object(
            settings.MINIO_BUCKET_NAME,
            archive.object_name,
        )
        data = response.read()
        response.close()
        response.release_conn()
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ARCHIVE_FILE_MISSING_DETAIL,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load preview file from object storage",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load preview file from object storage",
        ) from exc

    return StreamingResponse(
        iter([data]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{archive.name}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{course_id}/archives/{archive_id}/download")
async def get_archive_download_url(
    course_id: int,
    archive_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Get presigned URL for downloading an archive (1 hour expiry)
    This endpoint increments the download coun
    """
    query = select(Archive).where(
        *_public_archive_conditions(course_id=course_id, archive_id=archive_id)
    )
    result = await db.execute(query)
    archive = result.scalar_one_or_none()

    if not archive:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )

    try:
        get_minio_client().stat_object(
            settings.MINIO_BUCKET_NAME,
            archive.object_name,
        )
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ARCHIVE_FILE_MISSING_DETAIL,
            ) from exc
        raise

    archive.download_count += 1
    await db.commit()
    await db.refresh(archive)

    return {"url": presigned_get_url(archive.object_name, expires=timedelta(hours=1))}


async def _ensure_archive_exists_for_discussion(
    course_id: int, archive_id: int, db: AsyncSession
) -> Archive:
    query = select(Archive).where(
        *_public_archive_conditions(course_id=course_id, archive_id=archive_id)
    )
    archive = (await db.execute(query)).scalar_one_or_none()
    if not archive:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )
    return archive


async def _broadcast_discussion(archive_id: int, payload: dict):
    sockets = _discussion_connections_by_archive.get(archive_id)
    if not sockets:
        return

    dead: list[WebSocket] = []
    for ws in list(sockets):
        try:
            await ws.send_json(payload)
        except Exception as exc:
            logger.warning(
                "Discussion WebSocket send failed; removing dead connection",
                exc_info=redacted_exc_info(exc),
            )
            dead.append(ws)

    if dead:
        sockets = _discussion_connections_by_archive.get(archive_id)
        if sockets:
            for ws in dead:
                sockets.discard(ws)
            if not sockets:
                _discussion_connections_by_archive.pop(archive_id, None)


async def _fetch_archive_discussion_messages(
    archive_id: int,
    db: AsyncSession,
    *,
    current_user_id: int,
    limit: int = 50,
    before_id: int | None = None,
) -> list[ArchiveDiscussionMessageRead]:
    safe_limit = max(1, min(int(limit or 50), 100))
    reply_alias = aliased(ArchiveDiscussionMessage)
    active_reply_exists = exists(
        select(reply_alias.id).where(
            reply_alias.parent_id == ArchiveDiscussionMessage.id,
            reply_alias.deleted_at.is_(None),
        )
    )
    root_like_count = (
        select(func.count(ArchiveDiscussionLike.id))
        .where(ArchiveDiscussionLike.message_id == ArchiveDiscussionMessage.id)
        .correlate(ArchiveDiscussionMessage)
        .scalar_subquery()
    )
    root_stmt = (
        select(ArchiveDiscussionMessage.id)
        .where(
            ArchiveDiscussionMessage.archive_id == archive_id,
            ArchiveDiscussionMessage.parent_id.is_(None),
            or_(
                ArchiveDiscussionMessage.deleted_at.is_(None),
                active_reply_exists,
            ),
        )
        .order_by(
            ArchiveDiscussionMessage.is_pinned.desc(),
            root_like_count.desc(),
            ArchiveDiscussionMessage.created_at.desc(),
            ArchiveDiscussionMessage.id.desc(),
        )
        .limit(safe_limit)
    )
    if before_id is not None:
        root_stmt = root_stmt.where(ArchiveDiscussionMessage.id < before_id)

    root_ids = list((await db.execute(root_stmt)).scalars().all())
    if not root_ids:
        return []

    experience_by_author = (
        select(
            ArchiveSubmission.requester_id.label("author_id"),
            func.count(ArchiveSubmission.id).label("experience"),
        )
        .where(
            ArchiveSubmission.status.in_(
                [SubmissionStatus.APPROVED, SubmissionStatus.TAKEDOWN]
            )
        )
        .group_by(ArchiveSubmission.requester_id)
        .subquery()
    )
    like_count = (
        select(func.count(ArchiveDiscussionLike.id))
        .where(ArchiveDiscussionLike.message_id == ArchiveDiscussionMessage.id)
        .correlate(ArchiveDiscussionMessage)
        .scalar_subquery()
    )
    liked_by_current_user = exists(
        select(ArchiveDiscussionLike.id).where(
            ArchiveDiscussionLike.message_id == ArchiveDiscussionMessage.id,
            ArchiveDiscussionLike.user_id == current_user_id,
        )
    )

    stmt = (
        select(
            ArchiveDiscussionMessage,
            User.nickname,
            User.name,
            User.show_level_title,
            User.deleted_at,
            func.coalesce(experience_by_author.c.experience, 0),
            like_count.label("like_count"),
            liked_by_current_user.label("liked_by_current_user"),
        )
        .join(User, User.id == ArchiveDiscussionMessage.user_id)
        .outerjoin(
            experience_by_author,
            experience_by_author.c.author_id == ArchiveDiscussionMessage.user_id,
        )
        .where(
            ArchiveDiscussionMessage.archive_id == archive_id,
            or_(
                ArchiveDiscussionMessage.id.in_(root_ids),
                and_(
                    ArchiveDiscussionMessage.parent_id.in_(root_ids),
                    ArchiveDiscussionMessage.deleted_at.is_(None),
                ),
            ),
        )
    )
    rows = (await db.execute(stmt)).all()

    reply_target_ids = {
        msg.reply_to_message_id for row in rows if (msg := row[0]).reply_to_message_id
    }
    reply_target_names: dict[int, str] = {}
    if reply_target_ids:
        target_rows = (
            await db.execute(
                select(
                    ArchiveDiscussionMessage.id,
                    ArchiveDiscussionMessage.user_id,
                    User.nickname,
                    User.name,
                )
                .join(User, User.id == ArchiveDiscussionMessage.user_id)
                .where(ArchiveDiscussionMessage.id.in_(reply_target_ids))
            )
        ).all()
        reply_target_names = {
            target_id: _discussion_public_display_name(
                user_id=target_user_id,
                nickname=nickname,
                name=user_name,
            )
            for target_id, target_user_id, nickname, user_name in target_rows
        }

    messages_by_id: dict[int, ArchiveDiscussionMessageRead] = {}
    for (
        msg,
        nickname,
        user_name,
        show_level_title,
        deleted_at,
        experience,
        message_like_count,
        message_liked_by_current_user,
    ) in rows:
        is_deleted = msg.deleted_at is not None
        messages_by_id[msg.id] = ArchiveDiscussionMessageRead(
            id=msg.id,
            archive_id=msg.archive_id,
            user_id=msg.user_id,
            user_name=_discussion_public_display_name(
                user_id=msg.user_id, nickname=nickname, name=user_name
            ),
            author_show_level_title=bool(show_level_title and deleted_at is None),
            author_experience=int(experience) if deleted_at is None else None,
            content="" if is_deleted else msg.content,
            is_pinned=msg.is_pinned,
            is_deleted=is_deleted,
            parent_id=msg.parent_id,
            reply_to_message_id=msg.reply_to_message_id,
            reply_to_user_name=reply_target_names.get(msg.reply_to_message_id),
            like_count=int(message_like_count or 0),
            liked_by_current_user=bool(message_liked_by_current_user),
            created_at=msg.created_at,
        )

    roots = [
        messages_by_id[root_id] for root_id in root_ids if root_id in messages_by_id
    ]
    for message in messages_by_id.values():
        if message.parent_id in messages_by_id:
            messages_by_id[message.parent_id].replies.append(message)
    for root in roots:
        root.replies.sort(key=lambda reply: (reply.created_at, reply.id))
    return roots


@router.get(
    "/{course_id}/archives/{archive_id}/discussion/messages",
    response_model=list[ArchiveDiscussionMessageRead],
)
async def list_archive_discussion_messages(
    course_id: int,
    archive_id: int,
    limit: int = 50,
    before_id: int | None = None,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_archive_exists_for_discussion(course_id, archive_id, db)
    return await _fetch_archive_discussion_messages(
        archive_id,
        db,
        current_user_id=current_user.user_id,
        limit=limit,
        before_id=before_id,
    )


@router.websocket("/{course_id}/archives/{archive_id}/discussion/ws")
async def archive_discussion_ws(
    websocket: WebSocket,
    course_id: int,
    archive_id: int,
    db: AsyncSession = Depends(get_session),
):
    await websocket.accept()

    payload = await get_ws_token_payload(websocket)
    if not payload:
        await websocket.close(code=4401)
        return

    user_id = payload.get("uid")
    if not user_id:
        await websocket.close(code=4401)
        return

    user = await db.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    if not user:
        await websocket.close(code=4401)
        return

    exp = payload.get("exp")
    exp_ts = float(exp) if exp is not None else None

    try:
        await _ensure_archive_exists_for_discussion(course_id, archive_id, db)
    except HTTPException:
        await websocket.close(code=1008)
        return

    sockets = _discussion_connections_by_archive.setdefault(archive_id, set())
    sockets.add(websocket)

    try:
        history = await _fetch_archive_discussion_messages(
            archive_id,
            db,
            current_user_id=user.id,
            limit=50,
            before_id=None,
        )
        await websocket.send_json(
            jsonable_encoder({"type": "history", "messages": history})
        )

        while True:
            raw = await websocket.receive_text()
            if exp_ts is not None and exp_ts < datetime.now(UTC).timestamp():
                await websocket.close(code=4401)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, dict):
                continue

            msg_type = str(data.get("type") or "").strip().lower()
            if msg_type != "send":
                continue
            raw_content = str(data.get("content") or "")
            content = raw_content.strip()
            if not content:
                continue
            if len(content) > DISCUSSION_MESSAGE_MAX_LENGTH:
                await websocket.send_json(
                    jsonable_encoder(
                        {
                            "type": "error",
                            "code": "message_too_long",
                            "detail": f"訊息超出 {DISCUSSION_MESSAGE_MAX_LENGTH} 字",
                        }
                    )
                )
                continue

            parent_id = None
            reply_to_message_id = None
            reply_to_user_name = None
            raw_reply_to_message_id = data.get("reply_to_message_id")
            if raw_reply_to_message_id is not None:
                try:
                    reply_to_message_id = int(raw_reply_to_message_id)
                except (TypeError, ValueError):
                    reply_to_message_id = None
                if not reply_to_message_id:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_reply_target",
                            "detail": "找不到要回覆的留言",
                        }
                    )
                    continue

                reply_target_row = (
                    await db.execute(
                        select(
                            ArchiveDiscussionMessage,
                            User.nickname,
                            User.name,
                        )
                        .join(User, User.id == ArchiveDiscussionMessage.user_id)
                        .where(
                            ArchiveDiscussionMessage.id == reply_to_message_id,
                            ArchiveDiscussionMessage.archive_id == archive_id,
                            ArchiveDiscussionMessage.deleted_at.is_(None),
                        )
                    )
                ).one_or_none()
                if not reply_target_row:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_reply_target",
                            "detail": "找不到要回覆的留言",
                        }
                    )
                    continue

                reply_target, target_nickname, target_name = reply_target_row
                parent_id = reply_target.parent_id or reply_target.id
                root_exists = await db.scalar(
                    select(ArchiveDiscussionMessage.id).where(
                        ArchiveDiscussionMessage.id == parent_id,
                        ArchiveDiscussionMessage.archive_id == archive_id,
                    )
                )
                if not root_exists:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_reply_target",
                            "detail": "找不到回覆串的原始留言",
                        }
                    )
                    continue
                reply_to_user_name = _discussion_public_display_name(
                    user_id=reply_target.user_id,
                    nickname=target_nickname,
                    name=target_name,
                )

            message = ArchiveDiscussionMessage(
                archive_id=archive_id,
                user_id=user.id,
                parent_id=parent_id,
                reply_to_message_id=reply_to_message_id,
                content=content,
                created_at=datetime.now(UTC),
            )
            db.add(message)
            await db.flush()
            if reply_to_message_id is not None and reply_target.user_id != user.id:
                actor_name = _discussion_public_display_name(
                    user_id=user.id,
                    nickname=user.nickname,
                    name=user.name,
                )
                await enqueue_personal_notification(
                    db,
                    user_id=reply_target.user_id,
                    notification_type=PersonalNotificationType.DISCUSSION_REPLY,
                    title=f"{actor_name} 回覆了你的留言",
                    message=content,
                    source_type="archive_discussion_thread",
                    source_id=parent_id,
                    source_message_id=message.id,
                    metadata={
                        "archive_id": archive_id,
                        "course_id": course_id,
                        "thread_id": parent_id,
                        "reply_message_id": message.id,
                        "reply_to_message_id": reply_to_message_id,
                        "actor_name": actor_name,
                    },
                    dedupe_key=f"discussion_reply:{message.id}:{reply_target.user_id}",
                    created_at=message.created_at,
                )
            await db.commit()
            await db.refresh(message)

            # Fetch current public author metadata once for this new message.
            experience = (
                select(func.count(ArchiveSubmission.id))
                .where(
                    ArchiveSubmission.requester_id == user.id,
                    ArchiveSubmission.status.in_(
                        [SubmissionStatus.APPROVED, SubmissionStatus.TAKEDOWN]
                    ),
                )
                .scalar_subquery()
            )
            user_row = (
                await db.execute(
                    select(
                        User.nickname,
                        User.name,
                        User.show_level_title,
                        User.deleted_at,
                        func.coalesce(experience, 0),
                    ).where(User.id == user.id)
                )
            ).one_or_none()
            latest_display_name = None
            author_show_level_title = False
            author_experience = None
            if user_row:
                latest_display_name = _discussion_public_display_name(
                    user_id=user.id, nickname=user_row[0], name=user_row[1]
                )
                author_show_level_title = bool(user_row[2] and user_row[3] is None)
                author_experience = int(user_row[4]) if user_row[3] is None else None

            payload = jsonable_encoder(
                {
                    "type": "message",
                    "message": ArchiveDiscussionMessageRead(
                        id=message.id,
                        archive_id=message.archive_id,
                        user_id=message.user_id,
                        user_name=latest_display_name
                        or _discussion_public_display_name(
                            user_id=user.id, nickname=user.nickname, name=user.name
                        ),
                        author_show_level_title=author_show_level_title,
                        author_experience=author_experience,
                        content=message.content,
                        is_pinned=message.is_pinned,
                        parent_id=message.parent_id,
                        reply_to_message_id=message.reply_to_message_id,
                        reply_to_user_name=reply_to_user_name,
                        like_count=0,
                        liked_by_current_user=False,
                        created_at=message.created_at,
                    ),
                }
            )
            await _broadcast_discussion(archive_id, payload)
    except WebSocketDisconnect:
        return
    finally:
        sockets = _discussion_connections_by_archive.get(archive_id)
        if sockets:
            sockets.discard(websocket)
            if not sockets:
                _discussion_connections_by_archive.pop(archive_id, None)


async def _get_active_discussion_message(
    archive_id: int,
    message_id: int,
    db: AsyncSession,
) -> ArchiveDiscussionMessage:
    message = (
        await db.execute(
            select(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.id == message_id,
                ArchiveDiscussionMessage.archive_id == archive_id,
                ArchiveDiscussionMessage.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    return message


async def _discussion_like_count(message_id: int, db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count(ArchiveDiscussionLike.id)).where(
                ArchiveDiscussionLike.message_id == message_id
            )
        )
        or 0
    )


@router.put("/{course_id}/archives/{archive_id}/discussion/{message_id}/like")
async def like_archive_discussion_message(
    course_id: int,
    archive_id: int,
    message_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    archive = await _ensure_archive_exists_for_discussion(course_id, archive_id, db)
    message = await _get_active_discussion_message(archive_id, message_id, db)

    like_id = await db.scalar(
        pg_insert(ArchiveDiscussionLike)
        .values(message_id=message_id, user_id=current_user.user_id)
        .on_conflict_do_nothing(constraint="uq_archive_discussion_likes_message_user")
        .returning(ArchiveDiscussionLike.id)
    )
    if like_id is not None and message.user_id != current_user.user_id:
        actor = await db.get(User, current_user.user_id)
        course = await db.get(Course, course_id)
        actor_name = _discussion_public_display_name(
            user_id=current_user.user_id,
            nickname=actor.nickname if actor else None,
            name=actor.name if actor else None,
        )
        await enqueue_personal_notification(
            db,
            user_id=message.user_id,
            notification_type=PersonalNotificationType.DISCUSSION_LIKE,
            title=f"{actor_name} 對你的留言按了愛心",
            message=(message.content[:80] + "…")
            if len(message.content) > 80
            else message.content,
            source_type="archive_discussion_thread",
            source_id=message.parent_id or message.id,
            source_message_id=message.id,
            metadata={
                "archive_id": archive_id,
                "archive_name": archive.name,
                "course_id": course_id,
                "course_name": course.name if course else None,
                "course_name_en": course.name_en if course else None,
                "thread_id": message.parent_id or message.id,
                "message_id": message.id,
                "actor_user_id": current_user.user_id,
                "actor_name": actor_name,
            },
            dedupe_key=f"discussion_like:{message.id}:{current_user.user_id}",
        )
    await db.commit()
    like_count = await _discussion_like_count(message_id, db)
    await _broadcast_discussion(
        archive_id,
        {
            "type": "like",
            "message_id": message_id,
            "user_id": current_user.user_id,
            "liked": True,
            "like_count": like_count,
        },
    )
    return {"liked": True, "like_count": like_count}


@router.delete("/{course_id}/archives/{archive_id}/discussion/{message_id}/like")
async def unlike_archive_discussion_message(
    course_id: int,
    archive_id: int,
    message_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_archive_exists_for_discussion(course_id, archive_id, db)
    await _get_active_discussion_message(archive_id, message_id, db)

    await db.execute(
        delete(ArchiveDiscussionLike).where(
            ArchiveDiscussionLike.message_id == message_id,
            ArchiveDiscussionLike.user_id == current_user.user_id,
        )
    )
    await db.commit()
    like_count = await _discussion_like_count(message_id, db)
    await _broadcast_discussion(
        archive_id,
        {
            "type": "like",
            "message_id": message_id,
            "user_id": current_user.user_id,
            "liked": False,
            "like_count": like_count,
        },
    )
    return {"liked": False, "like_count": like_count}


@router.delete("/{course_id}/archives/{archive_id}/discussion/{message_id}")
async def delete_archive_discussion_message(
    course_id: int,
    archive_id: int,
    message_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_archive_exists_for_discussion(course_id, archive_id, db)

    message = await _get_active_discussion_message(archive_id, message_id, db)

    if not current_user.is_admin and message.user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    preserve_thread = await soft_delete_discussion_message(db, message)
    await db.commit()

    await _broadcast_discussion(
        archive_id,
        jsonable_encoder(
            {
                "type": "delete",
                "message_id": message_id,
                "preserve_thread": preserve_thread,
            }
        ),
    )
    return {"success": True, "preserve_thread": preserve_thread}


@router.patch("/{course_id}/archives/{archive_id}/discussion/{message_id}/pin")
async def pin_archive_discussion_message(
    course_id: int,
    archive_id: int,
    message_id: int,
    pinned: bool = Form(...),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_archive_exists_for_discussion(course_id, archive_id, db)
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    message = (
        await db.execute(
            select(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.id == message_id,
                ArchiveDiscussionMessage.archive_id == archive_id,
                ArchiveDiscussionMessage.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )
    if message.parent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Replies cannot be pinned",
        )

    was_pinned = bool(message.is_pinned)
    message.is_pinned = pinned
    db.add(message)
    if pinned and not was_pinned and message.user_id != current_user.user_id:
        archive = await db.get(Archive, archive_id)
        course = await db.get(Course, course_id)
        await enqueue_personal_notification(
            db,
            user_id=message.user_id,
            notification_type=PersonalNotificationType.DISCUSSION_PIN,
            title="你的留言已被管理員置頂",
            message=(message.content[:80] + "…")
            if len(message.content) > 80
            else message.content,
            source_type="archive_discussion_thread",
            source_id=message.id,
            source_message_id=message.id,
            metadata={
                "archive_id": archive_id,
                "archive_name": archive.name if archive else None,
                "course_id": course_id,
                "course_name": course.name if course else None,
                "course_name_en": course.name_en if course else None,
                "thread_id": message.id,
                "message_id": message.id,
                "actor_user_id": current_user.user_id,
            },
            dedupe_key=f"discussion_pin:{message.id}",
        )
    await db.commit()
    await db.refresh(message)

    await _broadcast_discussion(
        archive_id,
        jsonable_encoder(
            {
                "type": "pin",
                "message_id": message_id,
                "is_pinned": message.is_pinned,
            }
        ),
    )
    return {"success": True, "is_pinned": message.is_pinned}


@router.patch("/{course_id}/archives/{archive_id}")
async def update_archive(
    course_id: int,
    archive_id: int,
    name: str = Form(None),
    professor: str = Form(None),
    archive_type: ArchiveType = Form(None),
    has_answers: bool = Form(None),
    academic_year: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update archive information. Only admins can update archives.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update archives",
        )

    try:
        locked = await acquire_stable_archive_mutation_locks(
            db,
            archive_id=archive_id,
            target_course_id=None,
            operation="archive_edit",
        )
    except ArchiveMutationLifecycleConflict:
        raise archive_lifecycle_conflict_error()
    archive = locked.archive(archive_id) if locked is not None else None

    if not archive or archive.course_id != course_id or archive.deleted_at is not None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )

    if name is not None:
        archive.name = name
    if professor is not None:
        archive.professor = professor
    if archive_type is not None:
        archive.archive_type = archive_type
    if has_answers is not None:
        archive.has_answers = has_answers
    if academic_year is not None:
        archive.academic_year = academic_year

    archive.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(archive)

    return archive


@router.patch("/{course_id}/archives/{archive_id}/course")
async def update_archive_course(
    course_id: int,
    archive_id: int,
    course_update: ArchiveUpdateCourse,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update archive's course. Only admins can change archive's course.
    Supports both course ID and the existing normalized name/category lookup.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change archive's course",
        )

    if course_update.course_id is not None:
        target = await resolve_archive_move_target(
            db,
            course_id=course_update.course_id,
            normalized_name=None,
            category=None,
        )
    elif course_update.course_name and course_update.course_category:
        normalized_course_name = normalize_course_search_text(course_update.course_name)
        target = await resolve_archive_move_target(
            db,
            course_id=None,
            normalized_name=normalized_course_name,
            category=course_update.course_category,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Either course_id or both course_name and course_category "
                "must be provided"
            ),
        )

    try:
        locked = await acquire_stable_archive_mutation_locks(
            db,
            archive_id=archive_id,
            target_course_id=target.course_id,
            operation="archive_move",
        )
    except ArchiveMutationLifecycleConflict:
        raise archive_lifecycle_conflict_error()
    archive = locked.archive(archive_id) if locked is not None else None
    if (
        archive is None
        or archive.course_id != course_id
        or archive.deleted_at is not None
    ):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive not found",
        )

    if target.course_id == course_id:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot transfer archive to the same course",
        )

    new_course = locked.course(target.course_id)
    if new_course is None:
        await db.rollback()
        raise archive_move_target_not_found_error()
    if new_course.deleted_at is not None:
        await db.rollback()
        raise archive_move_target_trashed_error()

    if target.normalized_name is not None:
        revalidated_target = await resolve_archive_move_target(
            db,
            course_id=None,
            normalized_name=target.normalized_name,
            category=target.category,
        )
        if revalidated_target.course_id != target.course_id:
            await db.rollback()
            raise course_lifecycle_conflict_error()

    archive.course_id = target.course_id
    archive.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(archive)

    return {
        "message": f"Archive moved to course '{new_course.name}'",
        "archive_id": archive.id,
        "old_course_id": course_id,
        "new_course_id": target.course_id,
    }


@router.delete("/{course_id}/archives/{archive_id}")
async def delete_archive(
    course_id: int,
    archive_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Soft delete an archive. Users can only delete their own uploads.
    Admins can delete any archive.
    """
    budget = PlanRebuildBudget()
    locked: LockedLifecycleRows | None = None
    while True:
        (
            locked,
            revalidation,
        ) = await archive_lifecycle_locks.acquire_exact_archive_lifecycle_locks(
            db,
            archive_id=archive_id,
            operation="archive_trash",
        )
        if locked is None:
            break
        if revalidation is not None and revalidation.valid:
            break
        conflict_archive = locked.archive(archive_id)
        terminal_error = None
        if (
            conflict_archive is None
            or conflict_archive.course_id != course_id
            or conflict_archive.deleted_at is not None
        ):
            terminal_error = HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Archive not found",
            )
        elif (
            not current_user.is_admin
            and conflict_archive.uploader_id != current_user.user_id
        ):
            terminal_error = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this archive",
            )
        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted:
            if terminal_error is not None:
                raise terminal_error
            raise archive_lifecycle_conflict_error()

    archive = locked.archive(archive_id) if locked is not None else None

    if not archive or archive.course_id != course_id or archive.deleted_at is not None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive not found"
        )

    if not current_user.is_admin and archive.uploader_id != current_user.user_id:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this archive",
        )

    result = await soft_delete_archive_with_submission_takedown(
        db,
        archive=archive,
        submissions=locked.submissions,
        user_id=current_user.user_id,
        reason="archive deleted",
    )
    await db.commit()

    return {"message": "Archive deleted successfully", "deleted": result}


@router.post("/admin/courses", response_model=CourseRead)
async def create_course(
    course_data: CourseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Create a new course. Only admins can create courses.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create courses",
        )

    await _ensure_category(db, course_data.category)

    formatted_name = format_course_display_name(course_data.name)
    normalized_name = normalize_course_search_text(course_data.name)

    query = select(Course).where(
        normalized_course_text_expr(Course.name) == normalized_name,
        Course.category == course_data.category,
        Course.deleted_at.is_(None),
    )
    result = await db.execute(query)
    existing_course = result.scalar_one_or_none()

    if existing_course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course with this name and category already exists",
        )

    order_index = course_data.order_index
    if order_index is None:
        order_index = await _next_order_index(db, course_data.category)

    course = Course(
        name=formatted_name,
        name_en=(course_data.name_en or "").strip() or None,
        category=course_data.category,
        order_index=order_index,
    )

    db.add(course)
    await db.commit()
    await db.refresh(course)

    return course


@router.put("/admin/courses/{course_id}", response_model=CourseRead)
async def update_course(
    course_id: int,
    course_data: CourseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update a course. Only admins can update courses.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update courses",
        )

    query = select(Course).where(Course.id == course_id, Course.deleted_at.is_(None))
    result = await db.execute(query)
    course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    original_category = course.category

    if course_data.name is not None or course_data.category is not None:
        new_name = course_data.name if course_data.name is not None else course.name
        formatted_name = format_course_display_name(new_name)
        normalized_new_name = normalize_course_search_text(formatted_name)
        normalized_current_name = normalize_course_search_text(course.name)
        new_category = (
            course_data.category
            if course_data.category is not None
            else course.category
        )

        if (
            normalized_new_name != normalized_current_name
            or new_category != course.category
        ):
            check_query = select(Course).where(
                normalized_course_text_expr(Course.name) == normalized_new_name,
                Course.category == new_category,
                Course.id != course_id,
                Course.deleted_at.is_(None),
            )
            check_result = await db.execute(check_query)
            existing_course = check_result.scalar_one_or_none()

            if existing_course:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Course with this name and category already exists",
                )

    if course_data.name is not None:
        course.name = formatted_name
    if course_data.name_en is not None:
        course.name_en = course_data.name_en.strip() or None
    if course_data.category is not None:
        await _ensure_category(db, course_data.category)
        course.category = course_data.category
        if (
            course_data.category != original_category
            and course_data.order_index is None
        ):
            course.order_index = await _next_order_index(db, course_data.category)
    if course_data.order_index is not None:
        course.order_index = course_data.order_index

    await db.commit()
    await db.refresh(course)

    return course


@router.post("/admin/courses/reorder", response_model=list[CourseRead])
async def reorder_courses(
    reorder_data: CourseReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update course order within one category. Only admins can reorder courses.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can reorder courses",
        )

    await _ensure_category(db, reorder_data.category)

    result = await db.execute(
        select(Course).where(
            Course.category == reorder_data.category,
            Course.deleted_at.is_(None),
        )
    )
    courses = result.scalars().all()
    courses_by_id = {course.id: course for course in courses}

    requested_ids = list(dict.fromkeys(reorder_data.course_ids))
    missing_ids = [
        course_id for course_id in requested_ids if course_id not in courses_by_id
    ]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course order includes courses outside the selected category",
        )

    ordered_courses = [courses_by_id[course_id] for course_id in requested_ids]
    ordered_id_set = set(requested_ids)
    remaining_courses = sorted(
        (course for course in courses if course.id not in ordered_id_set),
        key=lambda item: _course_sort_key(item),
    )

    for index, course in enumerate([*ordered_courses, *remaining_courses]):
        course.order_index = index

    await db.commit()

    result = await db.execute(
        select(Course).where(
            Course.category == reorder_data.category,
            Course.deleted_at.is_(None),
        )
    )
    category_order = await _category_order_map(db)
    return _visible_courses(result.scalars().all(), category_order)


@router.delete("/admin/courses/{course_id}")
async def delete_course(
    course_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Delete a course. Only admins can delete courses.
    This will also soft delete all associated archives.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete courses",
        )

    budget = PlanRebuildBudget()
    locked_course_plan = None
    while True:
        (
            locked_course_plan,
            revalidation,
        ) = await course_lifecycle_locks.acquire_course_lifecycle_plan_once(
            db,
            course_id=course_id,
            operation=CourseLifecycleOperation.TRASH,
        )
        if locked_course_plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )
        if revalidation is not None and revalidation.valid:
            break

        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted:
            raise course_lifecycle_conflict_error()

    course = locked_course_plan.rows.course(course_id)
    if course is None or course.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    mutable_archive_ids = set(locked_course_plan.plan.mutable_archive_ids)
    active_archives = [
        archive
        for archive in locked_course_plan.rows.archives
        if archive.id in mutable_archive_ids
    ]
    mutable_submission_ids = set(locked_course_plan.plan.mutable_submission_ids)
    linked_submissions = [
        submission
        for submission in locked_course_plan.rows.submissions
        if submission.id in mutable_submission_ids
    ]

    # Soft delete all associated archives and the course
    current_time = datetime.now(UTC)
    for archive in active_archives:
        archive.deleted_at = current_time
        archive.deleted_by_id = current_user.user_id
        archive.deleted_reason = "course deleted"

    for submission in linked_submissions:
        if is_course_trash_lifecycle_reason(submission.lifecycle_reason):
            continue

        previous_status = submission.status

        submission.status = SubmissionStatus.TAKEDOWN
        submission.lifecycle_reason = make_course_trash_lifecycle_reason(
            previous_status=previous_status,
            course_id=course.id,
            archive_id=submission.created_archive_id,
        )
        submission.reviewer_id = current_user.user_id
        submission.reviewed_at = current_time

    # Soft delete the course
    course.deleted_at = current_time
    course.deleted_by_id = current_user.user_id

    await db.commit()

    return {
        "message": (
            f"Course '{course.name}' and {len(active_archives)} associated "
            f"archives deleted successfully"
        )
    }


@router.get("/admin/courses", response_model=list[CourseRead])
async def list_all_courses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Get all courses with full details. Only admins can access this.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access all courses",
        )

    query = select(Course).where(Course.deleted_at.is_(None))
    result = await db.execute(query)
    category_order = await _admin_category_order_map(db)
    courses = _visible_courses(result.scalars().all(), category_order)

    return courses


@router.get("/admin/categories", response_model=list[CourseCategoryRead])
async def list_admin_course_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    result = await db.execute(
        select(CourseCategoryConfig)
        .where(CourseCategoryConfig.deleted_at.is_(None))
        .order_by(
            CourseCategoryConfig.order_index,
            CourseCategoryConfig.id,
        )
    )
    return result.scalars().all()


@router.post("/admin/categories", response_model=CourseCategoryRead)
async def create_course_category(
    category_data: CourseCategoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    key = _validated_admin_category_key(category_data.key)
    name = await _ensure_unique_category_name(db, category_data.name)

    existing = (
        await db.execute(
            select(CourseCategoryConfig).where(CourseCategoryConfig.key == key)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category key already exists",
        )

    order_index = category_data.order_index
    if order_index is None:
        current_max = (
            await db.execute(select(func.max(CourseCategoryConfig.order_index)))
        ).scalar()
        order_index = 0 if current_max is None else int(current_max) + 1

    category = CourseCategoryConfig(
        key=key,
        name=name,
        name_en=(category_data.name_en or "").strip() or None,
        label=category_data.label.strip(),
        label_en=(category_data.label_en or "").strip() or None,
        icon=category_data.icon.strip() or "pi pi-fw pi-book",
        badge_color=_normalize_category_badge_color(category_data.badge_color),
        order_index=order_index,
        is_active=True,
    )
    db.add(category)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category key or name already exists",
        ) from exc
    await db.refresh(category)
    return category


@router.put("/admin/categories/{category_id}", response_model=CourseCategoryRead)
async def update_course_category(
    category_id: int,
    category_data: CourseCategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    category = await db.get(CourseCategoryConfig, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    old_key = category.key
    if category_data.key is not None:
        new_key = _validated_admin_category_key(category_data.key)
        existing = (
            await db.execute(
                select(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == new_key,
                    CourseCategoryConfig.id != category_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category key already exists",
            )
        category.key = new_key
        if new_key != old_key:
            for model in (Course, CourseSubmission, ArchiveSubmission):
                await db.execute(
                    sql_update(model)
                    .where(model.category == old_key)
                    .values(category=new_key)
                )
            await db.execute(
                sql_update(ArchiveSubmission)
                .where(ArchiveSubmission.requested_category_key == old_key)
                .values(requested_category_key=new_key)
            )

    if category_data.name is not None:
        category.name = await _ensure_unique_category_name(
            db,
            category_data.name,
            exclude_category_id=category_id,
        )
    if category_data.name_en is not None:
        category.name_en = category_data.name_en.strip() or None
    if category_data.label is not None:
        category.label = category_data.label.strip()
    if category_data.label_en is not None:
        category.label_en = category_data.label_en.strip() or None
    if category_data.icon is not None:
        category.icon = category_data.icon.strip() or "pi pi-fw pi-book"
    if category_data.badge_color is not None:
        category.badge_color = _normalize_category_badge_color(
            category_data.badge_color
        )
    if category_data.order_index is not None:
        category.order_index = category_data.order_index
    if category_data.is_active is not None:
        category.is_active = category_data.is_active
    category.updated_at = datetime.now(UTC)
    await db.execute(
        sql_update(ArchiveSubmission)
        .where(ArchiveSubmission.requested_category_key == category.key)
        .values(
            requested_category_name=category.name,
            requested_category_label=category.label,
            requested_category_icon=category.icon,
        )
    )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category key or name already exists",
        ) from exc
    await db.refresh(category)
    return category


@router.post("/admin/categories/reorder", response_model=list[CourseCategoryRead])
async def reorder_course_categories(
    reorder_data: CourseCategoryReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    result = await db.execute(select(CourseCategoryConfig))
    categories = result.scalars().all()
    categories_by_id = {category.id: category for category in categories}
    requested_ids = list(dict.fromkeys(reorder_data.category_ids))
    missing = [
        category_id
        for category_id in requested_ids
        if category_id not in categories_by_id
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category order includes unknown categories",
        )

    ordered = [categories_by_id[category_id] for category_id in requested_ids]
    ordered_ids = set(requested_ids)
    remaining = sorted(
        (category for category in categories if category.id not in ordered_ids),
        key=lambda item: (item.order_index, item.id or 0),
    )
    for index, category in enumerate([*ordered, *remaining]):
        category.order_index = index
        category.updated_at = datetime.now(UTC)

    await db.commit()
    result = await db.execute(
        select(CourseCategoryConfig).order_by(
            CourseCategoryConfig.order_index,
            CourseCategoryConfig.id,
        )
    )
    return result.scalars().all()


@router.delete("/admin/categories/{category_id}")
async def delete_course_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    category = await db.get(CourseCategoryConfig, category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    active_courses = (
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

    if active_courses:
        if len(active_courses) > 5:
            sample_names = (
                ", ".join(course.name for course in active_courses[:5])
                + f" 等 {len(active_courses)} 門課程"
            )
        else:
            sample_names = ", ".join(course.name for course in active_courses)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"此分類仍有啟用中的課程，請先刪除或移動這些課程後再刪除分類。({len(active_courses)} 門，包含：{sample_names})",
        )

    category.pre_delete_is_active = category.is_active
    category.is_active = False
    category.deleted_at = datetime.now(UTC)
    category.deleted_by_id = current_user.user_id

    await db.commit()
    return {"message": "Category deleted successfully"}
