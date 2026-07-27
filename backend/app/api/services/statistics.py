from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import Archive, Course, User
from app.api.services.presence import distinct_online_user_ids, load_presence_sessions

router = APIRouter()
logger = logging.getLogger(__name__)


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

        now_utc = datetime.now(timezone.utc)
        presence_sessions = await load_presence_sessions(
            db, range_start=now_utc, range_end=now_utc
        )
        online_users = len(distinct_online_user_ids(presence_sessions, now_utc))

        today_start = datetime.now(timezone.utc).replace(
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
