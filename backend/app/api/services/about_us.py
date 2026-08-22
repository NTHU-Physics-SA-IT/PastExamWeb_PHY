import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import (
    AboutUsEntry,
    AboutUsEntryCreate,
    AboutUsEntryRead,
    AboutUsEntryReorder,
    AboutUsEntryUpdate,
    User,
    UserRoles,
)
from app.utils.auth import get_current_user

router = APIRouter()

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_MARKDOWN_DECORATION = re.compile(r"[*_`~>|]+")


def _derive_compatibility_title(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    candidate = ""
    for line in lines:
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            candidate = heading.group(1)
            break
    if not candidate:
        candidate = next((line for line in lines if not line.startswith("```")), "")
    candidate = _MARKDOWN_IMAGE.sub(lambda match: match.group(1), candidate)
    candidate = _MARKDOWN_LINK.sub(lambda match: match.group(1), candidate)
    candidate = _HTML_TAG.sub("", candidate)
    candidate = _MARKDOWN_DECORATION.sub("", candidate).strip(" -:;,.，。；：")
    return (candidate or "About Us")[:150]


def _read(entry: AboutUsEntry, updater: User | None) -> AboutUsEntryRead:
    return AboutUsEntryRead.model_validate(entry).model_copy(
        update={"updated_by_username": updater.name if updater else None}
    )


async def _list_entries(db: AsyncSession) -> list[AboutUsEntryRead]:
    rows = (
        await db.execute(
            select(AboutUsEntry, User)
            .outerjoin(User, User.id == AboutUsEntry.updated_by_id)
            .order_by(AboutUsEntry.order_index, AboutUsEntry.id)
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
    existing_entries = (
        (await db.execute(select(AboutUsEntry).with_for_update())).scalars().all()
    )
    for existing_entry in existing_entries:
        existing_entry.order_index += 1
    entry = AboutUsEntry(
        title=_derive_compatibility_title(data.body),
        body=data.body.strip(),
        title_en=_derive_compatibility_title(data.body_en),
        body_en=data.body_en,
        order_index=0,
        created_at=now,
        updated_at=now,
        updated_by_id=current_user.user_id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _read(entry, await db.get(User, current_user.user_id))


@router.put("/admin/entries/reorder", response_model=list[AboutUsEntryRead])
async def reorder_about_us_entries(
    data: AboutUsEntryReorder,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    entries = (
        (
            await db.execute(
                select(AboutUsEntry).order_by(AboutUsEntry.id).with_for_update()
            )
        )
        .scalars()
        .all()
    )
    requested_ids = data.entry_ids
    if len(requested_ids) != len(set(requested_ids)) or set(requested_ids) != {
        entry.id for entry in entries
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="About Us entry order is stale; reload and try again",
        )
    entries_by_id = {entry.id: entry for entry in entries}
    for order_index, entry_id in enumerate(requested_ids):
        entries_by_id[entry_id].order_index = order_index
    await db.commit()
    return await _list_entries(db)


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
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(entry, field, value.strip() if isinstance(value, str) else value)
    if "body" in updates and updates["body"] is not None:
        entry.title = _derive_compatibility_title(updates["body"])
    if "body_en" in updates:
        entry.title_en = (
            _derive_compatibility_title(updates["body_en"])
            if updates["body_en"] is not None
            else None
        )
    entry.updated_at = datetime.now(UTC)
    entry.updated_by_id = current_user.user_id
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _read(entry, await db.get(User, current_user.user_id))


@router.delete(
    "/admin/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_about_us_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    entry = await db.get(AboutUsEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="About Us entry not found")
    await db.delete(entry)
    await db.commit()
