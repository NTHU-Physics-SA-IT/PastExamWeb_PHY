from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.services.presence import (
    ONLINE_TIMEOUT_SECONDS,
    allocate_interval_durations,
    merge_presence_intervals,
)
from app.api.services.users import (
    _product_date,
    _product_midnight_utc,
    build_user_online_duration,
    get_user_online_duration,
)
from app.models.models import User, UserPresenceSession, UserRoles

NOW = datetime(2026, 7, 15, 15, 30, tzinfo=UTC)


def session(
    start: datetime,
    end: datetime,
    *,
    user_id: int = 7,
    identifier: str = "a" * 64,
    open_session: bool = False,
) -> UserPresenceSession:
    return UserPresenceSession(
        user_id=user_id,
        session_identifier=identifier,
        started_at=start,
        last_seen_at=end - timedelta(seconds=ONLINE_TIMEOUT_SECONDS),
        ended_at=None if open_session else end,
    )


def test_merges_single_disjoint_overlapping_contained_and_multi_device_sessions():
    start = NOW - timedelta(hours=6)
    sessions = [
        session(start, start + timedelta(hours=2)),
        session(
            start + timedelta(minutes=30),
            start + timedelta(hours=1),
            identifier="b" * 64,
        ),
        session(
            start + timedelta(hours=1), start + timedelta(hours=3), identifier="c" * 64
        ),
        session(
            start + timedelta(hours=4), start + timedelta(hours=5), identifier="d" * 64
        ),
    ]

    assert merge_presence_intervals(
        sessions,
        range_start=start,
        range_end=NOW,
        now=NOW,
    ) == [
        (start, start + timedelta(hours=3)),
        (start + timedelta(hours=4), start + timedelta(hours=5)),
    ]


def test_clamps_open_expired_future_and_partially_overlapping_sessions():
    range_start = NOW - timedelta(hours=2)
    open_presence = session(
        NOW - timedelta(minutes=10),
        NOW + timedelta(seconds=ONLINE_TIMEOUT_SECONDS),
        open_session=True,
    )
    expired = session(NOW - timedelta(hours=4), NOW - timedelta(hours=3))
    future = session(NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    partial = session(
        range_start - timedelta(hours=1), range_start + timedelta(minutes=15)
    )

    assert merge_presence_intervals(
        [open_presence, expired, future, partial],
        range_start=range_start,
        range_end=NOW + timedelta(hours=3),
        now=NOW,
    ) == [
        (range_start, range_start + timedelta(minutes=15)),
        (NOW - timedelta(minutes=10), NOW),
    ]


def test_splits_session_across_hours_midnight_month_and_range_edges():
    range_start = datetime(2026, 6, 30, 23, 0, tzinfo=UTC)
    buckets = [
        (range_start, range_start + timedelta(hours=1)),
        (range_start + timedelta(hours=1), range_start + timedelta(hours=2)),
    ]
    intervals = [
        (
            datetime(2026, 6, 30, 23, 45, tzinfo=UTC),
            datetime(2026, 7, 1, 0, 20, tzinfo=UTC),
        )
    ]

    assert allocate_interval_durations(intervals, buckets) == [900, 1200]


@pytest.mark.parametrize(("days", "point_count"), [(7, 7), (30, 30), (90, 90)])
def test_daily_contract_has_fixed_points_and_never_exceeds_bucket(days, point_count):
    range_start = datetime(2026, 7, 15, tzinfo=UTC) - timedelta(days=days - 1)
    result = build_user_online_duration(
        user_id=7,
        mode="daily",
        sessions=[session(range_start, range_start + timedelta(days=2))],
        range_start=range_start,
        bucket_count=days,
        bucket_size=timedelta(days=1),
        now=NOW,
        history_started_at=range_start,
    )

    assert len(result.points) == point_count
    assert all(0 <= point.duration_seconds <= 86400 for point in result.points)
    assert result.points[0].duration_seconds == 86400
    assert result.points[1].duration_seconds == 86400


def test_hourly_contract_has_24_points_and_expected_split():
    range_start = datetime(2026, 7, 15, tzinfo=UTC)
    result = build_user_online_duration(
        user_id=7,
        mode="hourly",
        sessions=[
            session(
                range_start + timedelta(hours=13, minutes=45),
                range_start + timedelta(hours=14, minutes=20),
            )
        ],
        range_start=range_start,
        bucket_count=24,
        bucket_size=timedelta(hours=1),
        now=NOW,
        history_started_at=range_start,
    )

    assert len(result.points) == 24
    assert result.points[13].duration_seconds == 900
    assert result.points[14].duration_seconds == 1200
    assert all(0 <= point.duration_seconds <= 3600 for point in result.points)
    assert all(point.duration_seconds == 0 for point in result.points[16:])


def test_product_date_and_midnight_use_taipei_calendar_boundaries():
    utc_previous_day = datetime(2026, 7, 14, 16, 5, tzinfo=UTC)

    assert _product_date(utc_previous_day) == date(2026, 7, 15)
    assert _product_midnight_utc(date(2026, 7, 15)) == datetime(
        2026, 7, 14, 16, tzinfo=UTC
    )


def test_incomplete_product_day_keeps_24_points_partial_hour_and_future_zeroes():
    range_start = _product_midnight_utc(date(2026, 7, 15))
    now = range_start + timedelta(hours=4, minutes=20)
    result = build_user_online_duration(
        user_id=7,
        mode="hourly",
        sessions=[
            session(
                range_start + timedelta(hours=4),
                now + timedelta(hours=1),
                open_session=True,
            )
        ],
        range_start=range_start,
        bucket_count=24,
        bucket_size=timedelta(hours=1),
        now=now,
        history_started_at=range_start,
    )

    assert result.timezone == "Asia/Taipei"
    assert len(result.points) == 24
    assert result.points[0].start == datetime(2026, 7, 14, 16, tzinfo=UTC)
    assert result.points[-1].end == datetime(2026, 7, 15, 16, tzinfo=UTC)
    assert result.points[4].duration_seconds == 1200
    assert all(point.duration_seconds == 0 for point in result.points[5:])
    assert all(point.has_data is False for point in result.points[5:])


def test_five_minutes_after_product_midnight_still_returns_24_points():
    range_start = _product_midnight_utc(date(2026, 7, 15))
    now = range_start + timedelta(minutes=5)
    result = build_user_online_duration(
        user_id=7,
        mode="hourly",
        sessions=[session(range_start, now + timedelta(hours=1), open_session=True)],
        range_start=range_start,
        bucket_count=24,
        bucket_size=timedelta(hours=1),
        now=now,
        history_started_at=range_start,
    )

    assert len(result.points) == 24
    assert result.points[0].duration_seconds == 300
    assert all(point.duration_seconds == 0 for point in result.points[1:])


class _ScalarCollection:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, *, values=None, scalar=None):
        self.values = values or []
        self.scalar = scalar

    def scalars(self):
        return _ScalarCollection(self.values)

    def scalar_one_or_none(self):
        return self.scalar


class _FakeDb:
    def __init__(self, *, user=True, sessions=None, history=None):
        self.user = (
            User(id=7, name="target", email="target@example.com") if user else None
        )
        self.sessions = sessions or []
        self.history = history
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.user

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 2:
            return _Result(values=self.sessions)
        return _Result(scalar=self.history)


@pytest.mark.asyncio
async def test_endpoint_permissions_not_found_and_validation():
    with pytest.raises(HTTPException) as forbidden:
        await get_user_online_duration(
            7,
            current_user=UserRoles(user_id=1, is_admin=False),
            db=None,
        )
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as missing:
        await get_user_online_duration(
            7,
            mode="hourly",
            current_user=UserRoles(user_id=1, is_admin=True),
            db=_FakeDb(user=False),
        )
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as bad_mode:
        await get_user_online_duration(
            7,
            mode="invalid",
            current_user=UserRoles(user_id=1, is_admin=True),
            db=_FakeDb(),
        )
    assert bad_mode.value.status_code == 422

    with pytest.raises(HTTPException) as bad_days:
        await get_user_online_duration(
            7,
            mode="daily",
            days=8,
            current_user=UserRoles(user_id=1, is_admin=True),
            db=_FakeDb(),
        )
    assert bad_days.value.status_code == 422

    product_today = _product_date(datetime.now(UTC))
    for invalid_date in (
        product_today + timedelta(days=1),
        product_today - timedelta(days=7),
    ):
        with pytest.raises(HTTPException) as bad_date:
            await get_user_online_duration(
                7,
                mode="hourly",
                selected_date=invalid_date,
                current_user=UserRoles(user_id=1, is_admin=True),
                db=_FakeDb(),
            )
        assert bad_date.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_returns_aggregates_only_and_bounds_query_to_user():
    db = _FakeDb(history=NOW - timedelta(days=2))
    result = await get_user_online_duration(
        7,
        mode="daily",
        days=7,
        current_user=UserRoles(user_id=1, is_admin=True),
        db=db,
    )
    payload = result.model_dump()

    assert result.user_id == 7
    assert result.mode == "daily"
    assert result.timezone == "Asia/Taipei"
    assert len(result.points) == 7
    assert isinstance(result.points[0].duration_seconds, int)
    assert "session_identifier" not in str(payload)
    assert "user_presence_sessions.user_id" in str(db.statements[1])
