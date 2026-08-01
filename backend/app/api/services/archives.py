import io
import os
import re
import logging
import uuid
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from sqlalchemy import BigInteger, and_, cast, func, or_, text
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.db.course_categories import (
    RESERVED_LEGACY_COURSE_CATEGORY_KEYS,
    canonicalize_course_category_key,
    normalize_course_category_key,
)
from app.models.models import (
    Archive,
    ArchiveSubmissionComparisonRead,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveSubmissionRead,
    SubmissionStatisticsRead,
    ArchiveSubmissionUpdate,
    Course,
    CourseCategoryConfig,
    SubmissionDecision,
    SubmissionStatus,
    User,
)
from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_ARCHIVE_TRASHED,
    LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED,
    is_course_trash_lifecycle_reason,
    soft_delete_submission_with_linked_archive,
)
from app.utils.auth import get_current_user
from app.utils.course_text import (
    format_course_display_name,
    normalize_first_course_search_text,
    normalize_course_search_text,
    normalized_course_text_expr,
)
from app.utils.storage import get_minio_client
from app.api.services.submission_statistics import (
    SUBMISSION_RANGE_CONFIG,
    build_submission_statistics,
    get_submission_statistics_window,
    record_submission_event,
)
from app.services.archive_submission_status import (
    enqueue_submission_status_notification,
    normalize_submission_status,
    republish_archive_submission,
    take_down_archive_submission,
)

router = APIRouter()
logger = logging.getLogger(__name__)

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


def _is_locked_review_submission(submission: ArchiveSubmission) -> bool:
    normalized_status = _normalize_submission_status(submission.status)
    return (
        normalized_status in {SubmissionStatus.TAKEDOWN, SubmissionStatus.DELETED}
        or submission.deleted_at is not None
    )


def _ensure_review_submission_mutable(submission: ArchiveSubmission) -> None:
    if _is_locked_review_submission(submission):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此投稿已下架或已刪除，僅能查看，不能再編輯或變更審核狀態。",
        )


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


def _normalize_course_name(value: Optional[str]) -> str:
    return normalize_course_search_text(value)


def _normalize_match_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _normalize_course_match_text(value: Optional[str]) -> str:
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
    return bool(flag) or str(review_note or "").strip().lower() in {"管理員上傳", "admin upload"}


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


async def _acquire_course_approval_lock(db: AsyncSession, *, category_key: str, course_name: str) -> None:
    scope_key = f"archive_approval:{category_key}:{course_name.lower().strip()}"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": scope_key},
    )


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
        format_course_display_name(requested_course_name) if requested_course_name else None
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
            normalized_course_text_expr(Course.name) == normalize_course_search_text(subject),
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
                requested_course_name=requested_course_name if request_new_course else None,
                requested_category_key=requested_category_key if request_new_category else None,
                requested_category_name=requested_category_name if request_new_category else None,
                requested_category_label=requested_category_label if request_new_category else None,
                requested_category_icon=requested_category_icon if request_new_category else None,
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
            requested_category_key=requested_category_key if request_new_category else None,
            requested_category_name=requested_category_name if request_new_category else None,
            requested_category_label=requested_category_label if request_new_category else None,
            requested_category_icon=requested_category_icon if request_new_category else None,
            status=SubmissionStatus.APPROVED,
            requester_id=current_user.user_id,
            reviewer_id=current_user.user_id,
            is_admin_upload=True,
            created_archive_id=archive.id,
            reviewed_at=datetime.now(timezone.utc),
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}",
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
    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.deleted_at is not None or submission.status == SubmissionStatus.DELETED:
        return {"success": True, "id": submission.id}

    is_owner = submission.requester_id == current_user.user_id or (
        submission.owner_id is not None and submission.owner_id == current_user.user_id
    )
    if not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if submission.status != SubmissionStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only approved submissions can be deleted by users",
        )

    result = await soft_delete_submission_with_linked_archive(
        db,
        submission=submission,
        user_id=current_user.user_id,
        reason="user deleted",
    )

    await db.commit()

    return {
        "success": True,
        "id": submission.id,
        "status": submission.status,
        "deleted": result,
        "message": "已刪除，管理員可於垃圾桶中恢復",
    }


@router.get("/admin/submissions", response_model=list[ArchiveSubmissionRead])
async def list_archive_submissions_for_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

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
        normalized_status = _normalize_submission_status(row_dict.get("status"))
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
            archive_submissions.append(ArchiveSubmissionRead.model_validate(row_dict))
        except Exception as exc:
            skipped_submission_count += 1
            logger.warning(
                "Skipping archive submission %s due to invalid payload: %s",
                row_dict.get("id"),
                exc,
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    config = SUBMISSION_RANGE_CONFIG.get(range_key)
    if config is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid range")
    expected_mode = config[0]
    if mode not in {"time", "date"} or mode != expected_mode:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid mode")

    now_utc = datetime.now(timezone.utc)
    _, bucket_minutes, _, range_start, range_end = get_submission_statistics_window(
        range_key, now_utc
    )
    bucket_seconds = bucket_minutes * 60
    bucket_epoch = cast(
        func.floor(
            (func.extract("epoch", ArchiveSubmissionEvent.submitted_at) - range_start.timestamp())
            / bucket_seconds
        ),
        BigInteger,
    )
    result = await db.execute(
        select(bucket_epoch.label("bucket_index"), func.count(ArchiveSubmissionEvent.id))
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


@router.get("/admin/submissions/{submission_id}/comparisons", response_model=list[ArchiveSubmissionComparisonRead])
async def list_archive_submission_comparisons(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    course_name = normalize_first_course_search_text(
        submission.requested_course_name,
        submission.subject,
    )
    category_key = _normalize_match_text(submission.requested_category_key or submission.category)
    exam_name = _normalize_match_text(submission.name)
    professor = _normalize_match_text(submission.professor)
    if not course_name or not category_key or not exam_name or submission.academic_year is None:
        return []

    current_archive = await db.get(Archive, submission.created_archive_id) if submission.created_archive_id else None
    current_course_id = current_archive.course_id if current_archive else None
    comparison_archive = aliased(Archive)
    comparable_statuses = [
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
        SubmissionStatus.TAKEDOWN,
    ]
    fallback_course_condition = and_(
        ArchiveSubmission.created_archive_id.is_(None),
        normalized_course_text_expr(ArchiveSubmission.requested_course_name, ArchiveSubmission.subject)
        == course_name,
        _normalized_text_expr(ArchiveSubmission.requested_category_key, ArchiveSubmission.category)
        == category_key,
    )
    course_condition = (
        or_(comparison_archive.course_id == current_course_id, fallback_course_condition)
        if current_course_id is not None
        else and_(
            normalized_course_text_expr(ArchiveSubmission.requested_course_name, ArchiveSubmission.subject)
            == course_name,
            _normalized_text_expr(ArchiveSubmission.requested_category_key, ArchiveSubmission.category)
            == category_key,
        )
    )
    query = (
        select(ArchiveSubmission, User.name, User.email)
        .outerjoin(User, User.id == ArchiveSubmission.requester_id)
        .outerjoin(comparison_archive, comparison_archive.id == ArchiveSubmission.created_archive_id)
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
        normalized_status = _normalize_submission_status(comparison.status)
        if normalized_status not in comparable_statuses:
            continue

        payload = ArchiveSubmissionRead.model_validate(comparison).model_dump()
        payload["requester_name"] = requester_name
        payload["requester_email"] = requester_email
        payload["status"] = normalized_status
        payload["can_takedown"] = normalized_status in {
            SubmissionStatus.PENDING,
            SubmissionStatus.APPROVED,
        }
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

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


@router.put("/admin/submissions/{submission_id}", response_model=ArchiveSubmissionRead)
async def update_archive_submission_for_admin(
    submission_id: int,
    submission_data: ArchiveSubmissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    _ensure_review_submission_mutable(submission)

    if submission_data.subject is not None:
        submission.subject = format_course_display_name(submission_data.subject)
    if submission_data.category is not None:
        if not (submission_data.requested_category_key or submission.requested_category_key):
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
            format_course_display_name(submission_data.requested_course_name) or None
        )
    if submission_data.requested_category_key is not None:
        key = submission_data.requested_category_key.strip()
        submission.requested_category_key = _normalize_category_key(key) if key else None
    if submission_data.requested_category_name is not None:
        submission.requested_category_name = submission_data.requested_category_name.strip() or None
    if submission_data.requested_category_label is not None:
        submission.requested_category_label = submission_data.requested_category_label.strip() or None
    if submission_data.requested_category_icon is not None:
        submission.requested_category_icon = submission_data.requested_category_icon.strip() or None

    await db.commit()
    await db.refresh(submission)

    if submission.created_archive_id:
        course_name = format_course_display_name(
            submission.requested_course_name or submission.subject or ""
        )
        course_name_for_match = _normalize_course_match_text(course_name)
        category_key = submission.requested_category_key or submission.category
        if submission.requested_category_key:
            await _ensure_or_create_requested_category(
                db,
                submission.requested_category_key,
                submission.requested_category_name,
                submission.requested_category_label,
                submission.requested_category_icon,
                commit=True,
            )
        else:
            await _ensure_category(db, category_key)

        course = (
            await db.execute(
                select(Course).where(
                    normalized_course_text_expr(Course.name) == course_name_for_match,
                    Course.category == category_key,
                    Course.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not course:
            course = Course(
                name=course_name,
                category=category_key,
                order_index=await _next_course_order_index(db, category_key),
            )
            db.add(course)
            await db.commit()
            await db.refresh(course)

        archive = await db.get(Archive, submission.created_archive_id)
        if archive:
            archive.course_id = course.id
            archive.name = submission.name
            archive.academic_year = submission.academic_year
            archive.archive_type = submission.archive_type
            archive.professor = submission.professor
            archive.has_answers = submission.has_answers
            archive.updated_at = datetime.now(timezone.utc)
            db.add(archive)
            await db.commit()

    return submission


@router.post("/admin/submissions/{submission_id}/approve", response_model=ArchiveSubmissionRead)
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
        submission = await db.get(ArchiveSubmission, submission_id)
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
            )
        _ensure_review_submission_mutable(submission)

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

        await _acquire_course_approval_lock(
            db,
            category_key=category_key,
            course_name=course_name,
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
            archive.updated_at = datetime.now(timezone.utc)
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

        submission.status = SubmissionStatus.APPROVED
        submission.reviewer_id = current_user.user_id
        submission.review_note = decision.note if decision else None
        submission.created_archive_id = archive.id
        submission.reviewed_at = datetime.now(timezone.utc)
        await enqueue_submission_status_notification(
            db,
            submission,
            SubmissionStatus.APPROVED,
        )
        await db.flush()
        await db.refresh(submission)
        await db.commit()
        return submission
    except Exception:
        await db.rollback()
        raise


@router.post("/admin/submissions/{submission_id}/reject", response_model=ArchiveSubmissionRead)
async def reject_archive_submission(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    _ensure_review_submission_mutable(submission)

    submission.status = SubmissionStatus.REJECTED
    submission.reviewer_id = current_user.user_id
    submission.review_note = decision.note if decision else None
    submission.reviewed_at = datetime.now(timezone.utc)
    await enqueue_submission_status_notification(db, submission, SubmissionStatus.REJECTED)
    await db.commit()
    await db.refresh(submission)
    return submission


@router.post("/admin/submissions/{submission_id}/takedown", response_model=ArchiveSubmissionRead)
async def takedown_archive_submission(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    _ensure_review_submission_mutable(submission)

    await take_down_archive_submission(
        db,
        submission,
        reviewer_id=current_user.user_id,
        note=decision.note if decision else None,
    )
    await db.commit()
    await db.refresh(submission)
    return submission


@router.post("/admin/submissions/{submission_id}/republish", response_model=ArchiveSubmissionRead)
async def republish_archive_submission_endpoint(
    submission_id: int,
    decision: SubmissionDecision | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = (
        await db.execute(
            select(ArchiveSubmission)
            .where(ArchiveSubmission.id == submission_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    normalized_status = _normalize_submission_status(submission.status)
    if submission.deleted_at is not None or normalized_status == SubmissionStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此投稿已刪除，無法重新上架。",
        )
    if normalized_status != SubmissionStatus.TAKEDOWN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only taken down submissions can be republished",
        )

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
    return submission


@router.delete("/admin/submissions/{submission_id}")
async def delete_archive_submission_for_admin(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    submission = await db.get(ArchiveSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    _ensure_review_submission_mutable(submission)

    if submission.status == SubmissionStatus.DELETED:
        now = datetime.now(timezone.utc)
        if submission.deleted_at is None:
            submission.deleted_at = now
        if submission.deleted_by_id is None:
            submission.deleted_by_id = current_user.user_id
        if submission.delete_reason is None:
            submission.delete_reason = "admin deleted"
        submission.lifecycle_reason = None

    result = await soft_delete_submission_with_linked_archive(
        db,
        submission=submission,
        user_id=current_user.user_id,
        reason="admin deleted",
    )
    submission.reviewer_id = current_user.user_id
    submission.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"success": True, "id": submission.id, "deleted": result}
