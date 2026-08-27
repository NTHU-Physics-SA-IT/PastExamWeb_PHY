from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

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
        ("7d", 1440, 7),
        ("30d", 1440, 30),
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
    assert result.timezone == "Asia/Taipei"
    assert len(result.points) == bucket_count
    assert result.current_online == 1
    assert result.peak_online == 1
    assert 0 < result.average_online <= 1
    assert "at" not in result.points[-1].model_dump()


def test_sessions_are_distinct_per_user_and_all_activity_in_bucket_is_counted():
    sessions = [
        make_session(
            1,
            started_at=datetime(2026, 7, 12, 23, 51, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 12, 23, 53, tzinfo=UTC),
            ended_at=datetime(2026, 7, 12, 23, 53, tzinfo=UTC),
        ),
        make_session(
            1,
            started_at=datetime(2026, 7, 12, 23, 52, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 12, 23, 54, tzinfo=UTC),
            ended_at=datetime(2026, 7, 12, 23, 54, tzinfo=UTC),
            identifier="b" * 64,
        ),
        make_session(
            2,
            started_at=datetime(2026, 7, 12, 23, 57, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 12, 23, 59, tzinfo=UTC),
            ended_at=datetime(2026, 7, 12, 23, 59, tzinfo=UTC),
        ),
    ]
    result = build_online_statistics(
        range_key="24h",
        sessions=sessions,
        now=NOW,
        history_started_at=sessions[0].started_at,
    )

    bucket = next(
        point
        for point in result.points
        if point.start == datetime(2026, 7, 12, 23, 50, tzinfo=UTC)
    )
    assert bucket.active_users == 2


def test_short_session_between_sample_instants_is_counted_in_bucket():
    session = make_session(
        1,
        started_at=datetime(2026, 7, 12, 23, 51, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 12, 23, 53, tzinfo=UTC),
        ended_at=datetime(2026, 7, 12, 23, 53, tzinfo=UTC),
    )

    result = build_online_statistics(
        range_key="24h",
        sessions=[session],
        now=NOW,
        history_started_at=session.started_at,
    )

    bucket = next(
        point
        for point in result.points
        if point.start == datetime(2026, 7, 12, 23, 50, tzinfo=UTC)
    )
    assert bucket.active_users == 1


def test_session_crossing_bucket_boundary_contributes_to_both_buckets():
    session = make_session(
        1,
        started_at=datetime(2026, 7, 12, 23, 59, tzinfo=UTC),
        last_seen_at=NOW,
    )

    result = build_online_statistics(
        range_key="24h",
        sessions=[session],
        now=NOW,
        history_started_at=session.started_at,
    )

    assert [point.active_users for point in result.points[-2:]] == [1, 1]


@pytest.mark.parametrize(("range_key", "days"), [("7d", 7), ("30d", 30), ("90d", 90)])
def test_date_ranges_use_product_timezone_calendar_days(range_key, days):
    taipei = ZoneInfo("Asia/Taipei")
    local_now = datetime(2026, 7, 13, 12, 0, tzinfo=taipei)
    session = make_session(
        1,
        started_at=datetime(2026, 7, 12, 23, 58, tzinfo=taipei).astimezone(UTC),
        last_seen_at=datetime(2026, 7, 13, 0, 2, tzinfo=taipei).astimezone(UTC),
        ended_at=datetime(2026, 7, 13, 0, 2, tzinfo=taipei).astimezone(UTC),
    )

    result = build_online_statistics(
        range_key=range_key,
        sessions=[session],
        now=local_now,
        history_started_at=session.started_at,
    )

    assert len(result.points) == days
    assert all(
        point.start.astimezone(taipei).time().isoformat() == "00:00:00"
        and point.end.astimezone(taipei).time().isoformat() == "00:00:00"
        for point in result.points
    )
    assert [point.active_users for point in result.points[-2:]] == [1, 1]


def test_peak_and_time_weighted_average_use_complete_distinct_user_intervals():
    now = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
    sessions = [
        make_session(
            1,
            started_at=now - timedelta(minutes=10),
            last_seen_at=now - timedelta(minutes=5),
            ended_at=now,
        ),
        make_session(
            1,
            started_at=now - timedelta(minutes=3),
            last_seen_at=now,
            ended_at=now,
            identifier="b" * 64,
        ),
        make_session(
            2,
            started_at=now - timedelta(minutes=5),
            last_seen_at=now,
            ended_at=now,
        ),
    ]

    result = build_online_statistics(
        range_key="24h",
        sessions=sessions,
        now=now,
        history_started_at=now - timedelta(minutes=10),
    )

    assert result.current_online == 0
    assert result.peak_online == 2
    assert result.average_online == 1.5


def test_history_availability_and_current_partial_bucket_use_observed_time_only():
    now = datetime(2026, 7, 13, 0, 1, tzinfo=UTC)
    history_start = now - timedelta(seconds=30)
    session = make_session(
        1,
        started_at=history_start,
        last_seen_at=now,
    )

    result = build_online_statistics(
        range_key="24h",
        sessions=[session],
        now=now,
        history_started_at=history_start,
    )

    assert all(not point.has_data for point in result.points[:-1])
    assert result.points[-1].has_data
    assert result.points[-1].active_users == 1
    assert result.current_online == 1
    assert result.peak_online == 1
    assert result.average_online == 1


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
