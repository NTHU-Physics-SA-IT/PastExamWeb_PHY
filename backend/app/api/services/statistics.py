import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.presence import distinct_online_user_ids, load_presence_sessions
from app.db.session import get_session
from app.models.models import (
    AdminAnnouncementAttentionRead,
    AdminAttentionSummaryRead,
    AdminReportAttentionRead,
    AdminReviewAttentionRead,
    Archive,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveWishReport,
    CommentReport,
    CommentReportStatus,
    Course,
    HomepageSloganStatus,
    HomepageSloganSubmission,
    SubmissionStatus,
    SystemIssueReport,
    User,
)
from app.utils.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


async def _count(db: AsyncSession, model, *predicates) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(model).where(*predicates)) or 0
    )


@router.get("/admin/attention-summary", response_model=AdminAttentionSummaryRead)
async def get_admin_attention_summary(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    pending_submission = (
        ArchiveSubmission.status == SubmissionStatus.PENDING,
        ArchiveSubmission.deleted_at.is_(None),
    )
    requests_new_parent = or_(
        func.nullif(func.trim(ArchiveSubmission.requested_course_name), "").is_not(
            None
        ),
        func.nullif(func.trim(ArchiveSubmission.requested_category_key), "").is_not(
            None
        ),
    )
    new_parent_count = await _count(
        db, ArchiveSubmission, *pending_submission, requests_new_parent
    )
    existing_course_count = await _count(
        db, ArchiveSubmission, *pending_submission, ~requests_new_parent
    )
    pending_report = CommentReportStatus.PENDING.value
    archive_report_count = await _count(
        db,
        ArchiveReport,
        ArchiveReport.status == pending_report,
        ArchiveReport.deleted_at.is_(None),
    )
    comment_report_count = await _count(
        db,
        CommentReport,
        CommentReport.status == pending_report,
        CommentReport.deleted_at.is_(None),
    )
    wish_report_count = await _count(
        db,
        ArchiveWishReport,
        ArchiveWishReport.status == pending_report,
        ArchiveWishReport.deleted_at.is_(None),
    )
    system_issue_count = await _count(
        db,
        SystemIssueReport,
        SystemIssueReport.read_at.is_(None),
        SystemIssueReport.deleted_at.is_(None),
    )
    homepage_slogan_count = await _count(
        db,
        HomepageSloganSubmission,
        HomepageSloganSubmission.status == HomepageSloganStatus.PENDING.value,
    )

    return AdminAttentionSummaryRead(
        review_center=AdminReviewAttentionRead(
            new_course_or_category=new_parent_count,
            existing_course=existing_course_count,
            total=new_parent_count + existing_course_count,
        ),
        report_management=AdminReportAttentionRead(
            archive_reports=archive_report_count,
            comment_reports=comment_report_count,
            wish_reports=wish_report_count,
            system_issues=system_issue_count,
            total=(
                archive_report_count
                + comment_report_count
                + wish_report_count
                + system_issue_count
            ),
        ),
        announcement_management=AdminAnnouncementAttentionRead(
            homepage_slogans=homepage_slogan_count,
        ),
    )


@router.get("/statistics")
async def get_system_statistics(db: AsyncSession = Depends(get_session)):
    """Get system-wide statistics"""
    try:
        result = await db.execute(
            select(func.count(User.id)).where(User.deleted_at.is_(None))
        )
        total_users = result.scalar()

        result = await db.execute(
            select(func.count(Course.id)).where(Course.deleted_at.is_(None))
        )
        total_courses = result.scalar()

        result = await db.execute(
            select(func.count(Archive.id)).where(Archive.deleted_at.is_(None))
        )
        total_archives = result.scalar()

        result = await db.execute(
            select(func.coalesce(func.sum(Archive.download_count), 0)).where(
                Archive.deleted_at.is_(None)
            )
        )
        total_downloads = result.scalar()

        now_utc = datetime.now(UTC)
        presence_sessions = await load_presence_sessions(
            db, range_start=now_utc, range_end=now_utc
        )
        online_users = len(distinct_online_user_ids(presence_sessions, now_utc))

        today_start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await db.execute(
            select(func.count(User.id)).where(
                User.deleted_at.is_(None), User.last_login >= today_start
            )
        )
        active_today = result.scalar()

        return {
            "success": True,
            "data": {
                "totalUsers": total_users,
                "totalDownloads": total_downloads,
                "onlineUsers": online_users,
                "totalArchives": total_archives,
                "totalCourses": total_courses,
                "activeToday": active_today,
            },
        }

    except Exception:
        logger.exception("Error fetching statistics")
        return {
            "success": False,
            "error": "Failed to fetch statistics.",
            "data": {
                "totalUsers": 0,
                "totalDownloads": 0,
                "onlineUsers": 0,
                "totalArchives": 0,
                "totalCourses": 0,
                "activeToday": 0,
            },
        }
