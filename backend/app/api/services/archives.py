import io
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from sqlalchemy import BigInteger, and_, cast, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_ARCHIVE_TRASHED,
    LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED,
    acquire_stable_submission_lifecycle_locks,
    is_course_trash_lifecycle_reason,
    soft_delete_submission_with_linked_archive,
)
from app.api.services.submission_statistics import (
    SUBMISSION_RANGE_CONFIG,
    build_submission_statistics,
    get_submission_statistics_window,
    record_submission_event,
)
from app.core.config import settings
from app.db.course_categories import (
    RESERVED_LEGACY_COURSE_CATEGORY_KEYS,
    canonicalize_course_category_key,
    normalize_course_category_key,
)
from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionActionRead,
    ArchiveSubmissionAdminAction,
    ArchiveSubmissionAdminRead,
    ArchiveSubmissionComparisonRead,
    ArchiveSubmissionEvent,
    ArchiveSubmissionRead,
    ArchiveSubmissionUpdate,
    Course,
    CourseCategoryConfig,
    SubmissionDecision,
    SubmissionStatisticsRead,
    SubmissionStatus,
    User,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleMembershipFingerprint,
    LifecyclePlanRetryExhausted,
    PlanRebuildBudget,
)
from app.services.archive_submission_links import (
    archive_submission_link_conflict,
    ensure_archive_submission_link_available,
    is_archive_submission_link_unique_violation,
    validate_archive_source_membership,
)
from app.services.archive_submission_status import (
    ArchiveSubmissionExpectedStateClassification,
    ArchiveSubmissionReviewAction,
    ArchiveSubmissionTransitionClassification,
    archive_submission_self_delete_consumed_error,
    available_archive_submission_admin_actions,
    capture_submission_status_notification_identity,
    classify_archive_submission_expected_state,
    classify_archive_submission_review_transition,
    enqueue_submission_status_notification,
    normalize_submission_status,
    republish_archive_submission,
    resolve_archive_submission_actual_status,
    resolve_archive_submission_delete_source_status,
    take_down_archive_submission,
)
from app.utils.auth import get_current_user
from app.utils.course_text import (
    format_course_display_name,
    normalize_course_search_text,
    normalize_first_course_search_text,
    normalized_course_text_expr,
)
from app.utils.exception_logging import redacted_exc_info
from app.utils.storage import get_minio_client

router = APIRouter()
logger = logging.getLogger(__name__)

ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL = {
    "code": "archive_submission_edit_forbidden",
    "message": "此狀態的投稿不可直接編輯。",
    "reload_required": False,
}


async def _ensure_category(db: AsyncSession, category_key: str) -> None:
    category_key = canonicalize_course_category_key(category_key)
    result = await db.execute(
        select(CourseCategoryConfig).where(
            CourseCategoryConfig.key == category_key,
            CourseCategoryConfig.is_active.is_(True),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course category does not exist",
        )


def _normalize_category_key(value: str) -> str:
    key = (value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{2,40}", key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category key must use lowercase letters, numbers, or hyphens",
        )
    return canonicalize_course_category_key(key)


def _unwrap_form_default(value, default=None):
    if hasattr(value, "default"):
        return default if value.default is Ellipsis else value.default
    return value


def _normalize_submission_status(raw_status):
    normalized_status = normalize_submission_status(raw_status)
    if normalized_status is None:
        logger.warning("Unsupported submission status encountered: %s", raw_status)
    return normalized_status


def _resolve_submission_actual_status(raw_status, *, deleted_at):
    normalized_status = resolve_archive_submission_actual_status(
        raw_status,
        deleted_at=deleted_at,
    )
    if normalized_status is None:
        logger.warning("Unsupported submission status encountered: %s", raw_status)
    return normalized_status


def _serialize_archive_submission_admin(
    submission,
) -> ArchiveSubmissionAdminRead:
    base = ArchiveSubmissionRead.model_validate(submission)
    deleted_at = (
        submission.get("deleted_at")
        if isinstance(submission, dict)
        else getattr(submission, "deleted_at", None)
    )
    actual_status = _resolve_submission_actual_status(
        base.status,
        deleted_at=deleted_at,
    )
    if actual_status is None:
        raise ValueError(f"Unsupported submission status: {base.status}")

    payload = base.model_dump()
    payload["status"] = actual_status
    payload["available_actions"] = available_archive_submission_admin_actions(
        actual_status
    )
    return ArchiveSubmissionAdminRead.model_validate(payload)


def _serialize_archive_submission_action(
    submission,
    *,
    changed: bool,
) -> ArchiveSubmissionActionRead:
    payload = _serialize_archive_submission_admin(submission).model_dump()
    payload["changed"] = changed
    return ArchiveSubmissionActionRead.model_validate(payload)


def _ensure_archive_submission_editable(submission: ArchiveSubmission) -> None:
    actual_status = _resolve_submission_actual_status(
        submission.status,
        deleted_at=submission.deleted_at,
    )
    if actual_status in {SubmissionStatus.APPROVED, SubmissionStatus.DELETED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=dict(ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL),
        )
    if actual_status not in {
        SubmissionStatus.PENDING,
        SubmissionStatus.REJECTED,
        SubmissionStatus.TAKEDOWN,
    }:
        raise ValueError("Unsupported ArchiveSubmission edit state")


@dataclass(frozen=True)
class _DirectReviewLockContext:
    submission: ArchiveSubmission


async def _prepare_direct_archive_submission_review(
    db: AsyncSession,
    *,
    submission: ArchiveSubmission,
    decision: SubmissionDecision | None,
    action: ArchiveSubmissionReviewAction,
) -> tuple[ArchiveSubmission, ArchiveSubmissionActionRead | None]:
    actual_status = _resolve_submission_actual_status(
        submission.status,
        deleted_at=submission.deleted_at,
    )
    if actual_status is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "archive_submission_illegal_transition",
                "message": "此投稿目前不能執行該審核操作。",
                "actual_status": str(submission.status),
                "reload_required": False,
            },
        )

    expected_status = decision.expected_status if decision else None
    expected_state = classify_archive_submission_expected_state(
        expected_status,
        actual_status,
    )
    if expected_state == ArchiveSubmissionExpectedStateClassification.MISSING:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "archive_submission_precondition_required",
                "message": "請重新載入投稿狀態後再執行操作。",
                "reload_required": True,
            },
        )
    if expected_state == ArchiveSubmissionExpectedStateClassification.STALE:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "archive_submission_stale_state",
                "message": "投稿狀態已變更，請重新載入後再操作。",
                "actual_status": actual_status.value,
                "reload_required": True,
            },
        )

    policy = classify_archive_submission_review_transition(actual_status, action)
    if policy.classification == ArchiveSubmissionTransitionClassification.ILLEGAL:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "archive_submission_illegal_transition",
                "message": "此投稿目前不能執行該審核操作。",
                "actual_status": actual_status.value,
                "reload_required": False,
            },
        )
    if policy.classification == ArchiveSubmissionTransitionClassification.NO_OP:
        response = _serialize_archive_submission_action(
            submission,
            changed=False,
        )
        await db.rollback()
        return submission, response

    return submission, None


def _raise_direct_review_membership_conflict(
    submission: ArchiveSubmission | None,
) -> None:
    actual_status = (
        _resolve_submission_actual_status(
            submission.status,
            deleted_at=submission.deleted_at,
        )
        if submission is not None
        else None
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "archive_submission_stale_state",
            "message": "投稿狀態已變更，請重新載入後再操作。",
            "actual_status": (
                actual_status.value if actual_status is not None else "deleted"
            ),
            "reload_required": True,
        },
    )


async def _discover_direct_review_lock_context(
    db: AsyncSession,
    *,
    submission_id: int,
    action: ArchiveSubmissionReviewAction,
) -> tuple[ArchiveLifecycleLockPlan, dict[str, int | str | None]] | None:
    submission = (
        await db.execute(
            select(ArchiveSubmission)
            .where(ArchiveSubmission.id == submission_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if submission is None:
        return None

    course_name = _normalize_course_name(
        format_course_display_name(
            submission.requested_course_name or submission.subject
        )
    )
    category_key = submission.requested_category_key or submission.category
    approval_scope: str | None = None
    if action == ArchiveSubmissionReviewAction.APPROVE:
        approval_scope = await archive_lifecycle_locks.acquire_approval_namespace_mutex(
            db,
            category_key=category_key,
            course_name=course_name,
        )

    archive = (
        (
            await db.execute(
                select(Archive)
                .where(Archive.id == submission.created_archive_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if submission.created_archive_id is not None
        else None
    )
    sibling_ids: tuple[int, ...] | None = None
    submission_ids = (submission.id,)
    if archive is not None:
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
            operation=(
                "approval"
                if action == ArchiveSubmissionReviewAction.APPROVE
                else "review"
            ),
        )
        if action == ArchiveSubmissionReviewAction.APPROVE:
            submission_ids = sibling_ids

    category = None
    active_course = None
    deleted_course = None
    if action == ArchiveSubmissionReviewAction.APPROVE:
        category_lookup_key = canonicalize_course_category_key(
            (category_key or "").strip().lower()
        )
        category = (
            await db.execute(
                select(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == category_lookup_key
                )
            )
        ).scalar_one_or_none()
        active_course = (
            await db.execute(
                select(Course).where(
                    normalized_course_text_expr(Course.name) == course_name,
                    Course.category == category_key,
                    Course.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active_course is None:
            deleted_course = (
                await db.execute(
                    select(Course).where(
                        normalized_course_text_expr(Course.name) == course_name,
                        Course.category == category_key,
                        Course.deleted_at.is_not(None),
                    )
                )
            ).scalar_one_or_none()

    archive_course_pairs = (
        ((archive.id, archive.course_id),) if archive is not None else ()
    )
    plan = ArchiveLifecycleLockPlan.build(
        category_ids=(category.id if category is not None else None,),
        course_ids=(
            active_course.id if active_course is not None else None,
            deleted_course.id if deleted_course is not None else None,
            archive.course_id if archive is not None else None,
        ),
        archive_ids=(archive.id if archive is not None else None,),
        submission_ids=submission_ids,
        fingerprint=LifecycleMembershipFingerprint(
            target_submission_id=submission.id,
            target_created_archive_id=submission.created_archive_id,
            target_requester_id=submission.requester_id,
            target_owner_id=submission.owner_id,
            archive_course_pairs=archive_course_pairs,
            sibling_submission_ids=sibling_ids,
        ),
        approval_namespace_scope=approval_scope,
    )
    return plan, {
        "course_name": course_name,
        "category_key": category_key,
    }


async def _lock_direct_review_context(
    db: AsyncSession,
    *,
    submission_id: int,
    action: ArchiveSubmissionReviewAction,
) -> _DirectReviewLockContext:
    budget = PlanRebuildBudget()
    while True:
        discovered = await _discover_direct_review_lock_context(
            db,
            submission_id=submission_id,
            action=action,
        )
        if discovered is None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )
        plan, metadata = discovered
        locked = await archive_lifecycle_locks.acquire_lifecycle_locks(db, plan)
        revalidation = await archive_lifecycle_locks.revalidate_lifecycle_membership(
            db,
            locked,
        )
        submission = locked.submission(submission_id)
        approval_identity_changed = False
        if action == ArchiveSubmissionReviewAction.APPROVE and submission is not None:
            locked_course_name = _normalize_course_name(
                format_course_display_name(
                    submission.requested_course_name or submission.subject
                )
            )
            locked_category_key = (
                submission.requested_category_key or submission.category
            )
            approval_identity_changed = (
                locked_course_name != metadata["course_name"]
                or locked_category_key != metadata["category_key"]
            )
        if revalidation.valid and not approval_identity_changed:
            if submission is None:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Submission not found",
                )
            return _DirectReviewLockContext(submission=submission)

        await db.rollback()
        try:
            budget = budget.consume()
        except LifecyclePlanRetryExhausted:
            current = await db.get(ArchiveSubmission, submission_id)
            await db.rollback()
            _raise_direct_review_membership_conflict(current)


async def _get_deleted_course_id_for_submission(
    db: AsyncSession,
    submission: ArchiveSubmission,
) -> int | None:
    if not submission.created_archive_id:
        return None

    archive = await db.get(Archive, submission.created_archive_id)
    if not archive or archive.deleted_at is None:
        return None

    course = await db.get(Course, archive.course_id)
    if not course or course.deleted_at is None:
        return None

    return course.id


def _normalize_course_name(value: str | None) -> str:
    return normalize_course_search_text(value)


def _normalize_match_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_course_match_text(value: str | None) -> str:
    return normalize_course_search_text(value)


def _normalized_text_expr(*values):
    present_values = [func.nullif(func.trim(value), "") for value in values]
    return func.lower(func.trim(func.coalesce(*present_values, "")))


def _is_admin_upload_submission(submission_data) -> bool:
    flag = getattr(submission_data, "is_admin_upload", None)
    if isinstance(submission_data, dict):
        flag = submission_data.get("is_admin_upload")
    review_note = getattr(submission_data, "review_note", None)
    if isinstance(submission_data, dict):
        review_note = submission_data.get("review_note")
    return bool(flag) or str(review_note or "").strip().lower() in {
        "管理員上傳",
        "admin upload",
    }


async def _ensure_or_create_requested_category(
    db: AsyncSession,
    key: str,
    name: str | None,
    label: str | None,
    icon: str | None,
    *,
    commit: bool,
) -> CourseCategoryConfig:
    category_key = _normalize_category_key(key)
    result = await db.execute(
        select(CourseCategoryConfig).where(CourseCategoryConfig.key == category_key)
    )
    category = result.scalar_one_or_none()
    if category:
        if not category.is_active:
            category.is_active = True
        return category

    max_order = (
        await db.execute(select(func.max(CourseCategoryConfig.order_index)))
    ).scalar_one_or_none()
    category = CourseCategoryConfig(
        key=category_key,
        name=(name or category_key).strip(),
        label=(label or name or category_key).strip(),
        icon=(icon or "pi pi-fw pi-book").strip(),
        order_index=(max_order or 0) + 1,
        is_active=True,
    )
    db.add(category)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(category)
    return category


async def _ensure_or_create_requested_category_for_approval(
    db: AsyncSession,
    key: str,
    name: str | None,
    label: str | None,
    icon: str | None,
) -> CourseCategoryConfig:
    category_key = _normalize_category_key(key)
    result = await db.execute(
        select(CourseCategoryConfig).where(CourseCategoryConfig.key == category_key)
    )
    category = result.scalar_one_or_none()
    if category:
        if category.deleted_at is not None or not category.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="已有同名分類在垃圾桶，請先復原或永久刪除後再通過。",
            )
        return category

    return await _ensure_or_create_requested_category(
        db,
        key=key,
        name=name,
        label=label,
        icon=icon,
        commit=False,
    )


async def _next_course_order_index(db: AsyncSession, category: str) -> int:
    max_order = (
        await db.execute(
            select(func.max(Course.order_index)).where(
                Course.category == category,
                Course.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return 0 if max_order is None else int(max_order) + 1


@router.post("/upload")
async def upload_archive(
    file: UploadFile,
    subject: str = Form(...),
    category: str = Form(...),
    professor: str = Form(...),
    archive_type: str = Form(...),
    has_answers: bool = Form(False),
    filename: str = Form(...),
    academic_year: int = Form(...),
    request_new_course: bool = Form(False),
    request_new_category: bool = Form(False),
    requested_course_name: str | None = Form(None),
    requested_category_key: str | None = Form(None),
    requested_category_name: str | None = Form(None),
    requested_category_label: str | None = Form(None),
    requested_category_icon: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Upload a new archive and create course if not exists
    """
    user_query = select(User).where(
        User.id == current_user.user_id, User.deleted_at.is_(None)
    )
    user_result = await db.execute(user_query)
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    request_new_course = bool(_unwrap_form_default(request_new_course, False))
    request_new_category = bool(_unwrap_form_default(request_new_category, False))
    requested_course_name = _unwrap_form_default(requested_course_name)
    requested_category_key = _unwrap_form_default(requested_category_key)
    requested_category_name = _unwrap_form_default(requested_category_name)
    requested_category_label = _unwrap_form_default(requested_category_label)
    requested_category_icon = _unwrap_form_default(requested_category_icon)

    subject = format_course_display_name(subject)
    category = _normalize_category_key(category)
    professor = professor.strip()
    requested_course_name = (
        format_course_display_name(requested_course_name)
        if requested_course_name
        else None
    )
    requested_category_key = (requested_category_key or "").strip() or None
    requested_category_name = (requested_category_name or "").strip() or None
    requested_category_label = (requested_category_label or "").strip() or None
    requested_category_icon = (requested_category_icon or "").strip() or None

    if request_new_category and not request_new_course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新增分類必須同時申請新增課程。",
        )

    if request_new_category:
        if not requested_category_key or not requested_category_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New category key and name are required",
            )
        requested_key = normalize_course_category_key(requested_category_key)
        if requested_key in RESERVED_LEGACY_COURSE_CATEGORY_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Legacy category keys are reserved",
            )
        category = _normalize_category_key(requested_key)
        requested_category_key = category
        if not requested_course_name:
            requested_course_name = subject
        request_new_course = True
    else:
        await _ensure_category(db, category)

    if request_new_course:
        if not requested_course_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New course name is required",
            )
        subject = requested_course_name
    else:
        subject = format_course_display_name(subject)

    course = None
    if current_user.is_admin:
        if request_new_category:
            await _ensure_or_create_requested_category(
                db,
                requested_category_key,
                requested_category_name,
                requested_category_label,
                requested_category_icon,
                commit=True,
            )
        query = select(Course).where(
            normalized_course_text_expr(Course.name)
            == normalize_course_search_text(subject),
            Course.category == category,
            Course.deleted_at.is_(None),
        )
        result = await db.execute(query)
        course = result.scalar_one_or_none()

        if not course:
            course = Course(
                name=subject,
                category=category,
                order_index=await _next_course_order_index(db, category),
            )
            db.add(course)
            await db.commit()
            await db.refresh(course)

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are allowed"
        )

    file_content = await file.read()
    file_size = len(file_content)

    max_size = 10 * 1024 * 1024  # 10MB
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 10MB limit",
        )

    _, file_extension = os.path.splitext(file.filename)
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    if current_user.is_admin:
        object_name = f"archives/{course.id}/{unique_filename}"
    else:
        object_name = f"archive-submissions/{current_user.user_id}/{unique_filename}"

    try:
        minio_client = get_minio_client()
        file_data = io.BytesIO(file_content)

        minio_client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_name,
            data=file_data,
            length=file_size,
            content_type="application/pdf",
        )

        if not current_user.is_admin:
            submission = ArchiveSubmission(
                subject=subject,
                category=category,
                name=filename,
                professor=professor,
                archive_type=archive_type,
                has_answers=has_answers,
                object_name=object_name,
                academic_year=academic_year,
                requested_course_name=requested_course_name
                if request_new_course
                else None,
                requested_category_key=requested_category_key
                if request_new_category
                else None,
                requested_category_name=requested_category_name
                if request_new_category
                else None,
                requested_category_label=requested_category_label
                if request_new_category
                else None,
                requested_category_icon=requested_category_icon
                if request_new_category
                else None,
                requester_id=current_user.user_id,
            )
            db.add(submission)
            await db.flush()
            await record_submission_event(db, submission)
            await db.commit()
            await db.refresh(submission)

            return {
                "success": True,
                "message": "File submitted for review",
                "is_admin_upload": False,
                "submission": {
                    "id": submission.id,
                    "name": submission.name,
                    "professor": submission.professor,
                    "archive_type": submission.archive_type,
                    "has_answers": submission.has_answers,
                    "status": submission.status,
                    "created_at": submission.created_at,
                    "file_size": file_size,
                    "is_admin_upload": False,
                },
            }

        archive = Archive(
            course_id=course.id,
            name=filename,
            professor=professor,
            archive_type=archive_type,
            has_answers=has_answers,
            object_name=object_name,
            academic_year=academic_year,
            uploader_id=current_user.user_id,
        )
        db.add(archive)
        await db.commit()
        await db.refresh(archive)

        submission = ArchiveSubmission(
            subject=subject,
            category=category,
            name=filename,
            professor=professor,
            archive_type=archive_type,
            has_answers=has_answers,
            object_name=object_name,
            academic_year=academic_year,
            requested_course_name=requested_course_name if request_new_course else None,
            requested_category_key=requested_category_key
            if request_new_category
            else None,
            requested_category_name=requested_category_name
            if request_new_category
            else None,
            requested_category_label=requested_category_label
            if request_new_category
            else None,
            requested_category_icon=requested_category_icon
            if request_new_category
            else None,
            status=SubmissionStatus.APPROVED,
            requester_id=current_user.user_id,
            reviewer_id=current_user.user_id,
            is_admin_upload=True,
            created_archive_id=archive.id,
            reviewed_at=datetime.now(UTC),
        )
        db.add(submission)
        await db.flush()
        await record_submission_event(db, submission)
        await db.commit()
        await db.refresh(submission)

        return {
            "success": True,
            "message": "File uploaded successfully",
            "is_admin_upload": True,
            "archive": {
                "id": archive.id,
                "name": archive.name,
                "professor": archive.professor,
                "archive_type": archive.archive_type,
                "has_answers": archive.has_answers,
                "created_at": archive.created_at,
                "file_size": file_size,
            },
            "submission": {
                "id": submission.id,
                "name": submission.name,
                "professor": submission.professor,
                "archive_type": submission.archive_type,
                "has_answers": submission.has_answers,
                "status": submission.status,
                "created_at": submission.created_at,
                "file_size": file_size,
                "is_admin_upload": True,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected archive upload failure",
            exc_info=redacted_exc_info(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {e!s}",
        )


@router.get("/submissions/me", response_model=list[ArchiveSubmissionRead])
async def list_my_archive_submissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(
        select(ArchiveSubmission)
        .where(ArchiveSubmission.requester_id == current_user.user_id)
        .order_by(ArchiveSubmission.created_at.desc())
    )
    return [
        ArchiveSubmissionRead.model_validate(submission).model_copy(
            update={"is_admin_upload": _is_admin_upload_submission(submission)}
        )
        for submission in result.scalars().all()
    ]


@router.delete("/submissions/{submission_id}")
async def delete_my_archive_submission(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        locked = await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=submission_id,
            operation="submission_delete",
        )
        submission = locked.submission(submission_id) if locked is not None else None
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )

        is_owner = submission.requester_id == current_user.user_id or (
            submission.owner_id is not None
            and submission.owner_id == current_user.user_id
        )
        if not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

        if (
            submission.deleted_at is not None
            or submission.status == SubmissionStatus.DELETED
        ):
            target_id = submission.id
            await db.rollback()
            return {
                "success": True,
                "id": target_id,
                "status": SubmissionStatus.DELETED,
                "changed": False,
            }

        source_status = resolve_archive_submission_delete_source_status(
            submission.status,
            operation="owner_delete",
        )
        if source_status != SubmissionStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only approved submissions can be deleted by users",
            )
        if submission.owner_self_delete_consumed:
            raise archive_submission_self_delete_consumed_error()

        result = await soft_delete_submission_with_linked_archive(
            db,
            submission=submission,
            user_id=current_user.user_id,
            reason="user deleted",
            linked_archive=(
                locked.archive(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            ),
            exact_link_only=True,
            consume_owner_self_delete=True,
        )

        await db.commit()

        return {
            "success": True,
            "id": submission.id,
            "status": submission.status,
            "changed": result["submissions"] == 1,
            "deleted": result,
            "message": "已刪除，管理員可於垃圾桶中恢復",
        }
    except Exception:
        await db.rollback()
        raise


@router.get("/admin/submissions", response_model=list[ArchiveSubmissionAdminRead])
async def list_archive_submissions_for_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    result = await db.execute(
        text("""
            SELECT
                archive_submissions.id,
                archive_submissions.subject,
                archive_submissions.category,
                archive_submissions.name,
                archive_submissions.academic_year,
                LOWER(CAST(archive_submissions.archive_type AS TEXT)) AS archive_type,
                archive_submissions.professor,
                archive_submissions.has_answers,
                archive_submissions.requested_course_name,
                archive_submissions.requested_category_key,
                archive_submissions.requested_category_name,
                archive_submissions.requested_category_label,
                archive_submissions.requested_category_icon,
                LOWER(CAST(archive_submissions.status AS TEXT)) AS status,
                archive_submissions.requester_id,
                archive_submissions.reviewer_id,
                reviewers.name AS reviewer_name,
                reviewers.email AS reviewer_email,
                archive_submissions.review_note,
                (
                    archive_submissions.is_admin_upload
                    OR LOWER(TRIM(COALESCE(archive_submissions.review_note, ''))) IN ('管理員上傳', 'admin upload')
                ) AS is_admin_upload,
                archive_submissions.created_archive_id,
                archive_submissions.lifecycle_reason,
                archive_submissions.deleted_at,
                (archives.deleted_at IS NOT NULL) AS linked_archive_deleted,
                (courses.deleted_at IS NOT NULL) AS linked_course_deleted,
                archive_submissions.created_at,
                archive_submissions.reviewed_at,
                requesters.name AS requester_name,
                requesters.email AS requester_email
            FROM archive_submissions
            LEFT JOIN users AS requesters
                ON requesters.id = archive_submissions.requester_id
            LEFT JOIN users AS reviewers
                ON reviewers.id = archive_submissions.reviewer_id
            LEFT JOIN archives
                ON archives.id = archive_submissions.created_archive_id
            LEFT JOIN courses
                ON courses.id = archives.course_id
            ORDER BY
                CASE LOWER(CAST(archive_submissions.status AS TEXT))
                    WHEN 'pending' THEN 1
                    WHEN 'approved' THEN 2
                    WHEN 'rejected' THEN 3
                    WHEN 'takedown' THEN 4
                    WHEN 'deleted' THEN 5
                    ELSE 99
                END,
                archive_submissions.created_at DESC
        """)
    )
    archive_submissions = []
    skipped_submission_count = 0
    for row in result.all():
        row_dict = dict(row._mapping)
        normalized_status = _resolve_submission_actual_status(
            row_dict.get("status"),
            deleted_at=row_dict.get("deleted_at"),
        )
        if normalized_status is None:
            skipped_submission_count += 1
            continue

        row_dict["status"] = normalized_status
        if row_dict.get("subject"):
            row_dict["subject"] = format_course_display_name(row_dict["subject"])
        if row_dict.get("requested_course_name"):
            row_dict["requested_course_name"] = format_course_display_name(
                row_dict["requested_course_name"]
            )
        if row_dict.get("requested_category_name"):
            row_dict["requested_category_name"] = format_course_display_name(
                row_dict["requested_category_name"]
            )
        try:
            row_dict["is_admin_upload"] = bool(row_dict.get("is_admin_upload"))
            archive_submissions.append(_serialize_archive_submission_admin(row_dict))
        except Exception as exc:
            skipped_submission_count += 1
            logger.warning(
                "Skipping archive submission %s due to invalid payload",
                row_dict.get("id"),
                exc_info=redacted_exc_info(exc),
            )

    if skipped_submission_count:
        logger.info(
            "Skipped %s archive submissions in admin list due to unsupported/invalid status",
            skipped_submission_count,
        )
    return archive_submissions


@router.get("/admin/submission-statistics", response_model=SubmissionStatisticsRead)
async def get_archive_submission_statistics(
    mode: str = Query("time"),
    range_key: str = Query("24h", alias="range"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    config = SUBMISSION_RANGE_CONFIG.get(range_key)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid range"
        )
    expected_mode = config[0]
    if mode not in {"time", "date"} or mode != expected_mode:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid mode"
        )

    now_utc = datetime.now(UTC)
    _, bucket_minutes, _, range_start, range_end = get_submission_statistics_window(
        range_key, now_utc
    )
    bucket_seconds = bucket_minutes * 60
    bucket_epoch = cast(
        func.floor(
            (
                func.extract("epoch", ArchiveSubmissionEvent.submitted_at)
                - range_start.timestamp()
            )
            / bucket_seconds
        ),
        BigInteger,
    )
    result = await db.execute(
        select(
            bucket_epoch.label("bucket_index"), func.count(ArchiveSubmissionEvent.id)
        )
        .where(
            ArchiveSubmissionEvent.submitted_at >= range_start,
            ArchiveSubmissionEvent.submitted_at < range_end,
            ArchiveSubmissionEvent.submitted_at <= now_utc,
        )
        .group_by(bucket_epoch)
    )
    counts_by_bucket_start = {
        range_start + timedelta(seconds=int(bucket_index) * bucket_seconds): int(count)
        for bucket_index, count in result.all()
    }
    return build_submission_statistics(
        range_key=range_key,
        counts_by_bucket_start=counts_by_bucket_start,
        now=now_utc,
    )


@router.get(
    "/admin/submissions/{submission_id}/comparisons",
    response_model=list[ArchiveSubmissionComparisonRead],
)
async def list_archive_submission_comparisons(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )

    course_name = normalize_first_course_search_text(
        submission.requested_course_name,
        submission.subject,
    )
    category_key = _normalize_match_text(
        submission.requested_category_key or submission.category
    )
    exam_name = _normalize_match_text(submission.name)
    professor = _normalize_match_text(submission.professor)
    if (
        not course_name
        or not category_key
        or not exam_name
        or submission.academic_year is None
    ):
        return []

    current_archive = (
        await db.get(Archive, submission.created_archive_id)
        if submission.created_archive_id
        else None
    )
    current_course_id = current_archive.course_id if current_archive else None
    comparison_archive = aliased(Archive)
    comparable_statuses = [
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
        SubmissionStatus.TAKEDOWN,
    ]
    fallback_course_condition = and_(
        ArchiveSubmission.created_archive_id.is_(None),
        normalized_course_text_expr(
            ArchiveSubmission.requested_course_name, ArchiveSubmission.subject
        )
        == course_name,
        _normalized_text_expr(
            ArchiveSubmission.requested_category_key, ArchiveSubmission.category
        )
        == category_key,
    )
    course_condition = (
        or_(
            comparison_archive.course_id == current_course_id, fallback_course_condition
        )
        if current_course_id is not None
        else and_(
            normalized_course_text_expr(
                ArchiveSubmission.requested_course_name, ArchiveSubmission.subject
            )
            == course_name,
            _normalized_text_expr(
                ArchiveSubmission.requested_category_key, ArchiveSubmission.category
            )
            == category_key,
        )
    )
    query = (
        select(ArchiveSubmission, User.name, User.email)
        .outerjoin(User, User.id == ArchiveSubmission.requester_id)
        .outerjoin(
            comparison_archive,
            comparison_archive.id == ArchiveSubmission.created_archive_id,
        )
        .where(
            ArchiveSubmission.id != submission.id,
            ArchiveSubmission.deleted_at.is_(None),
            ArchiveSubmission.status.in_(comparable_statuses),
            course_condition,
            _normalized_text_expr(ArchiveSubmission.name) == exam_name,
            _normalized_text_expr(ArchiveSubmission.professor) == professor,
            ArchiveSubmission.academic_year == submission.academic_year,
        )
    )
    result = await db.execute(query)
    status_order = {
        SubmissionStatus.PENDING: 1,
        SubmissionStatus.APPROVED: 2,
        SubmissionStatus.TAKEDOWN: 3,
    }
    rows = []
    for comparison, requester_name, requester_email in result.all():
        normalized_status = _resolve_submission_actual_status(
            comparison.status,
            deleted_at=comparison.deleted_at,
        )
        if normalized_status not in comparable_statuses:
            continue

        payload = ArchiveSubmissionRead.model_validate(comparison).model_dump()
        payload["requester_name"] = requester_name
        payload["requester_email"] = requester_email
        payload["status"] = normalized_status
        payload["can_takedown"] = (
            ArchiveSubmissionAdminAction.TAKEDOWN
            in available_archive_submission_admin_actions(normalized_status)
        )
        rows.append(payload)

    rows.sort(
        key=lambda item: (
            status_order.get(item["status"], 99),
            -(item["created_at"].timestamp() if item.get("created_at") else 0),
        )
    )
    return [ArchiveSubmissionComparisonRead.model_validate(item) for item in rows]


@router.get("/admin/submissions/{submission_id}/preview-file")
async def get_archive_submission_preview_file(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )

    try:
        response = get_minio_client().get_object(
            settings.MINIO_BUCKET_NAME,
            submission.object_name,
        )
        data = response.read()
        response.close()
        response.release_conn()
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "archive_file_missing",
                    "message": "此筆考古題的 PDF 檔案缺失，無法預覽或下載。",
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load submission preview file from object storage",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load submission preview file from object storage",
        ) from exc

    return StreamingResponse(
        iter([data]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{submission.name}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "/admin/submissions/{submission_id}",
    response_model=ArchiveSubmissionAdminRead,
)
async def update_archive_submission_for_admin(
    submission_id: int,
    submission_data: ArchiveSubmissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        locked = await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=submission_id,
            operation="submission_edit",
        )
        submission = locked.submission(submission_id) if locked is not None else None
        if submission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )
        _ensure_archive_submission_editable(submission)

        if submission_data.subject is not None:
            submission.subject = format_course_display_name(submission_data.subject)
        if submission_data.category is not None:
            if not (
                submission_data.requested_category_key
                or submission.requested_category_key
            ):
                await _ensure_category(db, submission_data.category)
            submission.category = submission_data.category
        if submission_data.name is not None:
            submission.name = submission_data.name
        if submission_data.academic_year is not None:
            submission.academic_year = submission_data.academic_year
        if submission_data.archive_type is not None:
            submission.archive_type = submission_data.archive_type
        if submission_data.professor is not None:
            submission.professor = submission_data.professor
        if submission_data.has_answers is not None:
            submission.has_answers = submission_data.has_answers
        if submission_data.requested_course_name is not None:
            submission.requested_course_name = (
                format_course_display_name(submission_data.requested_course_name)
                or None
            )
        if submission_data.requested_category_key is not None:
            key = submission_data.requested_category_key.strip()
            submission.requested_category_key = (
                _normalize_category_key(key) if key else None
            )
        if submission_data.requested_category_name is not None:
            submission.requested_category_name = (
                submission_data.requested_category_name.strip() or None
            )
        if submission_data.requested_category_label is not None:
            submission.requested_category_label = (
                submission_data.requested_category_label.strip() or None
            )
        if submission_data.requested_category_icon is not None:
            submission.requested_category_icon = (
                submission_data.requested_category_icon.strip() or None
            )

        await db.commit()
        await db.refresh(submission)
        return _serialize_archive_submission_admin(submission)
    except Exception:
        await db.rollback()
        raise


@router.post(
    "/admin/submissions/{submission_id}/approve",
    response_model=ArchiveSubmissionActionRead,
)
async def approve_archive_submission(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        lock_context = await _lock_direct_review_context(
            db,
            submission_id=submission_id,
            action=ArchiveSubmissionReviewAction.APPROVE,
        )
        submission, no_op_response = await _prepare_direct_archive_submission_review(
            db,
            submission=lock_context.submission,
            decision=decision,
            action=ArchiveSubmissionReviewAction.APPROVE,
        )
        if no_op_response is not None:
            return no_op_response

        formatted_course_name = format_course_display_name(
            submission.requested_course_name or submission.subject
        )
        course_name = _normalize_course_name(formatted_course_name)
        category_key = submission.requested_category_key or submission.category

        if not course_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid course name",
            )

        if submission.requested_category_key:
            await _ensure_or_create_requested_category_for_approval(
                db,
                submission.requested_category_key,
                submission.requested_category_name,
                submission.requested_category_label,
                submission.requested_category_icon,
            )
        else:
            await _ensure_category(db, category_key)

        course = (
            await db.execute(
                select(Course).where(
                    normalized_course_text_expr(Course.name) == course_name,
                    Course.category == category_key,
                    Course.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if not course:
            deleted_course = (
                await db.execute(
                    select(Course).where(
                        normalized_course_text_expr(Course.name) == course_name,
                        Course.category == category_key,
                        Course.deleted_at.is_not(None),
                    )
                )
            ).scalar_one_or_none()
            if deleted_course:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="已有同名課程在垃圾桶，請先復原或永久刪除後再通過。",
                )

            order_index = await _next_course_order_index(db, category_key)
            course = Course(
                name=formatted_course_name,
                category=category_key,
                order_index=order_index,
            )
            db.add(course)
            await db.flush()
            await db.refresh(course)

        archive = (
            await db.get(Archive, submission.created_archive_id)
            if submission.created_archive_id
            else None
        )
        if archive:
            archive.course_id = course.id
            archive.name = submission.name
            archive.academic_year = submission.academic_year
            archive.archive_type = submission.archive_type
            archive.professor = submission.professor
            archive.has_answers = submission.has_answers
            archive.object_name = submission.object_name
            archive.uploader_id = submission.requester_id
            archive.deleted_at = None
            archive.updated_at = datetime.now(UTC)
        else:
            archive = Archive(
                course_id=course.id,
                name=submission.name,
                academic_year=submission.academic_year,
                archive_type=submission.archive_type,
                professor=submission.professor,
                has_answers=submission.has_answers,
                object_name=submission.object_name,
                uploader_id=submission.requester_id,
            )
        db.add(archive)
        await db.flush()
        await db.refresh(archive)

        await ensure_archive_submission_link_available(
            db,
            submission_id=submission.id,
            current_archive_id=submission.created_archive_id,
            target_archive_id=archive.id,
            operation="approval",
        )

        with capture_submission_status_notification_identity(
            db,
            submission,
            SubmissionStatus.APPROVED,
        ):
            submission.status = SubmissionStatus.APPROVED
            submission.reviewer_id = current_user.user_id
            submission.review_note = decision.note if decision else None
            submission.created_archive_id = archive.id
            submission.reviewed_at = datetime.now(UTC)
            await enqueue_submission_status_notification(
                db,
                submission,
                SubmissionStatus.APPROVED,
            )
        await db.flush()
        await db.refresh(submission)
        await db.commit()
        await db.refresh(submission)
        return _serialize_archive_submission_action(submission, changed=True)
    except IntegrityError as error:
        await db.rollback()
        if is_archive_submission_link_unique_violation(error):
            raise archive_submission_link_conflict() from error
        raise
    except Exception:
        await db.rollback()
        raise


@router.post(
    "/admin/submissions/{submission_id}/reject",
    response_model=ArchiveSubmissionActionRead,
)
async def reject_archive_submission(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        lock_context = await _lock_direct_review_context(
            db,
            submission_id=submission_id,
            action=ArchiveSubmissionReviewAction.REJECT,
        )
        submission, no_op_response = await _prepare_direct_archive_submission_review(
            db,
            submission=lock_context.submission,
            decision=decision,
            action=ArchiveSubmissionReviewAction.REJECT,
        )
        if no_op_response is not None:
            return no_op_response

        with capture_submission_status_notification_identity(
            db,
            submission,
            SubmissionStatus.REJECTED,
        ):
            submission.status = SubmissionStatus.REJECTED
            submission.reviewer_id = current_user.user_id
            submission.review_note = decision.note if decision else None
            submission.reviewed_at = datetime.now(UTC)
            await enqueue_submission_status_notification(
                db,
                submission,
                SubmissionStatus.REJECTED,
            )
        await db.commit()
        await db.refresh(submission)
        return _serialize_archive_submission_action(submission, changed=True)
    except Exception:
        await db.rollback()
        raise


@router.post(
    "/admin/submissions/{submission_id}/takedown",
    response_model=ArchiveSubmissionActionRead,
)
async def takedown_archive_submission(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        lock_context = await _lock_direct_review_context(
            db,
            submission_id=submission_id,
            action=ArchiveSubmissionReviewAction.TAKEDOWN,
        )
        submission, no_op_response = await _prepare_direct_archive_submission_review(
            db,
            submission=lock_context.submission,
            decision=decision,
            action=ArchiveSubmissionReviewAction.TAKEDOWN,
        )
        if no_op_response is not None:
            return no_op_response

        await take_down_archive_submission(
            db,
            submission,
            reviewer_id=current_user.user_id,
            note=decision.note if decision else None,
        )
        await db.commit()
        await db.refresh(submission)
        return _serialize_archive_submission_action(submission, changed=True)
    except Exception:
        await db.rollback()
        raise


@router.post(
    "/admin/submissions/{submission_id}/republish",
    response_model=ArchiveSubmissionActionRead,
)
async def republish_archive_submission_endpoint(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        lock_context = await _lock_direct_review_context(
            db,
            submission_id=submission_id,
            action=ArchiveSubmissionReviewAction.REPUBLISH,
        )
        submission, no_op_response = await _prepare_direct_archive_submission_review(
            db,
            submission=lock_context.submission,
            decision=decision,
            action=ArchiveSubmissionReviewAction.REPUBLISH,
        )
        if no_op_response is not None:
            return no_op_response

        if submission.created_archive_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法重新上架：找不到對應考古題。",
            )

        archive = await db.get(Archive, submission.created_archive_id)
        if not archive:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="無法重新上架：關聯考古題不存在",
            )
        if archive.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法重新上架：關聯考古題已下架，請先復原考古題。",
            )

        course = await db.get(Course, archive.course_id)
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="無法重新上架：關聯課程不存在",
            )
        if course.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法重新上架：關聯課程已在垃圾桶，請先復原原課程。",
            )

        if submission.lifecycle_reason == LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法復原：關聯考古題已永久刪除",
            )
        if submission.lifecycle_reason == LIFECYCLE_ARCHIVE_TRASHED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法重新上架：此投稿先前因關聯考古題刪除而下架",
            )

        if is_course_trash_lifecycle_reason(submission.lifecycle_reason):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="無法重新上架：此投稿先前因關聯課程刪除而下架",
            )

        await republish_archive_submission(
            db,
            submission,
            reviewer_id=current_user.user_id,
            note=decision.note if decision else None,
        )
        await db.commit()
        await db.refresh(submission)
        return _serialize_archive_submission_action(submission, changed=True)
    except Exception:
        await db.rollback()
        raise


@router.delete("/admin/submissions/{submission_id}")
async def delete_archive_submission_for_admin(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    try:
        locked = await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=submission_id,
            operation="submission_delete",
        )
        submission = locked.submission(submission_id) if locked is not None else None
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )

        if (
            submission.deleted_at is not None
            or submission.status == SubmissionStatus.DELETED
        ):
            target_id = submission.id
            await db.rollback()
            return {
                "success": True,
                "id": target_id,
                "changed": False,
                "deleted": {
                    "archives": 0,
                    "submissions": 0,
                    "warnings": [],
                },
            }

        resolve_archive_submission_delete_source_status(
            submission.status,
            operation="admin_delete",
        )
        result = await soft_delete_submission_with_linked_archive(
            db,
            submission=submission,
            user_id=current_user.user_id,
            reason="admin deleted",
            linked_archive=(
                locked.archive(submission.created_archive_id)
                if submission.created_archive_id is not None
                else None
            ),
            exact_link_only=True,
        )
        changed = result["submissions"] == 1
        if changed:
            submission.reviewer_id = current_user.user_id
            submission.reviewed_at = datetime.now(UTC)
        await db.commit()
        return {
            "success": True,
            "id": submission.id,
            "changed": changed,
            "deleted": result,
        }
    except Exception:
        await db.rollback()
        raise
