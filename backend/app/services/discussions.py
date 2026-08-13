from datetime import UTC, datetime, timezone

from sqlalchemy import exists
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import ArchiveDiscussionMessage


async def soft_delete_discussion_message(
    db: AsyncSession, message: ArchiveDiscussionMessage
) -> bool:
    """Apply the shared discussion deletion policy without committing."""

    message.deleted_at = datetime.now(UTC)
    message.is_pinned = False
    preserve_thread = bool(
        message.parent_id is None
        and await db.scalar(
            select(
                exists().where(
                    ArchiveDiscussionMessage.parent_id == message.id,
                    ArchiveDiscussionMessage.deleted_at.is_(None),
                )
            )
        )
    )
    db.add(message)
    return preserve_thread
