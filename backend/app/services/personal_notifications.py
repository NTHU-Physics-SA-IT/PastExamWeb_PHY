from datetime import UTC, datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import PersonalNotification, PersonalNotificationType


async def enqueue_personal_notification(
    db: AsyncSession,
    *,
    user_id: int,
    notification_type: PersonalNotificationType | str,
    title: str,
    message: str,
    dedupe_key: str,
    source_type: str | None = None,
    source_id: int | None = None,
    source_message_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> bool:
    """Queue one durable notification in the caller's transaction.

    The database uniqueness constraint is the final idempotency boundary.  Callers
    must commit only after their associated domain operation has succeeded.
    """

    statement = (
        pg_insert(PersonalNotification.__table__)
        .values(
            user_id=user_id,
            notification_type=str(
                notification_type.value
                if isinstance(notification_type, PersonalNotificationType)
                else notification_type
            ),
            title=title[:150],
            message=message,
            source_type=source_type,
            source_id=source_id,
            source_message_id=source_message_id,
            metadata=metadata or {},
            dedupe_key=dedupe_key[:160],
            created_at=created_at or datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_personal_notifications_dedupe_key")
        .returning(PersonalNotification.id)
    )
    return (await db.scalar(statement)) is not None
