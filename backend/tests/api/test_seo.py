import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    SubmissionStatus,
)


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
        takedown_course = Course(
            name=f"Sitemap takedown {suffix}",
            category=CourseCategory.FRESHMAN.value,
        )
        deleted_archive_course = Course(
            name=f"Sitemap deleted archive {suffix}",
            category=CourseCategory.FRESHMAN.value,
        )
        deleted_course = Course(
            name=f"Sitemap deleted course {suffix}",
            category=CourseCategory.FRESHMAN.value,
            deleted_at=datetime.now(timezone.utc),
        )
        session.add_all(
            [
                public_course,
                empty_course,
                takedown_course,
                deleted_archive_course,
                deleted_course,
            ]
        )
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
        takedown_archive = Archive(
            name=f"Sitemap takedown archive {suffix}",
            academic_year=20261,
            archive_type=ArchiveType.MIDTERM,
            professor="Professor Sitemap",
            has_answers=False,
            object_name=f"private/takedown-{suffix}.pdf",
            course_id=takedown_course.id,
            uploader_id=uploader.id,
        )
        deleted_archive = Archive(
            name=f"Sitemap deleted archive {suffix}",
            academic_year=20261,
            archive_type=ArchiveType.MIDTERM,
            professor="Professor Sitemap",
            has_answers=False,
            object_name=f"private/deleted-{suffix}.pdf",
            course_id=deleted_archive_course.id,
            uploader_id=uploader.id,
            deleted_at=datetime.now(timezone.utc),
        )
        deleted_course_archive = Archive(
            name=f"Sitemap deleted course archive {suffix}",
            academic_year=20261,
            archive_type=ArchiveType.MIDTERM,
            professor="Professor Sitemap",
            has_answers=False,
            object_name=f"private/deleted-course-{suffix}.pdf",
            course_id=deleted_course.id,
            uploader_id=uploader.id,
        )
        session.add_all(
            [archive, takedown_archive, deleted_archive, deleted_course_archive]
        )
        await session.flush()
        takedown_submission = ArchiveSubmission(
            subject=takedown_course.name,
            category=CourseCategory.FRESHMAN.value,
            name=takedown_archive.name,
            academic_year=takedown_archive.academic_year,
            archive_type=takedown_archive.archive_type,
            professor=takedown_archive.professor,
            has_answers=takedown_archive.has_answers,
            object_name=f"submissions/{suffix}.pdf",
            status=SubmissionStatus.TAKEDOWN,
            requester_id=uploader.id,
            created_archive_id=takedown_archive.id,
        )
        session.add(takedown_submission)
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
        assert (
            f"https://physarchive.com/courses/{takedown_course.id}" not in response.text
        )
        assert (
            f"https://physarchive.com/courses/{deleted_archive_course.id}"
            not in response.text
        )
        assert (
            f"https://physarchive.com/courses/{deleted_course.id}" not in response.text
        )
        assert "/archive" not in response.text
        assert "/admin" not in response.text
    finally:
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id == takedown_submission.id
                )
            )
            await session.execute(
                delete(Archive).where(
                    Archive.id.in_(
                        [
                            archive.id,
                            takedown_archive.id,
                            deleted_archive.id,
                            deleted_course_archive.id,
                        ]
                    )
                )
            )
            await session.execute(
                delete(Course).where(
                    Course.id.in_(
                        [
                            public_course.id,
                            empty_course.id,
                            takedown_course.id,
                            deleted_archive_course.id,
                            deleted_course.id,
                        ]
                    )
                )
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
