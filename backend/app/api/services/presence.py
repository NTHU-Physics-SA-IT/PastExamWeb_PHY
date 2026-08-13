from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.models import UserPresenceSession

HEARTBEAT_INTERVAL_SECONDS = 60
ONLINE_TIMEOUT_SECONDS = 5 * 60


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def token_fingerprint(token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def effective_session_end(
    session: UserPresenceSession,
    *,
    timeout_seconds: int = ONLINE_TIMEOUT_SECONDS,
) -> datetime:
    timeout_end = normalize_utc(session.last_seen_at) + timedelta(
        seconds=timeout_seconds
    )
    if session.ended_at is None:
        return timeout_end
    return min(normalize_utc(session.ended_at), timeout_end)


def session_is_online_at(
    session: UserPresenceSession,
    at: datetime,
    *,
    timeout_seconds: int = ONLINE_TIMEOUT_SECONDS,
) -> bool:
    sample_at = normalize_utc(at)
    return (
        normalize_utc(session.started_at)
        <= sample_at
        < effective_session_end(session, timeout_seconds=timeout_seconds)
    )


async def touch_presence_session(
    db: AsyncSession,
    *,
    user_id: int,
    token: str,
    now: datetime | None = None,
) -> UserPresenceSession:
    now_utc = normalize_utc(now or datetime.now(UTC))
    identifier = token_fingerprint(token)
    result = await db.execute(
        select(UserPresenceSession)
        .where(
            UserPresenceSession.user_id == user_id,
            UserPresenceSession.session_identifier == identifier,
            UserPresenceSession.ended_at.is_(None),
        )
        .order_by(UserPresenceSession.started_at.desc())
        .limit(1)
    )
    current = result.scalar_one_or_none()
    if current is not None and session_is_online_at(current, now_utc):
        current.last_seen_at = now_utc
        return current

    if current is not None:
        current.ended_at = effective_session_end(current)

    presence = UserPresenceSession(
        user_id=user_id,
        session_identifier=identifier,
        started_at=now_utc,
        last_seen_at=now_utc,
    )
    db.add(presence)
    return presence


async def end_presence_session(
    db: AsyncSession,
    *,
    user_id: int,
    token: str,
    now: datetime | None = None,
) -> None:
    now_utc = normalize_utc(now or datetime.now(UTC))
    identifier = token_fingerprint(token)
    result = await db.execute(
        select(UserPresenceSession).where(
            UserPresenceSession.user_id == user_id,
            UserPresenceSession.session_identifier == identifier,
            UserPresenceSession.ended_at.is_(None),
        )
    )
    for presence in result.scalars().all():
        presence.ended_at = min(now_utc, effective_session_end(presence))


async def load_presence_sessions(
    db: AsyncSession,
    *,
    range_start: datetime,
    range_end: datetime,
    user_id: int | None = None,
) -> list[UserPresenceSession]:
    bounded_start = normalize_utc(range_start) - timedelta(
        seconds=ONLINE_TIMEOUT_SECONDS
    )
    statement = select(UserPresenceSession).where(
        UserPresenceSession.started_at <= normalize_utc(range_end),
        or_(
            and_(
                UserPresenceSession.ended_at.is_(None),
                UserPresenceSession.last_seen_at >= bounded_start,
            ),
            UserPresenceSession.ended_at >= normalize_utc(range_start),
        ),
    )
    if user_id is not None:
        statement = statement.where(UserPresenceSession.user_id == user_id)
    result = await db.execute(statement)
    return list(result.scalars().all())


def merge_presence_intervals(
    sessions: list[UserPresenceSession],
    *,
    range_start: datetime,
    range_end: datetime,
    now: datetime,
    timeout_seconds: int = ONLINE_TIMEOUT_SECONDS,
) -> list[tuple[datetime, datetime]]:
    """Return bounded, de-duplicated online intervals for one user."""
    start_bound = normalize_utc(range_start)
    end_bound = min(normalize_utc(range_end), normalize_utc(now))
    if end_bound <= start_bound:
        return []

    intervals: list[tuple[datetime, datetime]] = []
    for session in sessions:
        start = max(normalize_utc(session.started_at), start_bound)
        end = min(
            effective_session_end(session, timeout_seconds=timeout_seconds),
            end_bound,
        )
        if start < end:
            intervals.append((start, end))

    intervals.sort(key=lambda interval: (interval[0], interval[1]))
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def allocate_interval_durations(
    intervals: list[tuple[datetime, datetime]],
    buckets: list[tuple[datetime, datetime]],
) -> list[int]:
    """Allocate merged intervals into buckets without losing second precision."""
    durations: list[int] = []
    for bucket_start, bucket_end in buckets:
        normalized_start = normalize_utc(bucket_start)
        normalized_end = normalize_utc(bucket_end)
        duration = sum(
            max(
                0,
                int(
                    (
                        min(interval_end, normalized_end)
                        - max(interval_start, normalized_start)
                    ).total_seconds()
                ),
            )
            for interval_start, interval_end in intervals
            if interval_start < normalized_end and interval_end > normalized_start
        )
        bucket_seconds = max(
            0, int((normalized_end - normalized_start).total_seconds())
        )
        durations.append(min(duration, bucket_seconds))
    return durations


def distinct_online_user_ids(
    sessions: list[UserPresenceSession], at: datetime
) -> set[int]:
    return {
        session.user_id for session in sessions if session_is_online_at(session, at)
    }
