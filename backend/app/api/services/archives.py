import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from pydantic import ValidationError
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
from app.db import session as db_session
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
    ArchiveWish,
    Course,
    CourseCategoryConfig,
    OwnerPendingArchiveSubmissionEdit,
    OwnerPendingArchiveSubmissionRead,
    PermanentDeletionStatus,
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
from app.services.archive_submission_owner_pending import (
    acquire_owner_pending_edit_locks,
    ensure_source_wish_target_matches,
    normalized_owner_exam_name,
    require_owner_pending_submission,
)
from app.services.archive_submission_review_revision import (
    compute_archive_submission_review_revision,
    review_revision_matches,
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
from app.services.pdf_security import PdfValidationError, validated_pdf_upload
from app.services.permanent_deletion import (
    enqueue_superseded_archive_submission_object_cleanup,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_storage import (
    ExactVersionMinioAdapter,
    StorageSafetyError,
)
from app.services.wish_fulfillment import enqueue_new_wish_fulfillment_notifications
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


async def _ensure_category(
    db: AsyncSession, category_key: str
) -> CourseCategoryConfig:
    category_key = canonicalize_course_category_key(category_key)
    result = await db.execute(
        select(CourseCategoryConfig).where(
            CourseCategoryConfig.key == category_key,
            CourseCategoryConfig.is_active.is_(True),
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course category does not exist",
        )
    return category


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


async def _load_current_archive_projection(db: AsyncSession, submission) -> dict | None:
    created_archive_id = (
        submission.get("created_archive_id")
        if isinstance(submission, dict)
        else getattr(submission, "created_archive_id", None)
    )
    if created_archive_id is None:
        return None
    row = (
        await db.execute(
            select(Archive, Course)
            .join(Course, Course.id == Archive.course_id)
            .where(Archive.id == created_archive_id)
        )
    ).one_or_none()
    if row is None:
        return None
    archive, course = row
    return {
        "id": archive.id,
        "course_id": course.id,
        "course_name": format_course_display_name(course.name),
        "course_name_en": course.name_en,
        "course_category": course.category,
        "name": archive.name,
        "academic_year": archive.academic_year,
        "archive_type": archive.archive_type,
        "professor": archive.professor,
        "has_answers": archive.has_answers,
        "is_deleted": archive.deleted_at is not None,
        "course_is_deleted": course.deleted_at is not None,
    }


async def _serialize_archive_submission_admin(
    db: AsyncSession,
    submission,
) -> ArchiveSubmissionAdminRead:
    raw_payload = dict(submission) if isinstance(submission, dict) else submission
    base = ArchiveSubmissionRead.model_validate(raw_payload)
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
    if isinstance(raw_payload, dict) and "current_archive" in raw_payload:
        payload["current_archive"] = raw_payload["current_archive"]
    else:
        payload["current_archive"] = await _load_current_archive_projection(
            db, submission
        )
    payload["status"] = actual_status
    payload["available_actions"] = available_archive_submission_admin_actions(
        actual_status
    )
    payload["review_revision"] = (
        raw_payload.get("review_revision")
        if isinstance(raw_payload, dict) and raw_payload.get("review_revision")
        else compute_archive_submission_review_revision(raw_payload)
    )
    return ArchiveSubmissionAdminRead.model_validate(payload)


async def _serialize_archive_submission_action(
    db: AsyncSession,
    submission,
    *,
    changed: bool,
) -> ArchiveSubmissionActionRead:
    payload = (await _serialize_archive_submission_admin(db, submission)).model_dump()
    payload["changed"] = changed
    return ArchiveSubmissionActionRead.model_validate(payload)


def _normalize_archive_submission_update(
    submission_data: ArchiveSubmissionUpdate,
) -> dict[str, object | None]:
    values: dict[str, object | None] = {}
    for field in submission_data.model_fields_set:
        value = getattr(submission_data, field)
        if field != "review_note" and value is None:
            continue
        if field == "subject":
            value = format_course_display_name(value)
        elif field == "requested_course_name":
            value = format_course_display_name(value) or None
        elif field in {
            "requested_course_name_en",
            "requested_category_name",
            "requested_category_name_en",
            "requested_category_label",
            "requested_category_label_en",
            "requested_category_icon",
            "review_note",
        }:
            value = value.strip() if value is not None else None
            value = value or None
        elif field == "requested_category_key":
            key = value.strip()
            value = _normalize_category_key(key) if key else None
        values[field] = value
    return values


def _sync_archive_metadata_from_submission(
    archive: Archive,
    submission: ArchiveSubmission,
) -> None:
    archive.name = submission.name
    archive.academic_year = submission.academic_year
    archive.archive_type = submission.archive_type
    archive.professor = submission.professor
    archive.has_answers = submission.has_answers
    archive.updated_at = datetime.now(UTC)


def _ensure_archive_submission_editable(
    submission: ArchiveSubmission,
    changed_fields: set[str],
) -> None:
    actual_status = _resolve_submission_actual_status(
        submission.status,
        deleted_at=submission.deleted_at,
    )
    if actual_status == SubmissionStatus.DELETED or (
        actual_status == SubmissionStatus.APPROVED
        and changed_fields - {"review_note"}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=dict(ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL),
        )
    if actual_status == SubmissionStatus.APPROVED:
        return
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

    if action in {
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionReviewAction.REJECT,
    }:
        expected_revision = decision.expected_revision if decision else None
        if not expected_revision:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail={
                    "code": "archive_submission_revision_precondition_required",
                    "message": "請重新載入投稿內容後再執行審核。",
                    "reload_required": True,
                },
            )
        current_revision = compute_archive_submission_review_revision(submission)
        if not review_revision_matches(expected_revision, current_revision):
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "archive_submission_stale_revision",
                    "message": "投稿內容已更新，請重新檢視後再審核。",
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
        response = await _serialize_archive_submission_action(
            db,
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
) -> tuple[ArchiveLifecycleLockPlan, dict[str, int | str | bool | None]] | None:
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
    uses_submission_parent = (
        action == ArchiveSubmissionReviewAction.APPROVE and archive is None
    )
    approval_scope: str | None = None
    if uses_submission_parent:
        approval_scope = await archive_lifecycle_locks.acquire_approval_namespace_mutex(
            db,
            category_key=category_key,
            course_name=course_name,
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
    if uses_submission_parent:
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
        "uses_submission_parent": uses_submission_parent,
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
        if (
            action == ArchiveSubmissionReviewAction.APPROVE
            and metadata["uses_submission_parent"]
            and submission is not None
        ):
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
    name_en: str | None,
    label: str | None,
    label_en: str | None,
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
        name_en=(name_en or "").strip() or None,
        label=(label or name or category_key).strip(),
        label_en=(label_en or "").strip() or None,
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
    name_en: str | None,
    label: str | None,
    label_en: str | None,
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
        name_en=name_en,
        label=label,
        label_en=label_en,
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


async def _committed_upload_reference_count(object_name: str) -> int:
    async with db_session.AsyncSessionLocal() as fresh_db:
        archive_count = (
            await fresh_db.execute(
                select(func.count(Archive.id)).where(Archive.object_name == object_name)
            )
        ).scalar_one()
        submission_count = (
            await fresh_db.execute(
                select(func.count(ArchiveSubmission.id)).where(
                    ArchiveSubmission.object_name == object_name
                )
            )
        ).scalar_one()
        return int(archive_count) + int(submission_count)


async def _compensate_failed_upload(object_name: str, minio_client) -> None:
    try:
        reference_count = await _committed_upload_reference_count(object_name)
    except Exception as exc:  # noqa: BLE001 - uncertain authority must retain storage
        logger.error(
            "Archive upload compensation retained object: fresh database authority unavailable (%s)",
            type(exc).__name__,
        )
        return

    if reference_count != 0:
        logger.info(
            "Archive upload compensation retained object: committed reference exists"
        )
        return

    try:
        await asyncio.to_thread(
            minio_client.remove_object,
            settings.MINIO_BUCKET_NAME,
            object_name,
        )
    except Exception as exc:  # noqa: BLE001 - cleanup is best-effort after failed commit
        logger.error(
            "Archive upload compensation could not remove unreferenced object (%s)",
            type(exc).__name__,
        )


async def _rollback_failed_upload(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception as exc:  # noqa: BLE001 - preserve original upload failure
        logger.error(
            "Archive upload rollback failed before compensation (%s)",
            type(exc).__name__,
        )


def _owner_pending_submission_read(
    submission: ArchiveSubmission,
    *,
    course_id: int,
) -> OwnerPendingArchiveSubmissionRead:
    return OwnerPendingArchiveSubmissionRead(
        submission_id=submission.id,
        course_id=course_id,
        name=submission.name,
        academic_year=submission.academic_year,
        archive_type=submission.archive_type,
        professor=submission.professor,
        has_answers=submission.has_answers,
        created_at=submission.created_at,
    )


async def _apply_owner_pending_submission_edit(
    *,
    submission_id: int,
    edit: OwnerPendingArchiveSubmissionEdit,
    staged,
    current_user: User,
    db: AsyncSession,
) -> OwnerPendingArchiveSubmissionRead:
    minio_client = None
    storage = None
    new_object_name: str | None = None
    new_object_written = False
    cleanup_operation_id: int | None = None
    committed = False
    try:
        locked = await acquire_owner_pending_edit_locks(
            db,
            submission_id=submission_id,
            course_id=edit.course_id,
        )
        submission = require_owner_pending_submission(
            locked.submission(submission_id) if locked is not None else None,
            current_user=current_user,
        )
        course = locked.course(edit.course_id) if locked is not None else None
        if course is None or course.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found",
            )

        exam_name = normalized_owner_exam_name(edit)
        await ensure_source_wish_target_matches(
            db,
            submission=submission,
            course=course,
            professor=edit.professor,
            archive_type=edit.archive_type,
            name=exam_name,
        )

        old_object_name: str | None = None
        old_version_id: str | None = None
        if staged is not None:
            old_object_name = (submission.object_name or "").strip()
            if not old_object_name.startswith("archive-submissions/"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "owner_pending_storage_identity_unavailable",
                        "message": "The current submission file identity is not replaceable.",
                    },
                )
            minio_client = get_minio_client()
            storage = ExactVersionMinioAdapter(
                minio_client,
                bucket_name=settings.MINIO_BUCKET_NAME,
            )
            try:
                old_version_id = await asyncio.to_thread(
                    storage.capture_version_id,
                    old_object_name,
                )
            except StorageSafetyError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "owner_pending_storage_identity_unavailable",
                        "message": "Unable to verify the current PDF version safely.",
                    },
                ) from exc

            new_object_name = (
                f"archive-submissions/{current_user.user_id}/{uuid.uuid4()}.pdf"
            )
            with staged.path.open("rb") as file_data:
                put_task = asyncio.create_task(
                    asyncio.to_thread(
                        minio_client.put_object,
                        bucket_name=settings.MINIO_BUCKET_NAME,
                        object_name=new_object_name,
                        data=file_data,
                        length=staged.size,
                        content_type="application/pdf",
                    )
                )
                try:
                    await asyncio.shield(put_task)
                except asyncio.CancelledError:
                    try:
                        await put_task
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Owner pending replacement cancelled before storage result (%s)",
                            type(exc).__name__,
                        )
                    else:
                        new_object_written = True
                    raise
            new_object_written = True

        submission.subject = format_course_display_name(course.name)
        submission.category = canonicalize_course_category_key(course.category)
        submission.requested_course_name_en = (course.name_en or "").strip() or None
        submission.professor = edit.professor
        submission.academic_year = edit.academic_year
        submission.archive_type = edit.archive_type
        submission.name = exam_name
        submission.has_answers = edit.has_answers
        if staged is not None:
            submission.object_name = new_object_name
            cleanup = await enqueue_superseded_archive_submission_object_cleanup(
                db,
                submission_id=submission.id,
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_key=old_object_name,
                version_id=old_version_id,
                idempotency_key=(
                    f"owner-pending-replacement:{submission.id}:{uuid.uuid4().hex}"
                ),
                requested_by_user_id=current_user.user_id,
            )
            cleanup_operation_id = int(cleanup.id)

        await db.commit()
        committed = True
    except asyncio.CancelledError:
        await _rollback_failed_upload(db)
        if new_object_written and new_object_name and minio_client is not None:
            await _compensate_failed_upload(new_object_name, minio_client)
        raise
    except HTTPException:
        await _rollback_failed_upload(db)
        if new_object_written and new_object_name and minio_client is not None:
            await _compensate_failed_upload(new_object_name, minio_client)
        raise
    except Exception as exc:
        await _rollback_failed_upload(db)
        if new_object_written and new_object_name and minio_client is not None:
            await _compensate_failed_upload(new_object_name, minio_client)
        logger.error(
            "Owner pending submission edit failed (%s)",
            type(exc).__name__,
            exc_info=redacted_exc_info(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to edit pending submission",
        ) from exc

    if committed and cleanup_operation_id is not None and storage is not None:
        try:
            cleanup_status = await process_one_permanent_deletion(
                db,
                operation_id=cleanup_operation_id,
                storage=storage,
            )
            if cleanup_status != PermanentDeletionStatus.COMPLETED:
                logger.warning(
                    "Superseded submission PDF cleanup remains durable",
                    extra={
                        "event": "superseded_submission_pdf_cleanup_pending",
                        "operation_id": cleanup_operation_id,
                        "status": cleanup_status.value,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - committed edit remains authoritative
            await db.rollback()
            logger.error(
                "Immediate superseded submission PDF cleanup failed (%s)",
                type(exc).__name__,
                extra={
                    "event": "superseded_submission_pdf_cleanup_failed",
                    "operation_id": cleanup_operation_id,
                },
            )

    return _owner_pending_submission_read(submission, course_id=edit.course_id)


@router.post("/upload")
async def upload_archive(
    file: UploadFile,
    subject: str = Form(...),
    category: str = Form(...),
    course_id: int | None = Form(None),
    professor: str = Form(...),
    archive_type: str = Form(...),
    has_answers: bool = Form(False),
    filename: str = Form(...),
    academic_year: int = Form(...),
    request_new_course: bool = Form(False),
    request_new_category: bool = Form(False),
    requested_course_name: str | None = Form(None),
    requested_course_name_en: str | None = Form(None),
    requested_category_key: str | None = Form(None),
    requested_category_name: str | None = Form(None),
    requested_category_name_en: str | None = Form(None),
    requested_category_label: str | None = Form(None),
    requested_category_label_en: str | None = Form(None),
    requested_category_icon: str | None = Form(None),
    source_wish_id: int | None = Form(None),
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
    course_id = _unwrap_form_default(course_id)
    requested_course_name = _unwrap_form_default(requested_course_name)
    requested_course_name_en = _unwrap_form_default(requested_course_name_en)
    requested_category_key = _unwrap_form_default(requested_category_key)
    requested_category_name = _unwrap_form_default(requested_category_name)
    requested_category_name_en = _unwrap_form_default(requested_category_name_en)
    requested_category_label = _unwrap_form_default(requested_category_label)
    requested_category_label_en = _unwrap_form_default(requested_category_label_en)
    requested_category_icon = _unwrap_form_default(requested_category_icon)
    source_wish_id = _unwrap_form_default(source_wish_id)

    subject = format_course_display_name(subject)
    category = _normalize_category_key(category)
    professor = professor.strip()
    requested_course_name = (
        format_course_display_name(requested_course_name)
        if requested_course_name
        else None
    )
    requested_course_name_en = (requested_course_name_en or "").strip() or None
    requested_category_key = (requested_category_key or "").strip() or None
    requested_category_name = (requested_category_name or "").strip() or None
    requested_category_name_en = (requested_category_name_en or "").strip() or None
    requested_category_label = (requested_category_label or "").strip() or None
    requested_category_label_en = (requested_category_label_en or "").strip() or None
    requested_category_icon = (requested_category_icon or "").strip() or None

    if request_new_category and not request_new_course:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新增分類必須同時申請新增課程。",
        )

    category_config = None
    if request_new_category:
        if not all(
            (
                requested_category_key,
                requested_category_name,
                requested_category_name_en,
                requested_category_label,
                requested_category_label_en,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New category key, bilingual names, and bilingual labels are required",
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
        category_config = await _ensure_category(db, category)

    if request_new_course:
        if not requested_course_name or not requested_course_name_en:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New course Chinese and English names are required",
            )
        subject = requested_course_name
    else:
        subject = format_course_display_name(subject)

    snapshot_course_name_en = requested_course_name_en if request_new_course else None
    snapshot_category_name_en = (
        requested_category_name_en
        if request_new_category
        else ((category_config.name_en or "").strip() or None if category_config else None)
    )
    snapshot_category_label_en = (
        requested_category_label_en
        if request_new_category
        else ((category_config.label_en or "").strip() or None if category_config else None)
    )
    if not request_new_course:
        course_conditions = [
            Course.category == category,
            Course.deleted_at.is_(None),
        ]
        if course_id is not None:
            course_conditions.append(Course.id == course_id)
        else:
            course_conditions.append(
                normalized_course_text_expr(Course.name)
                == normalize_course_search_text(subject)
            )
        course_result = await db.execute(select(Course).where(*course_conditions))
        canonical_course = course_result.scalar_one_or_none()
        if not canonical_course:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Course does not exist",
            )
        subject = canonical_course.name
        snapshot_course_name_en = (canonical_course.name_en or "").strip() or None

    if source_wish_id is not None:
        wish = await db.get(ArchiveWish, source_wish_id)
        if wish is None:
            raise HTTPException(status_code=404, detail="Wish not found")
        course_matches = (
            wish.course_id == canonical_course.id
            if not request_new_course and wish.course_id is not None
            else normalize_course_search_text(
                wish.requested_course_name or wish.subject
            )
            == normalize_course_search_text(requested_course_name or subject)
        )
        target_matches = all(
            (
                course_matches,
                _normalize_match_text(wish.category) == _normalize_match_text(category),
                _normalize_match_text(wish.professor)
                == _normalize_match_text(professor),
                wish.archive_type.value == archive_type,
                _normalize_match_text(wish.name) == _normalize_match_text(filename),
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

    object_name: str | None = None
    object_written = False
    minio_client = None
    try:
        async with validated_pdf_upload(file) as staged:
            course = None
            if current_user.is_admin:
                if request_new_category:
                    await _ensure_or_create_requested_category(
                        db,
                        requested_category_key,
                        requested_category_name,
                        requested_category_name_en,
                        requested_category_label,
                        requested_category_label_en,
                        requested_category_icon,
                        commit=False,
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
                        name_en=requested_course_name_en,
                        category=category,
                        order_index=await _next_course_order_index(db, category),
                    )
                    db.add(course)
                    await db.flush()
                    await db.refresh(course)

            _, file_extension = os.path.splitext(file.filename or "")
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            if current_user.is_admin:
                object_name = f"archives/{course.id}/{unique_filename}"
            else:
                object_name = (
                    f"archive-submissions/{current_user.user_id}/{unique_filename}"
                )

            minio_client = get_minio_client()
            with staged.path.open("rb") as file_data:
                put_task = asyncio.create_task(
                    asyncio.to_thread(
                        minio_client.put_object,
                        bucket_name=settings.MINIO_BUCKET_NAME,
                        object_name=object_name,
                        data=file_data,
                        length=staged.size,
                        content_type="application/pdf",
                    )
                )
                try:
                    await asyncio.shield(put_task)
                except asyncio.CancelledError:
                    # Establish whether the exact object completed before the
                    # staged stream is closed and compensation is considered.
                    try:
                        await put_task
                    except Exception as exc:  # noqa: BLE001 - cancellation remains primary
                        logger.warning(
                            "Archive upload cancelled while storage result was incomplete (%s)",
                            type(exc).__name__,
                        )
                    else:
                        object_written = True
                    raise
            object_written = True

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
                    requested_course_name_en=snapshot_course_name_en,
                    requested_category_key=requested_category_key
                    if request_new_category
                    else None,
                    requested_category_name=requested_category_name
                    if request_new_category
                    else None,
                    requested_category_name_en=snapshot_category_name_en,
                    requested_category_label=requested_category_label
                    if request_new_category
                    else None,
                    requested_category_label_en=snapshot_category_label_en,
                    requested_category_icon=requested_category_icon
                    if request_new_category
                    else None,
                    requester_id=current_user.user_id,
                    source_wish_id=source_wish_id,
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
                        "file_size": staged.size,
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
            await db.flush()
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
                requested_course_name=requested_course_name
                if request_new_course
                else None,
                requested_course_name_en=snapshot_course_name_en,
                requested_category_key=requested_category_key
                if request_new_category
                else None,
                requested_category_name=requested_category_name
                if request_new_category
                else None,
                requested_category_name_en=snapshot_category_name_en,
                requested_category_label=requested_category_label
                if request_new_category
                else None,
                requested_category_label_en=snapshot_category_label_en,
                requested_category_icon=requested_category_icon
                if request_new_category
                else None,
                status=SubmissionStatus.APPROVED,
                requester_id=current_user.user_id,
                reviewer_id=current_user.user_id,
                is_admin_upload=True,
                created_archive_id=archive.id,
                reviewed_at=datetime.now(UTC),
                source_wish_id=source_wish_id,
            )
            db.add(submission)
            await db.flush()
            await record_submission_event(db, submission)
            await enqueue_new_wish_fulfillment_notifications(
                db,
                archive=archive,
                publisher_user_id=current_user.user_id,
            )
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
                    "file_size": staged.size,
                },
                "submission": {
                    "id": submission.id,
                    "name": submission.name,
                    "professor": submission.professor,
                    "archive_type": submission.archive_type,
                    "has_answers": submission.has_answers,
                    "status": submission.status,
                    "created_at": submission.created_at,
                    "file_size": staged.size,
                    "is_admin_upload": True,
                },
            }
    except PdfValidationError as exc:
        await _rollback_failed_upload(db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.public_detail,
        ) from exc
    except asyncio.CancelledError:
        await _rollback_failed_upload(db)
        if object_written and object_name and minio_client is not None:
            await _compensate_failed_upload(object_name, minio_client)
        raise
    except HTTPException:
        await _rollback_failed_upload(db)
        if object_written and object_name and minio_client is not None:
            await _compensate_failed_upload(object_name, minio_client)
        raise
    except Exception as exc:
        await _rollback_failed_upload(db)
        if object_written and object_name and minio_client is not None:
            await _compensate_failed_upload(object_name, minio_client)
        logger.error(
            "Unexpected archive upload failure",
            exc_info=redacted_exc_info(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file",
        ) from exc


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


@router.get("/submissions/{submission_id}/pending/preview-file")
async def preview_owner_pending_archive_submission(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        locked = await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=submission_id,
            operation="submission_edit",
        )
        submission = require_owner_pending_submission(
            locked.submission(submission_id) if locked is not None else None,
            current_user=current_user,
        )
        object_name = submission.object_name
        filename = submission.name
        await db.rollback()
    except Exception:
        await db.rollback()
        raise

    try:
        response = get_minio_client().get_object(
            settings.MINIO_BUCKET_NAME,
            object_name,
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
                    "message": "此筆考古題的 PDF 檔案缺失，無法預覽。",
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load pending submission preview file from object storage",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load pending submission preview file from object storage",
        ) from exc

    return StreamingResponse(
        iter([data]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/submissions/{submission_id}/withdraw")
async def withdraw_owner_pending_archive_submission(
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
        submission = require_owner_pending_submission(
            locked.submission(submission_id) if locked is not None else None,
            current_user=current_user,
        )
        result = await soft_delete_submission_with_linked_archive(
            db,
            submission=submission,
            user_id=current_user.user_id,
            reason="owner withdrew pending submission",
            linked_archive=None,
            exact_link_only=True,
            consume_owner_self_delete=False,
        )
        await db.commit()
        return {
            "success": True,
            "submission_id": submission.id,
            "status": submission.status,
            "previous_status": submission.previous_status,
            "changed": result["submissions"] == 1,
        }
    except Exception:
        await db.rollback()
        raise


@router.patch(
    "/submissions/{submission_id}/pending",
    response_model=OwnerPendingArchiveSubmissionRead,
)
async def edit_owner_pending_archive_submission(
    submission_id: int,
    course_id: int = Form(...),
    professor: str = Form(...),
    academic_year: int = Form(...),
    archive_type: str = Form(...),
    sequence: int | None = Form(None),
    has_answers: bool = Form(False),
    other_name: str | None = Form(None),
    file: UploadFile | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        edit = OwnerPendingArchiveSubmissionEdit(
            course_id=course_id,
            professor=professor,
            academic_year=academic_year,
            archive_type=archive_type,
            sequence=sequence,
            has_answers=has_answers,
            other_name=other_name,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            ),
        ) from exc

    if file is None:
        return await _apply_owner_pending_submission_edit(
            submission_id=submission_id,
            edit=edit,
            staged=None,
            current_user=current_user,
            db=db,
        )

    try:
        async with validated_pdf_upload(file) as staged:
            return await _apply_owner_pending_submission_edit(
                submission_id=submission_id,
                edit=edit,
                staged=staged,
                current_user=current_user,
                db=db,
            )
    except PdfValidationError as exc:
        await _rollback_failed_upload(db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.public_detail,
        ) from exc


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
                archive_submissions.object_name,
                archive_submissions.requested_course_name,
                archive_submissions.requested_course_name_en,
                archive_submissions.requested_category_key,
                archive_submissions.requested_category_name,
                archive_submissions.requested_category_name_en,
                archive_submissions.requested_category_label,
                archive_submissions.requested_category_label_en,
                archive_submissions.requested_category_icon,
                LOWER(CAST(archive_submissions.status AS TEXT)) AS status,
                archive_submissions.requester_id,
                archive_submissions.owner_id,
                archive_submissions.source_wish_id,
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
                archives.id AS current_archive_id,
                archives.course_id AS current_archive_course_id,
                courses.name AS current_archive_course_name,
                courses.name_en AS current_archive_course_name_en,
                courses.category AS current_archive_course_category,
                archives.name AS current_archive_name,
                archives.academic_year AS current_archive_academic_year,
                LOWER(CAST(archives.archive_type AS TEXT)) AS current_archive_type,
                archives.professor AS current_archive_professor,
                archives.has_answers AS current_archive_has_answers,
                (archives.deleted_at IS NOT NULL) AS current_archive_is_deleted,
                (courses.deleted_at IS NOT NULL) AS current_archive_course_is_deleted,
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
        row_dict["review_revision"] = compute_archive_submission_review_revision(
            row_dict
        )
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
        current_archive_id = row_dict.pop("current_archive_id", None)
        if current_archive_id is None:
            row_dict["current_archive"] = None
        else:
            row_dict["current_archive"] = {
                "id": current_archive_id,
                "course_id": row_dict.pop("current_archive_course_id"),
                "course_name": format_course_display_name(
                    row_dict.pop("current_archive_course_name")
                ),
                "course_name_en": row_dict.pop("current_archive_course_name_en"),
                "course_category": row_dict.pop("current_archive_course_category"),
                "name": row_dict.pop("current_archive_name"),
                "academic_year": row_dict.pop("current_archive_academic_year"),
                "archive_type": row_dict.pop("current_archive_type"),
                "professor": row_dict.pop("current_archive_professor"),
                "has_answers": row_dict.pop("current_archive_has_answers"),
                "is_deleted": bool(row_dict.pop("current_archive_is_deleted")),
                "course_is_deleted": bool(
                    row_dict.pop("current_archive_course_is_deleted")
                ),
            }
        for projection_field in (
            "current_archive_course_id",
            "current_archive_course_name",
            "current_archive_course_name_en",
            "current_archive_course_category",
            "current_archive_name",
            "current_archive_academic_year",
            "current_archive_type",
            "current_archive_professor",
            "current_archive_has_answers",
            "current_archive_is_deleted",
            "current_archive_course_is_deleted",
        ):
            row_dict.pop(projection_field, None)
        try:
            row_dict["is_admin_upload"] = bool(row_dict.get("is_admin_upload"))
            archive_submissions.append(
                await _serialize_archive_submission_admin(db, row_dict)
            )
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
        payload["review_revision"] = compute_archive_submission_review_revision(
            comparison
        )
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
    expected_revision: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    locked = await acquire_stable_submission_lifecycle_locks(
        db,
        submission_id=submission_id,
        operation="submission_preview",
    )
    submission = locked.submission(submission_id) if locked is not None else None
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )

    if not expected_revision:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "archive_submission_revision_precondition_required",
                "message": "請重新載入投稿內容後再預覽。",
                "reload_required": True,
            },
        )
    current_revision = compute_archive_submission_review_revision(submission)
    if not review_revision_matches(expected_revision, current_revision):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "archive_submission_stale_revision",
                "message": "投稿內容已更新，請重新檢視後再審核。",
                "reload_required": True,
            },
        )
    object_name = submission.object_name
    filename = submission.name
    await db.rollback()

    try:
        response = get_minio_client().get_object(
            settings.MINIO_BUCKET_NAME,
            object_name,
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
            "Content-Disposition": f'inline; filename="{filename}.pdf"',
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
        normalized_values = _normalize_archive_submission_update(submission_data)
        changed_values = {
            field: value
            for field, value in normalized_values.items()
            if getattr(submission, field) != value
        }
        _ensure_archive_submission_editable(submission, set(changed_values))

        if "category" in changed_values and not (
            changed_values.get(
                "requested_category_key", submission.requested_category_key
            )
            or submission.requested_category_key
        ):
            await _ensure_category(db, changed_values["category"])
        if "review_note" in changed_values and _is_admin_upload_submission(
            submission
        ):
            submission.is_admin_upload = True
        for field, value in changed_values.items():
            setattr(submission, field, value)

        await db.commit()
        await db.refresh(submission)
        return await _serialize_archive_submission_admin(db, submission)
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

        archive = (
            await db.get(Archive, submission.created_archive_id)
            if submission.created_archive_id
            else None
        )
        if archive:
            _sync_archive_metadata_from_submission(archive, submission)
            archive.object_name = submission.object_name
            archive.uploader_id = submission.requester_id
            archive.deleted_at = None
        else:
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
                    submission.requested_category_name_en,
                    submission.requested_category_label,
                    submission.requested_category_label_en,
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
                    name_en=(submission.requested_course_name_en or "").strip()
                    or None,
                    category=category_key,
                    order_index=order_index,
                )
                db.add(course)
                await db.flush()
                await db.refresh(course)
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
            submission.created_archive_id = archive.id
            submission.reviewed_at = datetime.now(UTC)
            await enqueue_submission_status_notification(
                db,
                submission,
                SubmissionStatus.APPROVED,
            )
        await db.flush()
        await db.refresh(submission)
        await enqueue_new_wish_fulfillment_notifications(
            db,
            archive=archive,
            publisher_user_id=submission.requester_id,
        )
        await db.commit()
        await db.refresh(submission)
        return await _serialize_archive_submission_action(db, submission, changed=True)
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
            submission.reviewed_at = datetime.now(UTC)
            await enqueue_submission_status_notification(
                db,
                submission,
                SubmissionStatus.REJECTED,
            )
        await db.commit()
        await db.refresh(submission)
        return await _serialize_archive_submission_action(db, submission, changed=True)
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
            lifecycle_reason=decision.note if decision else None,
        )
        await db.commit()
        await db.refresh(submission)
        return await _serialize_archive_submission_action(db, submission, changed=True)
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

        _sync_archive_metadata_from_submission(archive, submission)
        await republish_archive_submission(
            db,
            submission,
            reviewer_id=current_user.user_id,
        )
        await db.commit()
        await db.refresh(submission)
        return await _serialize_archive_submission_action(db, submission, changed=True)
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
