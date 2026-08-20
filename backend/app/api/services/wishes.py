"""Past Exam Wish Pool API and its persisted support/report operations."""

from datetime import UTC, datetime
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveWish,
    ArchiveWishCreate,
    ArchiveWishHeart,
    ArchiveWishHeartRead,
    ArchiveWishListRead,
    ArchiveWishRead,
    ArchiveWishReport,
    ArchiveWishReportAdminUpdate,
    ArchiveWishReportCreate,
    ArchiveWishReportListRead,
    ArchiveWishReportRead,
    CommentReportReason,
    CommentReportStatus,
    Course,
    CourseCategory,
    User,
    UserRoles,
)
from app.services.archive_visibility import public_archive_conditions
from app.utils.auth import get_current_user
from app.utils.course_text import (
    format_course_display_name,
    normalize_course_search_text,
    normalized_course_text_expr,
)

router = APIRouter()
admin_router = APIRouter()


def _normalized_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalized_text_expr(value):
    return func.lower(func.trim(func.coalesce(value, "")))


def _target_key(data: ArchiveWishCreate, *, course: Course | None) -> str:
    course_identity = (
        f"course:{course.id}"
        if course is not None
        else "requested:"
        + normalize_course_search_text(data.requested_course_name or data.subject)
        + ":"
        + _normalized_text(data.requested_category_key or data.category)
    )
    identity = "|".join(
        (
            course_identity,
            _normalized_text(data.professor),
            "term:any" if data.academic_year is None else f"term:{data.academic_year}",
            data.archive_type.value,
            _normalized_text(data.name),
        )
    )
    return sha256(identity.encode("utf-8")).hexdigest()


async def _validated_course(db: AsyncSession, data: ArchiveWishCreate) -> Course | None:
    if data.course_id is None:
        return None
    course = await db.get(Course, data.course_id)
    if course is None or course.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wish course not found",
        )
    return course


def _matching_archive_id_subquery():
    course_match = or_(
        (ArchiveWish.course_id.is_not(None))
        & (Archive.course_id == ArchiveWish.course_id),
        (ArchiveWish.course_id.is_(None))
        & (
            normalized_course_text_expr(Course.name)
            == normalized_course_text_expr(
                ArchiveWish.requested_course_name, ArchiveWish.subject
            )
        )
        & (
            _normalized_text_expr(Course.category)
            == _normalized_text_expr(
                func.coalesce(ArchiveWish.requested_category_key, ArchiveWish.category)
            )
        ),
    )
    return (
        select(Archive.id)
        .join(Course, Course.id == Archive.course_id)
        .where(
            *public_archive_conditions(),
            Course.deleted_at.is_(None),
            course_match,
            _normalized_text_expr(Archive.name)
            == _normalized_text_expr(ArchiveWish.name),
            _normalized_text_expr(Archive.professor)
            == _normalized_text_expr(ArchiveWish.professor),
            or_(
                ArchiveWish.academic_year.is_(None),
                Archive.academic_year == ArchiveWish.academic_year,
            ),
            Archive.archive_type == ArchiveWish.archive_type,
        )
        .order_by(Archive.id.asc())
        .limit(1)
        .correlate(ArchiveWish)
        .scalar_subquery()
    )


def _wish_select(user_id: int):
    creator = aliased(User)
    heart_count = (
        select(func.count(ArchiveWishHeart.id))
        .where(ArchiveWishHeart.wish_id == ArchiveWish.id)
        .correlate(ArchiveWish)
        .scalar_subquery()
    )
    hearted_by_me = (
        select(ArchiveWishHeart.id)
        .where(
            ArchiveWishHeart.wish_id == ArchiveWish.id,
            ArchiveWishHeart.user_id == user_id,
        )
        .limit(1)
        .correlate(ArchiveWish)
        .scalar_subquery()
    )
    return select(
        ArchiveWish,
        creator.nickname,
        creator.name,
        heart_count.label("heart_count"),
        hearted_by_me.label("my_heart_id"),
        _matching_archive_id_subquery().label("matching_archive_id"),
    ).join(creator, creator.id == ArchiveWish.creator_id)


def _serialize_wish(row) -> ArchiveWishRead:
    wish = row[0]
    return ArchiveWishRead(
        **{
            field: getattr(wish, field)
            for field in ArchiveWishRead.model_fields
            if hasattr(wish, field)
        },
        creator_name=(row[1] or row[2] or f"User {wish.creator_id}").strip(),
        heart_count=int(row[3] or 0),
        hearted_by_me=row[4] is not None,
        fulfilled=row[5] is not None,
    )


async def _read_wish(db: AsyncSession, wish_id: int, user_id: int) -> ArchiveWishRead:
    row = (
        await db.execute(_wish_select(user_id).where(ArchiveWish.id == wish_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Wish not found")
    return _serialize_wish(row)


@router.get("", response_model=ArchiveWishListRead)
async def list_wishes(
    limit: int = Query(default=60, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    unfulfilled = _matching_archive_id_subquery().is_(None)
    total = int(
        await db.scalar(select(func.count(ArchiveWish.id)).where(unfulfilled)) or 0
    )
    rows = (
        await db.execute(
            _wish_select(current_user.user_id)
            .where(unfulfilled)
            .order_by(ArchiveWish.created_at.desc(), ArchiveWish.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ArchiveWishListRead(
        items=[_serialize_wish(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ArchiveWishRead, status_code=status.HTTP_201_CREATED)
async def create_wish(
    data: ArchiveWishCreate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    course = await _validated_course(db, data)
    key = _target_key(data, course=course)
    existing_id = await db.scalar(
        select(ArchiveWish.id).where(ArchiveWish.target_key == key)
    )
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "wish_already_exists", "existing_wish_id": existing_id},
        )
    wish = ArchiveWish(
        **data.model_dump(exclude={"course_id", "subject", "category"}),
        target_key=key,
        course_id=course.id if course is not None else None,
        subject=course.name
        if course is not None
        else format_course_display_name(data.subject),
        category=(
            course.category.value
            if course is not None and isinstance(course.category, CourseCategory)
            else course.category
            if course is not None
            else data.category
        ),
        creator_id=current_user.user_id,
    )
    db.add(wish)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing_id = await db.scalar(
            select(ArchiveWish.id).where(ArchiveWish.target_key == key)
        )
        if existing_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "wish_already_exists", "existing_wish_id": existing_id},
            ) from exc
        raise
    await db.refresh(wish)
    return await _read_wish(db, wish.id, current_user.user_id)


@router.post("/{wish_id}/heart", response_model=ArchiveWishHeartRead)
async def toggle_wish_heart(
    wish_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    wish = (
        await db.execute(
            select(ArchiveWish).where(ArchiveWish.id == wish_id).with_for_update()
        )
    ).scalar_one_or_none()
    if wish is None:
        raise HTTPException(status_code=404, detail="Wish not found")
    heart = (
        await db.execute(
            select(ArchiveWishHeart).where(
                ArchiveWishHeart.wish_id == wish_id,
                ArchiveWishHeart.user_id == current_user.user_id,
            )
        )
    ).scalar_one_or_none()
    hearted = heart is None
    if heart is None:
        db.add(ArchiveWishHeart(wish_id=wish_id, user_id=current_user.user_id))
    else:
        await db.delete(heart)
    await db.commit()
    count = int(
        await db.scalar(
            select(func.count(ArchiveWishHeart.id)).where(
                ArchiveWishHeart.wish_id == wish_id
            )
        )
        or 0
    )
    return ArchiveWishHeartRead(hearted=hearted, heart_count=count)


@router.delete("/{wish_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wish(
    wish_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    wish = await db.get(ArchiveWish, wish_id)
    if wish is None:
        raise HTTPException(status_code=404, detail="Wish not found")
    await db.delete(wish)
    await db.commit()


@router.post(
    "/{wish_id}/reports",
    response_model=ArchiveWishReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_wish_report(
    wish_id: int,
    payload: ArchiveWishReportCreate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    wish = await db.get(ArchiveWish, wish_id)
    if wish is None:
        raise HTTPException(status_code=404, detail="Wish not found")
    custom_message = (payload.custom_message or "").strip() or None
    if payload.report_reason == CommentReportReason.OTHER and not custom_message:
        raise HTTPException(status_code=400, detail="Custom report message is required")
    if payload.report_reason != CommentReportReason.OTHER:
        custom_message = None
    term_identity = (
        "term:any" if wish.academic_year is None else f"term:{wish.academic_year}"
    )
    report = ArchiveWishReport(
        wish_id=wish.id,
        reporter_user_id=current_user.user_id,
        wish_title_snapshot=wish.title,
        target_summary_snapshot=(
            f"{wish.subject} · {wish.professor} · {term_identity} · {wish.name}"
        ),
        reason=payload.report_reason.value,
        custom_message=custom_message,
    )
    db.add(report)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Wish report already exists"
        ) from exc
    await db.refresh(report)
    return await _read_wish_report(db, report.id)


def _wish_report_select():
    reporter = aliased(User)
    reviewer = aliased(User)
    wisher = aliased(User)
    statement = (
        select(
            ArchiveWishReport,
            reporter.nickname,
            reporter.name,
            reviewer.nickname,
            reviewer.name,
            ArchiveWish.id,
            ArchiveWish.creator_id,
            wisher.nickname,
            wisher.name,
        )
        .outerjoin(reporter, reporter.id == ArchiveWishReport.reporter_user_id)
        .outerjoin(reviewer, reviewer.id == ArchiveWishReport.reviewed_by)
        .outerjoin(ArchiveWish, ArchiveWish.id == ArchiveWishReport.wish_id)
        .outerjoin(wisher, wisher.id == ArchiveWish.creator_id)
    )
    return statement, reporter, reviewer, wisher


def _serialize_wish_report(row) -> ArchiveWishReportRead:
    report = row[0]
    return ArchiveWishReportRead(
        id=report.id,
        wish_id=report.wish_id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=(row[1] or row[2] or "Deleted user").strip(),
        wisher_name=(row[7] or row[8] or "").strip() or None,
        wish_title=report.wish_title_snapshot,
        target_summary=report.target_summary_snapshot,
        reason=report.reason,
        custom_message=report.custom_message,
        status=report.status,
        admin_response=report.admin_response,
        reviewed_by=report.reviewed_by,
        reviewer_name=(row[3] or row[4] or "").strip() or None,
        reviewed_at=report.reviewed_at,
        source_exists=row[5] is not None,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def _read_wish_report(db: AsyncSession, report_id: int) -> ArchiveWishReportRead:
    statement, _, _, _ = _wish_report_select()
    row = (
        await db.execute(statement.where(ArchiveWishReport.id == report_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Wish report not found")
    return _serialize_wish_report(row)


@admin_router.get("/admin/reports", response_model=ArchiveWishReportListRead)
async def list_wish_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    report_status: CommentReportStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    conditions = []
    if report_status is not None:
        conditions.append(ArchiveWishReport.status == report_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                ArchiveWishReport.wish_title_snapshot.ilike(pattern),
                ArchiveWishReport.target_summary_snapshot.ilike(pattern),
                ArchiveWishReport.custom_message.ilike(pattern),
            )
        )
    count_statement = select(func.count(ArchiveWishReport.id))
    statement, _, _, wisher = _wish_report_select()
    if conditions:
        count_statement = count_statement.where(*conditions)
        statement = statement.where(*conditions)
    total = int(await db.scalar(count_statement) or 0)
    status_rank = case(
        (ArchiveWishReport.status == CommentReportStatus.PENDING.value, 0),
        (ArchiveWishReport.status == CommentReportStatus.UPHELD.value, 1),
        (ArchiveWishReport.status == CommentReportStatus.DISMISSED.value, 2),
        else_=3,
    )
    sort_fields = {
        "created_at": ArchiveWishReport.created_at,
        "reason": ArchiveWishReport.reason,
        "wisher": func.coalesce(wisher.nickname, wisher.name, ""),
        "wish_target": func.coalesce(ArchiveWishReport.wish_title_snapshot, ""),
        "status": status_rank,
    }
    sort_column = sort_fields.get(sort_by)
    if sort_column is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid wish report sort field",
        )
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    secondary_ordering = (
        (ArchiveWishReport.created_at.desc(), ArchiveWishReport.id.desc())
        if sort_by == "status"
        else (ArchiveWishReport.id.desc(),)
    )
    rows = (
        await db.execute(
            statement.order_by(ordering, *secondary_ordering)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ArchiveWishReportListRead(
        items=[_serialize_wish_report(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@admin_router.get("/admin/reports/{report_id}", response_model=ArchiveWishReportRead)
async def get_wish_report(
    report_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return await _read_wish_report(db, report_id)


@admin_router.patch("/admin/reports/{report_id}", response_model=ArchiveWishReportRead)
async def review_wish_report(
    report_id: int,
    payload: ArchiveWishReportAdminUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    report = (
        await db.execute(
            select(ArchiveWishReport)
            .where(ArchiveWishReport.id == report_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Wish report not found")
    if report.status != CommentReportStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="Wish report is already finalized")
    if payload.status == CommentReportStatus.PENDING:
        raise HTTPException(status_code=400, detail="A final report status is required")
    report.status = payload.status.value
    report.admin_response = (payload.admin_response or "").strip() or None
    report.reviewed_by = current_user.user_id
    report.reviewed_at = datetime.now(UTC)
    report.updated_at = report.reviewed_at
    db.add(report)
    await db.commit()
    return await _read_wish_report(db, report.id)


@admin_router.delete(
    "/admin/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_wish_report(
    report_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    deleted_id = await db.scalar(
        delete(ArchiveWishReport)
        .where(ArchiveWishReport.id == report_id)
        .returning(ArchiveWishReport.id)
    )
    if deleted_id is None:
        raise HTTPException(status_code=404, detail="Wish report not found")
    await db.commit()
