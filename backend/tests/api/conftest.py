import pytest_asyncio

from app.db.init_db import sync_course_catalog


@pytest_asyncio.fixture(autouse=True)
async def ensure_api_seed_course_catalog(session_maker):
    """Keep API tests independent from destructive migration-test ordering."""
    async with session_maker() as session:
        await sync_course_catalog(session)
