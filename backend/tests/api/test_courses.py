import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from minio.error import S3Error
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services.archive_submission_lifecycle import (
    get_course_trash_previous_status,
    is_course_trash_lifecycle_reason,
)
from app.api.services.courses import (
    create_course,
    create_course_category,
    create_course_request,
    delete_archive,
    delete_course,
    get_archive_download_url,
    get_archive_preview_url,
    get_categorized_courses,
    get_course_archives,
    list_all_courses,
    update_archive,
    update_archive_course,
    update_course,
)
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    ArchiveUpdateCourse,
    Course,
    CourseCategory,
    CourseCategoryCreate,
    CourseCreate,
    CourseSubmission,
    CourseSubmissionCreate,
    CourseUpdate,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


async def _create_course(
    session_maker,
    *,
    name=None,
    category=CourseCategory.FRESHMAN,
):
    async with session_maker() as session:
        course = Course(
            name=name or "普通化學(一)",
            category=category,
        )
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course


async def _get_course_by_name(
    session_maker,
    *,
    name: str,
    category: CourseCategory,
):
    async with session_maker() as session:
        result = await session.execute(
            select(Course).where(
                Course.name == name,
                Course.category == category,
                Course.deleted_at.is_(None),
            )
        )
        return result.scalars().first()


async def _create_archive(
    session_maker,
    *,
    course_id: int,
    uploader_id: int,
    name=None,
    deleted: bool = False,
):
    async with session_maker() as session:
        archive = Archive(
            name=name or f"Archive {uuid.uuid4().hex[:6]}",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof. Test",
            has_answers=False,
            object_name=f"archives/{course_id}/{uuid.uuid4().hex}.pdf",
            course_id=course_id,
            uploader_id=uploader_id,
        )
        if deleted:
            archive.deleted_at = datetime.now(timezone.utc)
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        return archive


async def _create_linked_submission(
    session_maker,
    *,
    archive: Archive,
    requester_id: int,
):
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=f"Linked archive {archive.id}",
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            has_answers=archive.has_answers,
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.APPROVED,
            requester_id=requester_id,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return submission


async def _create_pending_course_lifecycle_context(
    session_maker,
    *,
    requester_id: int,
    label: str,
):
    unique = uuid.uuid4().hex
    course = await _create_course(
        session_maker,
        name=f"Course Trash Lifecycle {label} {unique}",
    )
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"Course Trash Exam {label} {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor=f"Course Trash Professor {label}",
            object_name=f"submissions/course-trash-{label}-{unique}.pdf",
            status=SubmissionStatus.PENDING,
            requester_id=requester_id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return course, submission


async def _review_course_lifecycle_context(
    client: AsyncClient,
    session_maker,
    *,
    submission_id: int,
    final_status: SubmissionStatus,
):
    approved_response = await client.post(
        f"/archives/admin/submissions/{submission_id}/approve",
        json={"note": "course lifecycle approval"},
    )
    assert approved_response.status_code == 200
    assert approved_response.json()["status"] == SubmissionStatus.APPROVED.value

    if final_status == SubmissionStatus.REJECTED:
        rejected_response = await client.post(
            f"/archives/admin/submissions/{submission_id}/reject",
            json={"note": "course lifecycle rejection"},
        )
        assert rejected_response.status_code == 200
        assert rejected_response.json()["status"] == SubmissionStatus.REJECTED.value

    async with session_maker() as session:
        submission = await session.get(ArchiveSubmission, submission_id)
        archive = await session.get(Archive, submission.created_archive_id)
        assert submission.status == final_status
        assert archive is not None
        assert archive.object_name == submission.object_name
        return submission, archive


async def _count_user_personal_notifications(
    session_maker,
    *,
    user_id: int,
) -> int:
    async with session_maker() as session:
        return int(
            await session.scalar(
                select(func.count(PersonalNotification.id)).where(
                    PersonalNotification.user_id == user_id
                )
            )
            or 0
        )


async def _cleanup_course_lifecycle_context(
    session_maker,
    *,
    course_id: int,
    submission_id: int,
):
    async with session_maker() as session:
        archive_ids = list(
            (
                await session.execute(
                    select(Archive.id).where(Archive.course_id == course_id)
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id == submission_id,
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        if archive_ids:
            await session.execute(delete(Archive).where(Archive.id.in_(archive_ids)))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.commit()

        assert await session.get(ArchiveSubmission, submission_id) is None
        assert await session.get(Course, course_id) is None
        if archive_ids:
            assert (
                int(
                    await session.scalar(
                        select(func.count(Archive.id)).where(
                            Archive.id.in_(archive_ids)
                        )
                    )
                    or 0
                )
                == 0
            )


async def _assert_course_trash_restore_lifecycle(
    client: AsyncClient,
    session_maker,
    *,
    requester_id: int,
    admin_id: int,
    course: Course,
    archive: Archive,
    submission: ArchiveSubmission,
    expected_previous_status: SubmissionStatus,
):
    assert submission.status == expected_previous_status
    notification_baseline = await _count_user_personal_notifications(
        session_maker,
        user_id=requester_id,
    )
    previous_reviewed_at = submission.reviewed_at

    delete_response = await client.delete(
        f"/courses/admin/courses/{course.id}"
    )
    assert delete_response.status_code == 200
    assert "1 associated archives" in delete_response.json()["message"]

    async with session_maker() as session:
        trashed_course = await session.get(Course, course.id)
        trashed_archive = await session.get(Archive, archive.id)
        temporary_submission = await session.get(
            ArchiveSubmission, submission.id
        )
        assert trashed_course.deleted_at is not None
        assert trashed_course.deleted_by_id == admin_id
        assert trashed_course.restored_at is None
        assert trashed_archive.deleted_at is not None
        assert trashed_archive.deleted_by_id == admin_id
        assert trashed_archive.deleted_reason == "course deleted"
        assert temporary_submission.deleted_at is None
        assert temporary_submission.status == SubmissionStatus.TAKEDOWN
        assert is_course_trash_lifecycle_reason(
            temporary_submission.lifecycle_reason
        )
        assert (
            get_course_trash_previous_status(
                temporary_submission.lifecycle_reason
            )
            == expected_previous_status
        )
        assert f"course_id={course.id}" in temporary_submission.lifecycle_reason
        assert f"archive_id={archive.id}" in temporary_submission.lifecycle_reason
        assert temporary_submission.reviewer_id == admin_id
        assert temporary_submission.reviewed_at > previous_reviewed_at
        trashed_reviewed_at = temporary_submission.reviewed_at

    assert (
        await _count_user_personal_notifications(
            session_maker,
            user_id=requester_id,
        )
        == notification_baseline
    )

    restore_response = await client.post(
        "/trash/restore",
        json={"item_type": "course", "item_id": course.id},
    )
    assert restore_response.status_code == 200
    assert restore_response.json()["restoredArchivesCount"] == 1
    assert restore_response.json()["restoredSubmissionsCount"] == 1
    assert restore_response.json()["skippedSubmissionsCount"] == 0

    async with session_maker() as session:
        restored_course = await session.get(Course, course.id)
        restored_archive = await session.get(Archive, archive.id)
        restored_submission = await session.get(
            ArchiveSubmission, submission.id
        )
        assert restored_course.deleted_at is None
        assert restored_course.deleted_by_id is None
        assert restored_course.restored_at is not None
        assert restored_course.restored_by_id == admin_id
        assert restored_archive.deleted_at is None
        assert restored_archive.deleted_by_id is None
        assert restored_archive.deleted_reason is None
        assert restored_archive.restored_at is not None
        assert restored_archive.restored_by_id == admin_id
        assert restored_submission.deleted_at is None
        assert restored_submission.status == expected_previous_status
        assert restored_submission.lifecycle_reason is None
        assert restored_submission.reviewer_id == admin_id
        assert restored_submission.reviewed_at > trashed_reviewed_at

    assert (
        await _count_user_personal_notifications(
            session_maker,
            user_id=requester_id,
        )
        == notification_baseline
    )


def _override_user(user):
    async def _get_current_user():
        return UserRoles(user_id=user.id, is_admin=user.is_admin)

    return _get_current_user


@pytest.mark.asyncio
async def test_course_request_canonicalizes_legacy_category_alias(
    session_maker,
    make_user,
):
    user = await make_user()
    async with session_maker() as session:
        submission = await create_course_request(
            course_data=CourseSubmissionCreate(
                name=f"Legacy alias request {uuid.uuid4().hex[:8]}",
                category="freshman",
            ),
            current_user=UserRoles(user_id=user.id, is_admin=False),
            db=session,
        )
        assert submission.category == "fundamental"
        await session.execute(
            delete(CourseSubmission).where(CourseSubmission.id == submission.id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_categorized_courses_returns_courses(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    course = await _get_course_by_name(
        session_maker,
        category=CourseCategory.FRESHMAN,
        name="普通化學(一)",
    )
    assert course is not None

    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get("/courses")
        assert response.status_code == 200
        body = response.json()
        freshman_courses = body["freshman"]
        assert any(item["id"] == course.id for item in freshman_courses)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_course_archives_returns_active_archives(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    course = await _create_course(session_maker)
    active_archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )
    await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=user.id,
        deleted=True,
    )

    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get(f"/courses/{course.id}/archives")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == active_archive.id

        missing_response = await client.get("/courses/999999/archives")
        assert missing_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.course_id == course.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_get_course_archives_limits_submission_ids_to_owner_or_admin(
    client: AsyncClient,
    session_maker,
    make_user,
):
    owner = await make_user()
    other_user = await make_user()
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    owner_archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=owner.id, name="Owner archive"
    )
    other_archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=other_user.id, name="Other archive"
    )
    owner_submission = await _create_linked_submission(
        session_maker, archive=owner_archive, requester_id=owner.id
    )
    other_submission = await _create_linked_submission(
        session_maker, archive=other_archive, requester_id=other_user.id
    )

    async def fetch_as(user):
        app.dependency_overrides[get_current_user] = _override_user(user)
        response = await client.get(f"/courses/{course.id}/archives")
        assert response.status_code == 200
        return {item["id"]: item for item in response.json()}

    try:
        owner_rows = await fetch_as(owner)
        assert owner_rows[owner_archive.id]["source_submission_ids"] == [owner_submission.id]
        assert owner_rows[other_archive.id]["source_submission_ids"] == []

        other_rows = await fetch_as(other_user)
        assert other_rows[owner_archive.id]["source_submission_ids"] == []
        assert other_rows[other_archive.id]["source_submission_ids"] == [other_submission.id]

        admin_rows = await fetch_as(admin)
        assert admin_rows[owner_archive.id]["source_submission_ids"] == [owner_submission.id]
        assert admin_rows[other_archive.id]["source_submission_ids"] == [other_submission.id]

        app.dependency_overrides.pop(get_current_user, None)
        unauthenticated_response = await client.get(f"/courses/{course.id}/archives")
        assert unauthenticated_response.status_code in {401, 403}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id.in_([owner_submission.id, other_submission.id])
                )
            )
            await session.execute(delete(Archive).where(Archive.course_id == course.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.parametrize("endpoint", ["preview", "preview-file", "download"])
@pytest.mark.asyncio
async def test_archive_file_endpoints_require_authentication(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
    endpoint,
):
    uploader = await make_user()
    course = await _create_course(
        session_maker,
        name=f"Archive auth {uuid.uuid4().hex}",
    )
    archive = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=uploader.id,
    )
    storage_accessed = False

    def fail_if_storage_is_accessed():
        nonlocal storage_accessed
        storage_accessed = True
        raise AssertionError("anonymous request reached object storage")

    monkeypatch.setattr(
        "app.api.services.courses.get_minio_client",
        fail_if_storage_is_accessed,
    )
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/{endpoint}"
        )

        assert response.status_code in {401, 403}
        assert not storage_accessed
        assert "url" not in response.text
        assert not response.headers.get("content-type", "").startswith(
            "application/pdf"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_get_archive_preview_url_returns_presigned_link(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    preview_url = "https://preview.example.com/resource"

    def fake_presigned(obj_name, *, expires):
        assert obj_name == archive.object_name
        assert expires.total_seconds() == 1800
        return preview_url

    monkeypatch.setattr(
        "app.api.services.courses.presigned_get_url", fake_presigned
    )
    monkeypatch.setattr(
        "app.api.services.courses.get_minio_client",
        lambda: type("MinioStub", (), {"stat_object": lambda *_args: None})(),
    )
    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/preview"
        )
        assert response.status_code == 200
        assert response.json() == {"url": preview_url}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_archive_preview_and_download_return_structured_missing_file(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    def missing_object(*_args):
        raise S3Error(
            None,
            "NoSuchKey",
            "Object does not exist",
            archive.object_name,
            "request-id",
            "host-id",
        )

    monkeypatch.setattr(
        "app.api.services.courses.get_minio_client",
        lambda: type("MinioStub", (), {"stat_object": missing_object})(),
    )
    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        for endpoint in ("preview", "download"):
            response = await client.get(
                f"/courses/{course.id}/archives/{archive.id}/{endpoint}"
            )
            assert response.status_code == 404
            assert response.json()["detail"]["code"] == "archive_file_missing"

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.download_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_get_archive_download_url_increments_count(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    download_url = "https://download.example.com/file"

    def fake_presigned(obj_name, *, expires):
        assert obj_name == archive.object_name
        assert expires.total_seconds() == 3600
        return download_url

    monkeypatch.setattr(
        "app.api.services.courses.presigned_get_url", fake_presigned
    )
    monkeypatch.setattr(
        "app.api.services.courses.get_minio_client",
        lambda: type("MinioStub", (), {"stat_object": lambda *_args: None})(),
    )
    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/download"
        )
        assert response.status_code == 200
        assert response.json() == {"url": download_url}

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.download_count == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_archive_requires_admin(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.patch(
            f"/courses/{course.id}/archives/{archive.id}",
            data={"name": "New Name"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_update_archive_changes_fields(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=admin.id
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        response = await client.patch(
            f"/courses/{course.id}/archives/{archive.id}",
            data={
                "name": "Updated Archive",
                "professor": "Prof. New",
                "archive_type": ArchiveType.MIDTERM.value,
                "has_answers": "true",
                "academic_year": 2025,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Updated Archive"
        assert body["professor"] == "Prof. New"
        assert body["archive_type"] == ArchiveType.MIDTERM.value
        assert body["has_answers"] is True
        assert body["academic_year"] == 2025
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_course_crud_flow(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_user(admin)

    course_name = "測試課程"
    course_id = None

    try:
        response = await client.post(
            "/courses/admin/courses",
            json={
                "name": course_name,
                "category": CourseCategory.FRESHMAN.value,
            },
        )
        assert response.status_code == 200
        created = response.json()
        course_id = created["id"]

        response = await client.put(
            f"/courses/admin/courses/{course_id}",
            json={"name": "測試課程 (更新)"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["name"] == "測試課程 (更新)"

        response = await client.get("/courses/admin/courses")
        assert response.status_code == 200
        all_courses = response.json()
        assert any(course["id"] == course_id for course in all_courses)

        response = await client.get("/courses")
        assert response.status_code == 200
        freshman_courses = response.json()["freshman"]
        assert any(course["id"] == course_id for course in freshman_courses)

        response = await client.delete(f"/courses/admin/courses/{course_id}")
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]

        async with session_maker() as session:
            soft_deleted = await session.get(Course, course_id)
            assert soft_deleted.deleted_at is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if course_id is not None:
            async with session_maker() as session:
                await session.execute(
                    delete(Archive).where(Archive.course_id == course_id)
                )
                await session.execute(
                    delete(Course).where(Course.id == course_id)
                )
                await session.commit()


@pytest.mark.asyncio
async def test_admin_course_endpoints_require_admin(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    course = await _create_course(session_maker)
    app.dependency_overrides[get_current_user] = _override_user(user)

    try:
        response = await client.post(
            "/courses/admin/courses",
            json={
                "name": f"Forbidden {uuid.uuid4().hex[:4]}",
                "category": CourseCategory.FRESHMAN.value,
            },
        )
        assert response.status_code == 403

        response = await client.put(
            f"/courses/admin/courses/{course.id}",
            json={"name": "Should Not Update"},
        )
        assert response.status_code == 403

        response = await client.delete(f"/courses/admin/courses/{course.id}")
        assert response.status_code == 403

        response = await client.get("/courses/admin/courses")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_transfers_to_existing_course(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course_a = await _create_course(session_maker, name="Course A")
    course_b = await _create_course(session_maker, name="Course B")
    archive = await _create_archive(
        session_maker,
        course_id=course_a.id,
        uploader_id=admin.id,
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)

    try:
        response = await client.patch(
            f"/courses/{course_a.id}/archives/{archive.id}/course",
            json={"course_id": course_b.id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["new_course_id"] == course_b.id

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.course_id == course_b.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(
                    Course.id.in_([course_a.id, course_b.id])
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_creates_new_course_when_missing(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    original = await _create_course(session_maker, name="Original Course")
    archive = await _create_archive(
        session_maker,
        course_id=original.id,
        uploader_id=admin.id,
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)

    try:
        response = await client.patch(
            f"/courses/{original.id}/archives/{archive.id}/course",
            json={
                "course_name": "New Course",
                "course_category": CourseCategory.FRESHMAN.value,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["message"].startswith("Archive moved to course")

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.course_id != original.id
            new_course = await session.get(Course, body["new_course_id"])
            assert new_course.name == "New Course"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(
                    Course.name.in_(["Original Course", "New Course"])
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_rejects_same_course(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker, name="SameCourse")
    archive = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=admin.id,
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)

    try:
        response = await client.patch(
            f"/courses/{course.id}/archives/{archive.id}/course",
            json={"course_id": course.id},
        )
        assert response.status_code == 400
        assert "same course" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_delete_archive_admin_success(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=admin.id,
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)

    try:
        response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}"
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Archive deleted successfully"

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.deleted_at is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_get_categorized_courses_direct(session_maker, make_user):
    user = await make_user()
    course_freshman = await _get_course_by_name(
        session_maker,
        category=CourseCategory.FRESHMAN,
        name="普通化學(一)",
    )
    course_graduate = await _get_course_by_name(
        session_maker,
        category=CourseCategory.GRADUATE,
        name="電動力學(一)",
    )
    assert course_freshman is not None
    assert course_graduate is not None

    try:
        async with session_maker() as session:
            result = await get_categorized_courses(
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        payload = result.model_dump()
        assert any(
            item["id"] == course_freshman.id
            for item in payload["freshman"]
        )
        assert any(
            item["id"] == course_graduate.id
            for item in payload["graduate"]
        )
    finally:
        pass


@pytest.mark.asyncio
async def test_get_course_archives_direct_errors_when_course_missing(
    session_maker,
    make_user,
):
    user = await make_user()
    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await get_course_archives(
                course_id=999999,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_archive_preview_and_download_direct(
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    preview_url = "https://example.com/preview"
    download_url = "https://example.com/download"

    def fake_presigned(object_name: str, *, expires):
        if expires.total_seconds() == 1800:
            return preview_url
        return download_url

    monkeypatch.setattr(
        "app.api.services.courses.presigned_get_url",
        fake_presigned,
    )
    monkeypatch.setattr(
        "app.api.services.courses.get_minio_client",
        lambda: type("MinioStub", (), {"stat_object": lambda *_args: None})(),
    )

    try:
        async with session_maker() as session:
            preview = await get_archive_preview_url(
                course.id,
                archive.id,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
            download = await get_archive_download_url(
                course.id,
                archive.id,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
            assert preview == {"url": preview_url}
            assert download == {"url": download_url}

        async with session_maker() as session:
            refreshed = await session.get(Archive, archive.id)
            assert refreshed.download_count == 1
    finally:
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_get_archive_preview_url_not_found(
    client: AsyncClient,
    make_user,
):
    user = await make_user()

    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get("/courses/999/archives/1/preview")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_archive_download_url_not_found(
    client: AsyncClient,
    make_user,
):
    user = await make_user()

    app.dependency_overrides[get_current_user] = _override_user(user)
    try:
        response = await client.get("/courses/123/archives/456/download")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_update_archive_direct_sets_fields(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=admin.id
    )

    try:
        async with session_maker() as session:
            updated = await update_archive(
                course_id=course.id,
                archive_id=archive.id,
                name="Flashcards",
                professor="Prof. Direct",
                archive_type=ArchiveType.QUIZ,
                has_answers=True,
                academic_year=2026,
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
            assert updated.name == "Flashcards"
            assert updated.professor == "Prof. Direct"
            assert updated.archive_type == ArchiveType.QUIZ
            assert updated.has_answers is True
            assert updated.academic_year == 2026
    finally:
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_archive_direct_404_when_missing(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive(
                course_id=course.id,
                archive_id=9999,
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 404

    async with session_maker() as session:
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_requires_admin(session_maker, make_user):
    user = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=user.id
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive_course(
                course_id=course.id,
                archive_id=archive.id,
                course_update=ArchiveUpdateCourse(course_id=course.id + 1),
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 403

    async with session_maker() as session:
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_missing_payload_raises(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=admin.id
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive_course(
                course_id=course.id,
                archive_id=archive.id,
                course_update=ArchiveUpdateCourse(),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 400

    async with session_maker() as session:
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_target_course_missing(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=admin.id
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive_course(
                course_id=course.id,
                archive_id=archive.id,
                course_update=ArchiveUpdateCourse(course_id=999999),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 404

    async with session_maker() as session:
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_same_course_by_name_rejected(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker, name="OverlapCourse")
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=admin.id
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive_course(
                course_id=course.id,
                archive_id=archive.id,
                course_update=ArchiveUpdateCourse(
                    course_name=course.name,
                    course_category=course.category,
                ),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 400

    async with session_maker() as session:
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_update_archive_course_archive_missing(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_archive_course(
                course_id=course.id,
                archive_id=123456,
                course_update=ArchiveUpdateCourse(course_id=course.id),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 404

    async with session_maker() as session:
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_delete_archive_direct_forbidden_for_non_owner(
    session_maker,
    make_user,
):
    owner = await make_user()
    other = await make_user()
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker, course_id=course.id, uploader_id=owner.id
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await delete_archive(
                course_id=course.id,
                archive_id=archive.id,
                current_user=UserRoles(user_id=other.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 403

    async with session_maker() as session:
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_create_course_duplicate_rejected(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(
        session_maker,
        name="Duplicate Course",
        category=CourseCategory.FRESHMAN,
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await create_course(
                course_data=CourseCreate(
                    name="Duplicate Course",
                    category=CourseCategory.FRESHMAN,
                ),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 400

    async with session_maker() as session:
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_category_create_rejects_legacy_key_and_duplicate_normalized_name(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    current_user = UserRoles(user_id=admin.id, is_admin=True)

    async with session_maker() as session:
        with pytest.raises(HTTPException) as legacy_error:
            await create_course_category(
                category_data=CourseCategoryCreate(
                    key="freshman",
                    name="Legacy category",
                ),
                current_user=current_user,
                db=session,
            )
        assert legacy_error.value.status_code == 400
        assert "Legacy" in legacy_error.value.detail

        with pytest.raises(HTTPException) as name_error:
            await create_course_category(
                category_data=CourseCategoryCreate(
                    key="duplicate-fundamental",
                    name=" 基礎必修 ",
                ),
                current_user=current_user,
                db=session,
            )
        assert name_error.value.status_code == 400
        assert "name already exists" in name_error.value.detail


@pytest.mark.asyncio
async def test_update_course_duplicate_name_rejected(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    original = await _create_course(session_maker, name="Original-Name")
    other = await _create_course(session_maker, name="Existing-Name")

    try:
        async with session_maker() as session:
            with pytest.raises(HTTPException) as exc:
                await update_course(
                    course_id=original.id,
                    course_data=CourseUpdate(name="Existing-Name"),
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            assert exc.value.status_code == 400
    finally:
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.id.in_([original.id, other.id]))
            )
            await session.commit()


@pytest.mark.asyncio
async def test_update_course_not_found_direct(session_maker, make_user):
    admin = await make_user(is_admin=True)

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await update_course(
                course_id=424242,
                course_data=CourseUpdate(name="Missing"),
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_course_not_found_direct(session_maker, make_user):
    admin = await make_user(is_admin=True)

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await delete_course(
                course_id=123123,
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_course_trash_restore_preserves_approved_submission_without_notification(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, pending_submission = await _create_pending_course_lifecycle_context(
        session_maker,
        requester_id=requester.id,
        label="approved",
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        submission, archive = await _review_course_lifecycle_context(
            client,
            session_maker,
            submission_id=pending_submission.id,
            final_status=SubmissionStatus.APPROVED,
        )
        await _assert_course_trash_restore_lifecycle(
            client,
            session_maker,
            requester_id=requester.id,
            admin_id=admin.id,
            course=course,
            archive=archive,
            submission=submission,
            expected_previous_status=SubmissionStatus.APPROVED,
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_course_lifecycle_context(
            session_maker,
            course_id=course.id,
            submission_id=pending_submission.id,
        )


@pytest.mark.asyncio
async def test_course_trash_restore_preserves_rejected_submission_without_notification(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, pending_submission = await _create_pending_course_lifecycle_context(
        session_maker,
        requester_id=requester.id,
        label="rejected",
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        submission, archive = await _review_course_lifecycle_context(
            client,
            session_maker,
            submission_id=pending_submission.id,
            final_status=SubmissionStatus.REJECTED,
        )
        await _assert_course_trash_restore_lifecycle(
            client,
            session_maker,
            requester_id=requester.id,
            admin_id=admin.id,
            course=course,
            archive=archive,
            submission=submission,
            expected_previous_status=SubmissionStatus.REJECTED,
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_course_lifecycle_context(
            session_maker,
            course_id=course.id,
            submission_id=pending_submission.id,
        )


@pytest.mark.asyncio
async def test_admin_delete_course_soft_deletes_archives(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _create_course(session_maker)
    archive = await _create_archive(
        session_maker,
        course_id=course.id,
        uploader_id=admin.id,
    )

    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        response = await client.delete(
            f"/courses/admin/courses/{course.id}"
        )
        assert response.status_code == 200
        body = response.json()
        assert "1 associated archives" in body["message"]

        async with session_maker() as session:
            refreshed_course = await session.get(Course, course.id)
            refreshed_archive = await session.get(Archive, archive.id)
            assert refreshed_course.deleted_at is not None
            assert refreshed_archive.deleted_at is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.id == archive.id)
            )
            await session.execute(
                delete(Course).where(Course.id == course.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_list_all_courses_direct_returns_courses(
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    course = await _get_course_by_name(
        session_maker,
        name="普通化學(一)",
        category=CourseCategory.FRESHMAN,
    )
    assert course is not None

    try:
        async with session_maker() as session:
            courses = await list_all_courses(
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
            assert any(item.id == course.id for item in courses)
    finally:
        pass
