from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.services.presence import (
    ONLINE_TIMEOUT_SECONDS,
    distinct_online_user_ids,
    session_is_online_at,
)
from app.api.services.users import (
    ONLINE_RANGE_CONFIG,
    build_online_statistics,
    get_online_statistics,
)
from app.models.models import UserPresenceSession, UserRoles

NOW = datetime(2026, 7, 13, 0, 1, tzinfo=UTC)


def make_session(
    user_id: int,
    *,
    started_at: datetime,
    last_seen_at: datetime,
    ended_at: datetime | None = None,
    identifier: str = "a" * 64,
) -> UserPresenceSession:
    return UserPresenceSession(
        user_id=user_id,
        session_identifier=identifier,
        started_at=started_at,
        last_seen_at=last_seen_at,
        ended_at=ended_at,
    )


def test_presence_timeout_end_and_distinct_users():
    active = make_session(
        1,
        started_at=NOW - timedelta(minutes=3),
        last_seen_at=NOW - timedelta(minutes=1),
    )
    duplicate_device = make_session(
        1,
        started_at=NOW - timedelta(minutes=2),
        last_seen_at=NOW,
        identifier="b" * 64,
    )
    other_user = make_session(
        2,
        started_at=NOW - timedelta(minutes=1),
        last_seen_at=NOW,
    )
    expired = make_session(
        3,
        started_at=NOW - timedelta(minutes=10),
        last_seen_at=NOW - timedelta(seconds=ONLINE_TIMEOUT_SECONDS),
    )
    ended = make_session(
        4,
        started_at=NOW - timedelta(minutes=2),
        last_seen_at=NOW,
        ended_at=NOW,
    )

    assert session_is_online_at(active, NOW)
    assert not session_is_online_at(expired, NOW)
    assert not session_is_online_at(ended, NOW)
    assert distinct_online_user_ids(
        [active, duplicate_device, other_user, expired, ended], NOW
    ) == {1, 2}


@pytest.mark.parametrize(
    ("range_key", "bucket_minutes", "bucket_count"),
    [
        ("24h", 10, 144),
        ("48h", 20, 144),
        ("72h", 30, 144),
        ("7d", 240, 42),
        ("30d", 720, 60),
        ("90d", 1440, 90),
    ],
)
def test_online_statistics_bucket_contract(range_key, bucket_minutes, bucket_count):
    session = make_session(
        1,
        started_at=NOW - timedelta(minutes=30),
        last_seen_at=NOW,
    )
    result = build_online_statistics(
        range_key=range_key,
        sessions=[session],
        now=NOW,
        history_started_at=session.started_at,
    )

    assert ONLINE_RANGE_CONFIG[range_key] == (bucket_minutes, bucket_count)
    assert result.bucket_minutes == bucket_minutes
    assert len(result.points) == bucket_count
    assert result.points[-1].at == NOW
    assert result.current_online == 1
    assert result.peak_online == 1
    assert 0 < result.average_online <= 1


def test_session_crossing_midnight_is_counted_at_sample_points():
    session = make_session(
        1,
        started_at=datetime(2026, 7, 12, 23, 58, tzinfo=UTC),
        last_seen_at=NOW,
    )
    result = build_online_statistics(
        range_key="24h",
        sessions=[session],
        now=NOW,
        history_started_at=session.started_at,
    )

    assert result.points[-1].start == datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
    assert result.points[-1].count == 1
    assert sum(point.count for point in result.points[:-1]) == 1


@pytest.mark.asyncio
async def test_online_statistics_requires_admin_and_valid_range():
    with pytest.raises(HTTPException) as forbidden:
        await get_online_statistics(
            range_key="24h",
            current_user=UserRoles(user_id=1, is_admin=False),
            db=None,
        )
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as invalid:
        await get_online_statistics(
            range_key="invalid",
            current_user=UserRoles(user_id=1, is_admin=True),
            db=None,
        )
    assert invalid.value.status_code == 422
