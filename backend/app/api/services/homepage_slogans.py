"""Homepage slogan submission, moderation, and public selection API."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import (
    HomepageSloganAdminListRead,
    HomepageSloganAdminRead,
    HomepageSloganAdminUpdate,
    HomepageSloganCreate,
    HomepageSloganOccurrenceLevel,
    HomepageSloganPublicRead,
    HomepageSloganStatus,
    HomepageSloganStatusCounts,
    HomepageSloganSubmission,
    User,
    UserRoles,
)
from app.services.homepage_slogans import select_weighted_enabled_slogan
from app.utils.auth import get_current_user

router = APIRouter()


def _require_admin(current_user: UserRoles) -> None:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def _display_name(user: User | None, fallback: str | None = None) -> str | None:
    if user is None:
        return fallback
    return (user.nickname or user.name or fallback or "").strip() or fallback


def _admin_select():
    submitter = aliased(User)
    reviewer = aliased(User)
    statement = (
        select(HomepageSloganSubmission, submitter, reviewer)
        .outerjoin(
            submitter,
            submitter.id == HomepageSloganSubmission.submitter_user_id,
        )
        .outerjoin(
            reviewer,
            reviewer.id == HomepageSloganSubmission.reviewer_user_id,
        )
    )
    return statement, submitter, reviewer


def _serialize_admin(row) -> HomepageSloganAdminRead:
    slogan, submitter, reviewer = row
    return HomepageSloganAdminRead(
        id=slogan.id,
        content=slogan.content,
        submitter_user_id=slogan.submitter_user_id,
        submitter_name=_display_name(
            submitter, slogan.submitter_name_snapshot
        ) or slogan.submitter_name_snapshot,
        status=slogan.status,
        occurrence_level=slogan.occurrence_level,
        reviewer_user_id=slogan.reviewer_user_id,
        reviewer_name=_display_name(reviewer),
        reviewed_at=slogan.reviewed_at,
        created_at=slogan.created_at,
        updated_at=slogan.updated_at,
    )


async def _read_admin(
    db: AsyncSession, slogan_id: int
) -> HomepageSloganAdminRead:
    statement, _, _ = _admin_select()
    row = (
        await db.execute(
            statement.where(HomepageSloganSubmission.id == slogan_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Homepage slogan not found")
    return _serialize_admin(row)


async def _status_counts(db: AsyncSession) -> HomepageSloganStatusCounts:
    rows = (
        await db.execute(
            select(
                HomepageSloganSubmission.status,
                func.count(HomepageSloganSubmission.id),
            ).group_by(HomepageSloganSubmission.status)
        )
    ).all()
    counts = {status_value: int(count) for status_value, count in rows}
    return HomepageSloganStatusCounts(
        pending=counts.get(HomepageSloganStatus.PENDING.value, 0),
        enabled=counts.get(HomepageSloganStatus.ENABLED.value, 0),
        disabled=counts.get(HomepageSloganStatus.DISABLED.value, 0),
    )


@router.get("/selected", response_model=HomepageSloganPublicRead | None)
async def get_selected_homepage_slogan(
    db: AsyncSession = Depends(get_session),
):
    slogan = await select_weighted_enabled_slogan(db)
    if slogan is None:
        return None
    return HomepageSloganPublicRead(id=slogan.id, content=slogan.content)


@router.post(
    "",
    response_model=HomepageSloganPublicRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_homepage_slogan(
    data: HomepageSloganCreate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    submitter = await db.get(User, current_user.user_id)
    if submitter is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    now = datetime.now(UTC)
    slogan = HomepageSloganSubmission(
        content=data.content,
        submitter_user_id=submitter.id,
        submitter_name_snapshot=_display_name(submitter) or f"User {submitter.id}",
        status=HomepageSloganStatus.PENDING.value,
        occurrence_level=HomepageSloganOccurrenceLevel.NORMAL.value,
        created_at=now,
        updated_at=now,
    )
    db.add(slogan)
    await db.commit()
    await db.refresh(slogan)
    return HomepageSloganPublicRead(id=slogan.id, content=slogan.content)


@router.get("/admin", response_model=HomepageSloganAdminListRead)
async def list_homepage_slogans(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    slogan_status: HomepageSloganStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=80),
    sort_by: str = Query(default="status"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    _require_admin(current_user)
    conditions = []
    if slogan_status is not None:
        conditions.append(
            HomepageSloganSubmission.status == slogan_status.value
        )
    statement, submitter, _ = _admin_select()
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                HomepageSloganSubmission.content.ilike(pattern),
                HomepageSloganSubmission.submitter_name_snapshot.ilike(pattern),
            )
        )
    count_statement = select(func.count(HomepageSloganSubmission.id))
    if conditions:
        statement = statement.where(*conditions)
        count_statement = count_statement.where(*conditions)
    status_rank = case(
        (HomepageSloganSubmission.status == HomepageSloganStatus.PENDING.value, 0),
        (HomepageSloganSubmission.status == HomepageSloganStatus.ENABLED.value, 1),
        else_=2,
    )
    level_rank = case(
        (
            HomepageSloganSubmission.occurrence_level
            == HomepageSloganOccurrenceLevel.SUPER_RARE.value,
            0,
        ),
        (
            HomepageSloganSubmission.occurrence_level
            == HomepageSloganOccurrenceLevel.RARE.value,
            1,
        ),
        (
            HomepageSloganSubmission.occurrence_level
            == HomepageSloganOccurrenceLevel.NORMAL.value,
            2,
        ),
        (
            HomepageSloganSubmission.occurrence_level
            == HomepageSloganOccurrenceLevel.FREQUENT.value,
            3,
        ),
        else_=4,
    )
    sort_fields = {
        "created_at": HomepageSloganSubmission.created_at,
        "content": HomepageSloganSubmission.content,
        "submitter": func.coalesce(
            submitter.nickname,
            submitter.name,
            HomepageSloganSubmission.submitter_name_snapshot,
        ),
        "status": status_rank,
        "occurrence_level": level_rank,
        "reviewed_at": HomepageSloganSubmission.reviewed_at,
    }
    sort_column = sort_fields.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=422, detail="Invalid slogan sort field")
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    secondary_ordering = (
        (
            HomepageSloganSubmission.created_at.desc(),
            HomepageSloganSubmission.id.desc(),
        )
        if sort_by == "status"
        else (HomepageSloganSubmission.id.desc(),)
    )
    rows = (
        await db.execute(
            statement.order_by(ordering, *secondary_ordering)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return HomepageSloganAdminListRead(
        items=[_serialize_admin(row) for row in rows],
        total=int(await db.scalar(count_statement) or 0),
        limit=limit,
        offset=offset,
        status_counts=await _status_counts(db),
    )


@router.get("/admin/{slogan_id}", response_model=HomepageSloganAdminRead)
async def get_homepage_slogan(
    slogan_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _read_admin(db, slogan_id)


@router.patch("/admin/{slogan_id}", response_model=HomepageSloganAdminRead)
async def review_homepage_slogan(
    slogan_id: int,
    data: HomepageSloganAdminUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    _require_admin(current_user)
    slogan = (
        await db.execute(
            select(HomepageSloganSubmission)
            .where(HomepageSloganSubmission.id == slogan_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if slogan is None:
        raise HTTPException(status_code=404, detail="Homepage slogan not found")
    now = datetime.now(UTC)
    next_status = data.status.value
    next_level = data.occurrence_level.value
    status_changed = slogan.status != next_status
    level_changed = slogan.occurrence_level != next_level
    if status_changed:
        slogan.status = next_status
        slogan.reviewer_user_id = current_user.user_id
        slogan.reviewed_at = now
    if level_changed:
        slogan.occurrence_level = next_level
    if status_changed or level_changed:
        slogan.updated_at = now
        db.add(slogan)
        await db.commit()
    return await _read_admin(db, slogan.id)


@router.delete(
    "/admin/{slogan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_homepage_slogan(
    slogan_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    _require_admin(current_user)
    slogan = await db.get(HomepageSloganSubmission, slogan_id)
    if slogan is None:
        raise HTTPException(status_code=404, detail="Homepage slogan not found")
    await db.delete(slogan)
    await db.commit()
