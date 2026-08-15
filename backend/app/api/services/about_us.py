from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import (
    AboutUsEntry,
    AboutUsEntryCreate,
    AboutUsEntryRead,
    AboutUsEntryUpdate,
    User,
    UserRoles,
)
from app.utils.auth import get_current_user

router = APIRouter()


def _read(entry: AboutUsEntry, updater: User | None) -> AboutUsEntryRead:
    return AboutUsEntryRead.model_validate(entry).model_copy(
        update={"updated_by_username": updater.name if updater else None}
    )


async def _list_entries(db: AsyncSession) -> list[AboutUsEntryRead]:
    rows = (
        await db.execute(
            select(AboutUsEntry, User)
            .outerjoin(User, User.id == AboutUsEntry.updated_by_id)
            .order_by(AboutUsEntry.updated_at.desc(), AboutUsEntry.id.desc())
        )
    ).all()
    return [_read(entry, updater) for entry, updater in rows]


@router.get("", response_model=list[AboutUsEntryRead])
async def list_about_us_entries(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    return await _list_entries(db)


@router.post(
    "/admin/entries",
    response_model=AboutUsEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_about_us_entry(
    data: AboutUsEntryCreate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    now = datetime.now(UTC)
    entry = AboutUsEntry(
        title=data.title.strip(),
        body=data.body.strip(),
        created_at=now,
        updated_at=now,
        updated_by_id=current_user.user_id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _read(entry, await db.get(User, current_user.user_id))


@router.put("/admin/entries/{entry_id}", response_model=AboutUsEntryRead)
async def update_about_us_entry(
    entry_id: int,
    data: AboutUsEntryUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    entry = await db.get(AboutUsEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="About Us entry not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, field, value.strip())
    entry.updated_at = datetime.now(UTC)
    entry.updated_by_id = current_user.user_id
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _read(entry, await db.get(User, current_user.user_id))
