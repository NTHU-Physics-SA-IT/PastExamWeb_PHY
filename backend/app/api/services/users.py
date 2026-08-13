from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.presence import (
    ONLINE_TIMEOUT_SECONDS,
    allocate_interval_durations,
    distinct_online_user_ids,
    load_presence_sessions,
    merge_presence_intervals,
)
from app.core.config import settings
from app.db.session import get_session
from app.models.models import (
    AdminUserRead,
    ArchiveSubmission,
    OnlineStatisticsPoint,
    OnlineStatisticsRead,
    SubmissionStatus,
    User,
    UserCreate,
    UserNicknameUpdate,
    UserOnlineDurationPoint,
    UserOnlineDurationRead,
    UserPasswordResetRequest,
    UserPresenceSession,
    UserRead,
    UserRoles,
    UserSubmissionRecordRead,
    UserSubmissionStatsRead,
    UserSubmissionStatusCounts,
    UserUpdate,
)
from app.services.nthu_affiliation import (
    classify_nthu_affiliation,
    parse_nthu_student_affiliation,
)
from app.utils.auth import get_current_user, get_password_hash

router = APIRouter()

NICKNAME_MAX_LENGTH = 15
ONLINE_RANGE_CONFIG = {
    "24h": (10, 144),
    "48h": (20, 144),
    "72h": (30, 144),
    "7d": (4 * 60, 42),
    "30d": (12 * 60, 60),
    "90d": (24 * 60, 90),
}
USER_ONLINE_DURATION_DAYS = {7, 30, 90}
PRODUCT_TIMEZONE = ZoneInfo(settings.PRODUCT_TIMEZONE)


def _normalize_timestamp(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _get_user_online_status(user: User, is_online: bool = False):
    if not user.last_login and not user.last_seen_at:
        return False, "從未登入"
    return is_online, "在線" if is_online else "離線"


def _to_user_read(
    user: User, contributor_experience: int = 0, is_online: bool = False
) -> UserRead:
    is_online, status_label = _get_user_online_status(user, is_online)
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        nickname=user.nickname,
        is_admin=user.is_admin,
        is_local=user.is_local,
        last_login=user.last_login,
        last_login_at=user.last_login,
        last_seen_at=user.last_seen_at,
        last_logout_at=user.last_logout,
        is_online=is_online,
        online_status_label=status_label,
        contributor_experience=contributor_experience,
    )


def _to_admin_user_read(
    user: User, contributor_experience: int = 0, is_online: bool = False
) -> AdminUserRead:
    base = _to_user_read(user, contributor_experience, is_online)
    parsed_affiliation = parse_nthu_student_affiliation(user.student_id)
    account_source = (
        "local"
        if user.is_local
        else "nthu"
        if user.oauth_provider == "nthu"
        else "unknown"
    )
    affiliation = (
        classify_nthu_affiliation(user.student_id) if account_source == "nthu" else None
    )
    return AdminUserRead(
        **base.model_dump(),
        account_source=account_source,
        student_id=user.student_id,
        department_code=affiliation.department_code if affiliation else None,
        department_name=affiliation.department_name if affiliation else None,
        affiliation_status=parsed_affiliation.status.value,
        nthu_affiliation_kind=affiliation.kind.value if affiliation else None,
        nthu_affiliation_label=affiliation.label if affiliation else None,
        nthu_classification_source=(
            affiliation.classification_source.value if affiliation else None
        ),
    )


@router.get("/admin/users", response_model=list[AdminUserRead])
async def get_users(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Get all users (admin only)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    result = await db.execute(select(User).where(User.deleted_at.is_(None)))
    users = result.scalars().all()
    experience_result = await db.execute(
        select(ArchiveSubmission.requester_id, func.count(ArchiveSubmission.id))
        .where(
            ArchiveSubmission.status.in_(
                [SubmissionStatus.APPROVED, SubmissionStatus.TAKEDOWN]
            )
        )
        .group_by(ArchiveSubmission.requester_id)
    )
    experience_by_user = {
        requester_id: int(experience)
        for requester_id, experience in experience_result.all()
    }
    now_utc = datetime.now(UTC)
    active_sessions = await load_presence_sessions(
        db,
        range_start=now_utc,
        range_end=now_utc,
    )
    online_user_ids = distinct_online_user_ids(active_sessions, now_utc)
    return [
        _to_admin_user_read(
            user,
            experience_by_user.get(user.id, 0),
            user.id in online_user_ids,
        )
        for user in users
    ]


def _align_utc_bucket(value: datetime, bucket_minutes: int) -> datetime:
    value_utc = _normalize_timestamp(value).astimezone(UTC)
    minutes = value_utc.hour * 60 + value_utc.minute
    aligned = (minutes // bucket_minutes) * bucket_minutes
    return value_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        minutes=aligned
    )


def build_online_statistics(
    *,
    range_key: str,
    sessions: list[UserPresenceSession],
    now: datetime,
    history_started_at: datetime | None,
) -> OnlineStatisticsRead:
    bucket_minutes, bucket_count = ONLINE_RANGE_CONFIG[range_key]
    now_utc = _normalize_timestamp(now).astimezone(UTC)
    current_start = _align_utc_bucket(now_utc, bucket_minutes)
    first_start = current_start - timedelta(minutes=(bucket_count - 1) * bucket_minutes)
    points = []
    normalized_history_start = (
        _normalize_timestamp(history_started_at).astimezone(UTC)
        if history_started_at
        else None
    )
    for index in range(bucket_count):
        start = first_start + timedelta(minutes=index * bucket_minutes)
        end = start + timedelta(minutes=bucket_minutes)
        sample_at = now_utc if index == bucket_count - 1 else end
        points.append(
            OnlineStatisticsPoint(
                start=start,
                end=end,
                at=sample_at,
                count=len(distinct_online_user_ids(sessions, sample_at)),
                has_data=bool(
                    normalized_history_start and sample_at >= normalized_history_start
                ),
            )
        )
    available_counts = [point.count for point in points if point.has_data]
    return OnlineStatisticsRead(
        range=range_key,
        bucket_minutes=bucket_minutes,
        timezone="UTC",
        online_timeout_seconds=ONLINE_TIMEOUT_SECONDS,
        current_online=points[-1].count if points and points[-1].has_data else 0,
        peak_online=max(available_counts, default=0),
        average_online=(
            round(sum(available_counts) / len(available_counts), 2)
            if available_counts
            else 0
        ),
        history_started_at=history_started_at,
        points=points,
    )


@router.get("/admin/online-statistics", response_model=OnlineStatisticsRead)
async def get_online_statistics(
    range_key: str = Query(default="24h", alias="range"),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    if range_key not in ONLINE_RANGE_CONFIG:
        raise HTTPException(
            status_code=422, detail="Unsupported online statistics range"
        )

    now_utc = datetime.now(UTC)
    bucket_minutes, bucket_count = ONLINE_RANGE_CONFIG[range_key]
    current_start = _align_utc_bucket(now_utc, bucket_minutes)
    range_start = current_start - timedelta(minutes=(bucket_count - 1) * bucket_minutes)
    sessions = await load_presence_sessions(
        db,
        range_start=range_start,
        range_end=now_utc,
    )
    history_result = await db.execute(select(func.min(UserPresenceSession.started_at)))
    return build_online_statistics(
        range_key=range_key,
        sessions=sessions,
        now=now_utc,
        history_started_at=history_result.scalar_one_or_none(),
    )


def build_user_online_duration(
    *,
    user_id: int,
    mode: str,
    sessions: list[UserPresenceSession],
    range_start: datetime,
    bucket_count: int,
    bucket_size: timedelta,
    now: datetime,
    history_started_at: datetime | None,
    display_timezone: str = settings.PRODUCT_TIMEZONE,
) -> UserOnlineDurationRead:
    normalized_start = _normalize_timestamp(range_start).astimezone(UTC)
    normalized_now = _normalize_timestamp(now).astimezone(UTC)
    buckets = [
        (
            normalized_start + index * bucket_size,
            normalized_start + (index + 1) * bucket_size,
        )
        for index in range(bucket_count)
    ]
    range_end = buckets[-1][1]
    intervals = merge_presence_intervals(
        sessions,
        range_start=normalized_start,
        range_end=range_end,
        now=normalized_now,
    )
    durations = allocate_interval_durations(intervals, buckets)
    normalized_history_start = (
        _normalize_timestamp(history_started_at).astimezone(UTC)
        if history_started_at
        else None
    )
    return UserOnlineDurationRead(
        user_id=user_id,
        mode=mode,
        timezone=display_timezone,
        online_timeout_seconds=ONLINE_TIMEOUT_SECONDS,
        range_start=normalized_start,
        range_end=range_end,
        history_started_at=normalized_history_start,
        points=[
            UserOnlineDurationPoint(
                start=start,
                end=end,
                duration_seconds=duration,
                has_data=bool(
                    normalized_history_start
                    and start < normalized_now
                    and end > normalized_history_start
                ),
            )
            for (start, end), duration in zip(buckets, durations, strict=True)
        ],
    )


def _product_date(value: datetime) -> date:
    return _normalize_timestamp(value).astimezone(PRODUCT_TIMEZONE).date()


def _product_midnight_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=PRODUCT_TIMEZONE).astimezone(
        UTC
    )


@router.get(
    "/admin/users/{user_id}/online-duration",
    response_model=UserOnlineDurationRead,
)
async def get_user_online_duration(
    user_id: int,
    mode: str = Query(default="hourly"),
    selected_date: date | None = Query(default=None, alias="date"),
    days: int = Query(default=7),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    if mode not in {"hourly", "daily"}:
        raise HTTPException(status_code=422, detail="Unsupported online duration mode")

    user = await db.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    now_utc = datetime.now(UTC)
    today = _product_date(now_utc)
    if mode == "hourly":
        target_date = selected_date or today
        if target_date > today or target_date < today - timedelta(days=6):
            raise HTTPException(
                status_code=422, detail="Hourly date must be within the last 7 days"
            )
        range_start = _product_midnight_utc(target_date)
        bucket_count = 24
        bucket_size = timedelta(hours=1)
    else:
        if days not in USER_ONLINE_DURATION_DAYS:
            raise HTTPException(
                status_code=422, detail="Daily days must be 7, 30, or 90"
            )
        range_start = _product_midnight_utc(today - timedelta(days=days - 1))
        bucket_count = days
        bucket_size = timedelta(days=1)

    range_end = range_start + bucket_count * bucket_size
    sessions = await load_presence_sessions(
        db,
        range_start=range_start,
        range_end=min(range_end, now_utc),
        user_id=user_id,
    )
    history_result = await db.execute(
        select(func.min(UserPresenceSession.started_at)).where(
            UserPresenceSession.user_id == user_id
        )
    )
    return build_user_online_duration(
        user_id=user_id,
        mode=mode,
        sessions=sessions,
        range_start=range_start,
        bucket_count=bucket_count,
        bucket_size=bucket_size,
        now=now_utc,
        history_started_at=history_result.scalar_one_or_none(),
    )


@router.get(
    "/admin/users/{user_id}/submission-stats",
    response_model=UserSubmissionStatsRead,
)
async def get_user_submission_stats(
    user_id: int,
    include_records: bool = False,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Return one user's archive submission status totals for administrators."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    user_result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    counts_result = await db.execute(
        select(ArchiveSubmission.status, func.count(ArchiveSubmission.id))
        .where(ArchiveSubmission.requester_id == user_id)
        .group_by(ArchiveSubmission.status)
    )
    counts = {submission_status.value: 0 for submission_status in SubmissionStatus}
    for submission_status, count in counts_result.all():
        status_key = (
            submission_status.value
            if isinstance(submission_status, SubmissionStatus)
            else str(submission_status)
        )
        if status_key in counts:
            counts[status_key] = int(count)

    contributor_experience = (
        counts[SubmissionStatus.APPROVED.value]
        + counts[SubmissionStatus.TAKEDOWN.value]
    )
    submission_records = []
    if include_records:
        records_result = await db.execute(
            select(ArchiveSubmission)
            .where(ArchiveSubmission.requester_id == user_id)
            .order_by(ArchiveSubmission.created_at.desc(), ArchiveSubmission.id.desc())
        )
        submission_records = [
            UserSubmissionRecordRead(
                id=submission.id,
                status=submission.status,
                archive_type=submission.archive_type,
                course_name=submission.requested_course_name or submission.subject,
                exam_name=submission.name,
                academic_year=submission.academic_year,
                professor=submission.professor,
                has_answers=submission.has_answers,
                requested_course_name=submission.requested_course_name,
                requested_category_key=submission.requested_category_key,
                is_admin_upload=submission.is_admin_upload,
                submitted_at=submission.created_at,
                reviewed_at=submission.reviewed_at,
                review_comment=submission.review_note,
            )
            for submission in records_result.scalars().all()
        ]
    return UserSubmissionStatsRead(
        user_id=user.id,
        name=user.name,
        contributor_experience=contributor_experience,
        total_count=sum(counts.values()),
        status_counts=UserSubmissionStatusCounts(**counts),
        records_total=len(submission_records)
        if include_records
        else sum(counts.values()),
        submission_records=submission_records,
    )


@router.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Reset password for a local user (admin only)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.is_local:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="此帳號不是本地帳號，無法由系統重設密碼。",
        )

    new_password = payload.new_password.strip() if payload.new_password else ""

    if not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="新密碼不可為空"
        )

    user.password_hash = get_password_hash(new_password)
    await db.commit()

    return {"message": "密碼已重設"}


@router.post("/admin/users", response_model=UserRead)
async def create_user(
    user_data: UserCreate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Create a new user (admin only)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    result = await db.execute(select(User).where(User.name == user_data.name))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this name already exists",
        )
    hashed_password = get_password_hash(user_data.password)
    user = User(
        name=user_data.name,
        nickname=user_data.name,
        email=user_data.email,
        password_hash=hashed_password,
        is_admin=user_data.is_admin,
        is_local=True,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.get("/me", response_model=UserRead)
async def get_me(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    user = await db.scalar(
        select(User).where(User.id == current_user.user_id, User.deleted_at.is_(None))
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if not user.nickname:
        user.nickname = user.name
        await db.commit()
        await db.refresh(user)
    return user


@router.patch("/me/nickname", response_model=UserRead)
async def update_my_nickname(
    payload: UserNicknameUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    user = await db.scalar(
        select(User).where(User.id == current_user.user_id, User.deleted_at.is_(None))
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    nickname = (payload.nickname or "").strip()
    if not nickname:
        nickname = user.name
    if len(nickname) > NICKNAME_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"暱稱超出 {NICKNAME_MAX_LENGTH} 字",
        )

    user.nickname = nickname
    if payload.show_level_title is not None:
        user.show_level_title = payload.show_level_title
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/admin/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update a user (admin only)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    provider_profile_changed = not user.is_local and (
        (user_data.name is not None and user_data.name != user.name)
        or (user_data.email is not None and user_data.email != user.email)
    )
    if provider_profile_changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="清大 OAuth 帳號的使用者名稱與電子郵件由身分提供者管理，無法手動修改。",
        )

    if user_data.name is not None:
        result = await db.execute(
            select(User).where(User.name == user_data.name, User.id != user_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this name already exists",
            )
        user.name = user_data.name

    if user_data.email is not None:
        result = await db.execute(
            select(User).where(User.email == user_data.email, User.id != user_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            )
        user.email = user_data.email

    if user_data.password is not None:
        user.password_hash = get_password_hash(user_data.password)

    if user_data.is_admin is not None:
        user.is_admin = user_data.is_admin

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Delete a user (admin only)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    if current_user.user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself"
        )
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    user.deleted_at = datetime.now(UTC)
    user.deleted_by_id = current_user.user_id
    await db.commit()

    return {"detail": "User deleted successfully"}
