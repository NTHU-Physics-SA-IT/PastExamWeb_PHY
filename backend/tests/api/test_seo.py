import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.models.models import Archive, ArchiveType, Course, CourseCategory


@pytest.mark.asyncio
async def test_sitemap_contains_only_courses_with_public_archives(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://physarchive.com/")
    uploader = await make_user()
    suffix = uuid.uuid4().hex

    async with session_maker() as session:
        public_course = Course(
            name=f"Sitemap public {suffix}",
            category=CourseCategory.FRESHMAN.value,
        )
        empty_course = Course(
            name=f"Sitemap empty {suffix}",
            category=CourseCategory.FRESHMAN.value,
        )
        session.add_all([public_course, empty_course])
        await session.flush()
        archive = Archive(
            name=f"Sitemap archive {suffix}",
            academic_year=20261,
            archive_type=ArchiveType.MIDTERM,
            professor="Professor Sitemap",
            has_answers=False,
            object_name=f"private/{suffix}.pdf",
            course_id=public_course.id,
            uploader_id=uploader.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(public_course)
        await session.refresh(empty_course)
        await session.refresh(archive)

    try:
        response = await client.get("/seo/sitemap.xml")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        assert "https://physarchive.com/" in response.text
        assert "https://physarchive.com/courses" in response.text
        assert f"https://physarchive.com/courses/{public_course.id}" in response.text
        assert f"https://physarchive.com/courses/{empty_course.id}" not in response.text
        assert "/archive" not in response.text
        assert "/admin" not in response.text
    finally:
        async with session_maker() as session:
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(
                delete(Course).where(Course.id.in_([public_course.id, empty_course.id]))
            )
            await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("site_url", "expected_rule"),
    [
        ("https://physarchive.com", "Allow: /"),
        ("http://localhost:8080", "Disallow: /"),
    ],
)
async def test_robots_uses_canonical_frontend_url_and_blocks_local_indexing(
    client: AsyncClient,
    monkeypatch,
    site_url,
    expected_rule,
):
    monkeypatch.setattr(settings, "FRONTEND_URL", site_url)

    response = await client.get("/seo/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert expected_rule in response.text
    assert f"Sitemap: {site_url}/sitemap.xml" in response.text
