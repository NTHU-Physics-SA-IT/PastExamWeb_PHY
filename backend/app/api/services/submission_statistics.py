from datetime import UTC, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.models.models import (
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    SubmissionStatisticsPoint,
    SubmissionStatisticsRead,
    SubmissionStatisticsSummary,
)

SUBMISSION_RANGE_CONFIG = {
    "24h": ("time", 10, 144),
    "48h": ("time", 20, 144),
    "72h": ("time", 30, 144),
    "7d": ("date", 4 * 60, 42),
    "30d": ("date", 12 * 60, 60),
    "90d": ("date", 24 * 60, 90),
}
PRODUCT_TIMEZONE = ZoneInfo(settings.PRODUCT_TIMEZONE)


async def record_submission_event(db, submission: ArchiveSubmission) -> None:
    """Persist the one immutable statistics event created with a submission."""
    if submission.id is None:
        await db.flush()
    if submission.id is None:
        raise ValueError("Submission must have an id before recording its event")

    db.add(
        ArchiveSubmissionEvent(
            submission_id=submission.id,
            submitted_at=submission.created_at,
        )
    )


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def align_product_bucket(value: datetime, bucket_minutes: int) -> datetime:
    value_local = normalize_utc(value).astimezone(PRODUCT_TIMEZONE)
    local_midnight = datetime.combine(value_local.date(), time.min, tzinfo=PRODUCT_TIMEZONE)
    elapsed_minutes = value_local.hour * 60 + value_local.minute
    aligned_minutes = (elapsed_minutes // bucket_minutes) * bucket_minutes
    return (local_midnight + timedelta(minutes=aligned_minutes)).astimezone(UTC)


def get_submission_statistics_window(range_key: str, now: datetime):
    mode, bucket_minutes, bucket_count = SUBMISSION_RANGE_CONFIG[range_key]
    current_start = align_product_bucket(now, bucket_minutes)
    first_start = current_start - timedelta(minutes=(bucket_count - 1) * bucket_minutes)
    range_end = current_start + timedelta(minutes=bucket_minutes)
    return mode, bucket_minutes, bucket_count, first_start, range_end


def build_submission_statistics(
    *,
    range_key: str,
    counts_by_bucket_start: dict[datetime, int],
    now: datetime,
) -> SubmissionStatisticsRead:
    mode, bucket_minutes, bucket_count, first_start, range_end = (
        get_submission_statistics_window(range_key, now)
    )
    normalized_counts = {
        normalize_utc(start): max(0, int(count))
        for start, count in counts_by_bucket_start.items()
    }
    points = []
    for index in range(bucket_count):
        start = first_start + timedelta(minutes=index * bucket_minutes)
        end = start + timedelta(minutes=bucket_minutes)
        points.append(
            SubmissionStatisticsPoint(
                start=start,
                end=end,
                count=normalized_counts.get(start, 0),
            )
        )

    counts = [point.count for point in points]
    total = sum(counts)
    return SubmissionStatisticsRead(
        mode=mode,
        range=range_key,
        timezone=settings.PRODUCT_TIMEZONE,
        bucket_minutes=bucket_minutes,
        range_start=first_start,
        range_end=range_end,
        summary=SubmissionStatisticsSummary(
            total=total,
            peak=max(counts, default=0),
            average=round(total / bucket_count, 1),
        ),
        points=points,
    )
