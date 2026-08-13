import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.db.init_db import load_seed_data
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    SubmissionStatus,
)
from app.utils.auth import get_current_user


async def _create_course(session_maker, *, name: str, deleted: bool = False) -> Course:
    async with session_maker() as session:
        course = Course(name=name, category=CourseCategory.FRESHMAN.value)
        if deleted:
            course.deleted_at = datetime.now(timezone.utc)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course


async def _create_archive(
    session_maker,
    *,
    course_id: int,
    uploader_id: int,
    deleted: bool = False,
    name: str | None = None,
    object_name: str | None = None,
) -> Archive:
    async with session_maker() as session:
        archive = Archive(
            name=name or f"Public archive {uuid.uuid4().hex[:8]}",
            academic_year=20262,
            archive_type=ArchiveType.FINAL,
            professor="Professor Public",
            has_answers=True,
            object_name=object_name or f"private/{uuid.uuid4().hex}.pdf",
            course_id=course_id,
            uploader_id=uploader_id,
        )
        if deleted:
            archive.deleted_at = datetime.now(timezone.utc)
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        return archive


async def _link_submission(
    session_maker,
    *,
    archive: Archive,
    requester_id: int,
    status: SubmissionStatus,
    deleted: bool = False,
) -> ArchiveSubmission:
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=f"Course {archive.course_id}",
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            has_answers=archive.has_answers,
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=status,
            requester_id=requester_id,
            created_archive_id=archive.id,
        )
        if deleted:
            submission.deleted_at = datetime.now(timezone.utc)
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return submission


@pytest.mark.parametrize(
    ("sibling_status", "sibling_deleted", "expect_sibling"),
    [
        (SubmissionStatus.APPROVED, False, True),
        (SubmissionStatus.PENDING, False, False),
        (SubmissionStatus.REJECTED, False, False),
        (SubmissionStatus.TAKEDOWN, False, False),
        (SubmissionStatus.APPROVED, True, False),
    ],
    ids=["approved", "pending", "rejected", "takedown", "soft-deleted"],
)
@pytest.mark.asyncio
async def test_public_catalog_keeps_same_metadata_approved_sibling_independent(
    client: AsyncClient,
    session_maker,
    make_user,
    sibling_status: SubmissionStatus,
    sibling_deleted: bool,
    expect_sibling: bool,
):
    uploader = await make_user()
    marker = uuid.uuid4().hex
    course = await _create_course(
        session_maker,
        name=f"Same metadata public course {marker}",
    )
    archive_a = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=uploader.id,
        name="Shared final exam",
        object_name=f"private/{marker}-a.pdf",
    )
    archive_b = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=uploader.id,
        name="Shared final exam",
        object_name=f"private/{marker}-b.pdf",
    )
    submission_a = await _link_submission(
        session_maker,
        archive=archive_a,
        requester_id=uploader.id,
        status=sibling_status,
        deleted=sibling_deleted,
    )
    submission_b = await _link_submission(
        session_maker,
        archive=archive_b,
        requester_id=uploader.id,
        status=SubmissionStatus.APPROVED,
    )

    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = await client.get(f"/courses/public/{course.id}/archives")

        assert response.status_code == 200
        rows = response.json()
        rows_by_id = {row["id"]: row for row in rows}
        expected_ids = {archive_b.id}
        if expect_sibling:
            expected_ids.add(archive_a.id)
        assert set(rows_by_id) == expected_ids
        assert rows_by_id[archive_b.id] == {
            "id": archive_b.id,
            "name": archive_b.name,
            "academic_year": archive_b.academic_year,
            "archive_type": archive_b.archive_type.value,
            "professor": archive_b.professor,
            "has_answers": archive_b.has_answers,
        }
        for row in rows:
            assert "object_name" not in row
            assert "uploader_id" not in row
            assert "download_count" not in row
            assert "source_submission_ids" not in row
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id.in_([submission_a.id, submission_b.id])
                )
            )
            await session.execute(
                delete(Archive).where(Archive.id.in_([archive_a.id, archive_b.id]))
            )
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_anonymous_public_catalog_separates_course_discovery_from_archive_visibility(
    client: AsyncClient,
    session_maker,
    make_user,
):
    uploader = await make_user()
    suffix = uuid.uuid4().hex
    public_course = await _create_course(
        session_maker,
        name=f"Public SEO course {suffix}",
    )
    empty_course = await _create_course(
        session_maker,
        name=f"Empty SEO course {suffix}",
    )
    hidden_course = await _create_course(
        session_maker,
        name=f"Hidden SEO course {suffix}",
    )
    deleted_archive_course = await _create_course(
        session_maker,
        name=f"Deleted archive SEO course {suffix}",
    )
    deleted_course = await _create_course(
        session_maker,
        name=f"Deleted SEO course {suffix}",
        deleted=True,
    )

    public_archive = await _create_archive(
        session_maker,
        course_id=public_course.id,
        uploader_id=uploader.id,
    )
    hidden_archive = await _create_archive(
        session_maker,
        course_id=hidden_course.id,
        uploader_id=uploader.id,
    )
    hidden_submission = await _link_submission(
        session_maker,
        archive=hidden_archive,
        requester_id=uploader.id,
        status=SubmissionStatus.TAKEDOWN,
    )
    deleted_archive = await _create_archive(
        session_maker,
        course_id=deleted_archive_course.id,
        uploader_id=uploader.id,
        deleted=True,
    )

    app.dependency_overrides.pop(get_current_user, None)
    try:
        categories_response = await client.get("/courses/public/categories")
        catalog_response = await client.get("/courses/public")
        detail_response = await client.get(
            f"/courses/public/{public_course.id}/archives"
        )

        assert categories_response.status_code == 200
        assert catalog_response.status_code == 200
        assert detail_response.status_code == 200

        catalog_rows = [
            item for courses in catalog_response.json().values() for item in courses
        ]
        catalog_ids = {item["id"] for item in catalog_rows}
        assert public_course.id in catalog_ids
        assert empty_course.id in catalog_ids
        assert hidden_course.id in catalog_ids
        assert deleted_archive_course.id in catalog_ids
        assert deleted_course.id not in catalog_ids

        rows = detail_response.json()
        assert len(rows) == 1
        assert rows[0] == {
            "id": public_archive.id,
            "name": public_archive.name,
            "academic_year": public_archive.academic_year,
            "archive_type": public_archive.archive_type.value,
            "professor": public_archive.professor,
            "has_answers": public_archive.has_answers,
        }
        assert "object_name" not in rows[0]
        assert "uploader_id" not in rows[0]
        assert "download_count" not in rows[0]
        assert "source_submission_ids" not in rows[0]

        for course_id in (
            empty_course.id,
            hidden_course.id,
            deleted_archive_course.id,
        ):
            response = await client.get(f"/courses/public/{course_id}/archives")
            assert response.status_code == 200
            assert response.json() == []

        for course_id in (deleted_course.id, 2_000_000_000):
            response = await client.get(f"/courses/public/{course_id}/archives")
            assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id == hidden_submission.id
                )
            )
            await session.execute(
                delete(Archive).where(
                    Archive.id.in_(
                        [
                            public_archive.id,
                            hidden_archive.id,
                            deleted_archive.id,
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
                            hidden_course.id,
                            deleted_archive_course.id,
                            deleted_course.id,
                        ]
                    )
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_anonymous_public_catalog_exposes_fresh_seed_courses_without_archives(
    client: AsyncClient,
):
    app.dependency_overrides.pop(get_current_user, None)
    response = await client.get("/courses/public")

    assert response.status_code == 200
    catalog_rows = [item for courses in response.json().values() for item in courses]
    seed_course_names = {course["name"] for course in load_seed_data()["courses"]}
    catalog_course_names = {course["name"] for course in catalog_rows}
    assert seed_course_names <= catalog_course_names
