import pytest_asyncio
from sqlalchemy import delete
from sqlmodel import select

from app.db.init_db import sync_course_catalog
from app.models.models import Course


@pytest_asyncio.fixture(autouse=True)
async def ensure_api_seed_course_catalog(session_maker):
    """Keep API tests independent from destructive migration-test ordering."""
    async with session_maker() as session:
        existing_course_ids = set(
            (await session.execute(select(Course.id))).scalars().all()
        )
        await sync_course_catalog(session)
        managed_course_ids = tuple(
            course_id
            for course_id in (
                await session.execute(select(Course.id).order_by(Course.id.asc()))
            ).scalars()
            if course_id not in existing_course_ids
        )

    yield

    if managed_course_ids:
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.id.in_(managed_course_ids))
            )
            await session.commit()
