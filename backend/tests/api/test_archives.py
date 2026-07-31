import io
import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select, func
from starlette.datastructures import UploadFile

from app.api.services.archives import upload_archive
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    CourseCategoryConfig,
    PersonalNotification,
    SubmissionStatus,
    User,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


async def _create_pending_review_context(
    session_maker,
    *,
    requester_id: int,
):
    unique = uuid.uuid4().hex
    async with session_maker() as session:
        course = Course(
            name=f"Lifecycle Course {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"Lifecycle Exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Lifecycle Professor",
            object_name=f"submissions/lifecycle-{unique}.pdf",
            requester_id=requester_id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)
    return course, submission


async def _cleanup_review_context(
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
            remaining_archives = int(
                await session.scalar(
                    select(func.count(Archive.id)).where(Archive.id.in_(archive_ids))
                )
                or 0
            )
            assert remaining_archives == 0


@pytest.mark.parametrize(
    ("action", "target_status", "notification_type"),
    [
        ("reject", SubmissionStatus.REJECTED, "archive_submission_rejected"),
        ("takedown", SubmissionStatus.TAKEDOWN, "archive_submission_takedown"),
    ],
    ids=["rejected", "takedown"],
)
@pytest.mark.asyncio
async def test_approved_submission_can_be_rejected_or_taken_down(
    client: AsyncClient,
    session_maker,
    make_user,
    action,
    target_status,
    notification_type,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        approved_response = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={"note": "initial approval"},
        )
        assert approved_response.status_code == 200
        assert approved_response.json()["status"] == SubmissionStatus.APPROVED.value

        async with session_maker() as session:
            approved = await session.get(ArchiveSubmission, submission.id)
            archive = await session.get(Archive, approved.created_archive_id)
            assert archive is not None
            approved_reviewed_at = approved.reviewed_at
            archive_id = archive.id
            archive_object_name = archive.object_name
            notification_baseline = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == requester.id,
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission.id,
                    )
                )
                or 0
            )

        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={"note": f"move to {target_status.value}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == target_status.value

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            paired_archive = await session.get(Archive, archive_id)
            assert stored.status == target_status
            assert stored.reviewer_id == admin.id
            assert stored.reviewed_at is not None
            assert stored.reviewed_at > approved_reviewed_at
            assert stored.review_note == f"move to {target_status.value}"
            assert stored.lifecycle_reason is None
            assert stored.created_archive_id == archive_id
            assert paired_archive is not None
            assert paired_archive.deleted_at is None
            assert paired_archive.object_name == archive_object_name

            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification)
                        .where(
                            PersonalNotification.user_id == requester.id,
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission.id,
                        )
                        .order_by(PersonalNotification.created_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == notification_baseline + 1
            assert {item.notification_type for item in notifications} == {
                "archive_submission_approved",
                notification_type,
            }
            target_notifications = [
                item
                for item in notifications
                if item.notification_type == notification_type
            ]
            assert len(target_notifications) == 1
            notification = target_notifications[0]
            assert notification.user_id == requester.id
            assert notification.source_type == "archive_submission"
            assert notification.source_id == submission.id
            assert notification.metadata_json["status"] == target_status.value
            assert notification.metadata_json["archive_id"] == archive_id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_rejected_submission_can_be_approved(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        rejected_response = await client.post(
            f"/archives/admin/submissions/{submission.id}/reject",
            json={"note": "initial rejection"},
        )
        assert rejected_response.status_code == 200
        assert rejected_response.json()["status"] == SubmissionStatus.REJECTED.value

        async with session_maker() as session:
            rejected = await session.get(ArchiveSubmission, submission.id)
            assert rejected.created_archive_id is None
            rejected_reviewed_at = rejected.reviewed_at
            notification_baseline = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == requester.id,
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission.id,
                    )
                )
                or 0
            )

        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={"note": "approved after rejection"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == SubmissionStatus.APPROVED.value

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.reviewer_id == admin.id
            assert stored.reviewed_at is not None
            assert stored.reviewed_at > rejected_reviewed_at
            assert stored.review_note == "approved after rejection"
            assert stored.created_archive_id is not None
            assert stored.lifecycle_reason is None

            archive = await session.get(Archive, stored.created_archive_id)
            assert archive is not None
            assert archive.deleted_at is None
            assert archive.object_name == submission.object_name
            archive_count = int(
                await session.scalar(
                    select(func.count(Archive.id)).where(
                        Archive.object_name == submission.object_name
                    )
                )
                or 0
            )
            assert archive_count == 1

            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == requester.id,
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == notification_baseline + 1
            approved_notifications = [
                item
                for item in notifications
                if item.notification_type == "archive_submission_approved"
            ]
            assert len(approved_notifications) == 1
            notification = approved_notifications[0]
            assert notification.user_id == requester.id
            assert notification.source_type == "archive_submission"
            assert notification.source_id == submission.id
            assert notification.metadata_json["status"] == "approved"
            assert notification.metadata_json["archive_id"] == archive.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_archive_review_statuses_create_deduplicated_notifications(
    client: AsyncClient, session_maker, make_user
):
    requester = await make_user(name="review-notification-requester")
    admin = await make_user(name="review-notification-admin", is_admin=True)
    category_key = f"review-{uuid.uuid4().hex[:8]}"
    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=category_key,
            name="Review notification category",
            label="Review notification category",
            icon="pi pi-book",
            is_active=True,
            order_index=999,
        )
        course = Course(name="Review Notification Course", category=category_key)
        session.add_all([category, course])
        await session.commit()
        await session.refresh(course)
        submissions = []
        for index in range(3):
            submission = ArchiveSubmission(
                subject=course.name,
                category=category_key,
                name=f"Review Exam {index}",
                academic_year=2024,
                archive_type=ArchiveType.FINAL,
                professor="Prof",
                object_name=f"review-{index}.pdf",
                requester_id=requester.id,
                status=SubmissionStatus.PENDING,
            )
            session.add(submission)
            submissions.append(submission)
        await session.commit()
        for submission in submissions:
            await session.refresh(submission)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        responses = [
            await client.post(f"/archives/admin/submissions/{submissions[0].id}/approve"),
            await client.post(f"/archives/admin/submissions/{submissions[1].id}/reject"),
            await client.post(f"/archives/admin/submissions/{submissions[2].id}/takedown"),
        ]
        assert [response.status_code for response in responses] == [200, 200, 200]

        async with session_maker() as session:
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == requester.id,
                            PersonalNotification.source_type == "archive_submission",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {item.notification_type for item in notifications} == {
                "archive_submission_approved",
                "archive_submission_rejected",
                "archive_submission_takedown",
            }
            assert len({item.dedupe_key for item in notifications}) == 3
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.user_id == requester.id
                )
            )
            created_ids = [submission.id for submission in submissions]
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id.in_(created_ids))
            )
            await session.execute(
                delete(Archive).where(Archive.uploader_id == requester.id)
            )
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.execute(
                delete(CourseCategoryConfig).where(CourseCategoryConfig.key == category_key)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_creates_course_and_archive(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    unique = uuid.uuid4().hex[:8]
    user = await make_user()
    user_id = user.id

    async def fake_get_current_user():
        return UserRoles(user_id=user_id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user

    fake_pdf = io.BytesIO(b"%PDF-1.4 test content")
    unique_course = f"Test Course {unique}"

    class FakeMinio:
        def put_object(self, **kwargs):
            return None

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FakeMinio(),
    )

    try:
        response = await client.post(
            "/archives/upload",
            files={"file": ("sample.pdf", fake_pdf, "application/pdf")},
            data={
                "subject": unique_course,
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Test",
                "archive_type": "final",
                "has_answers": "true",
                "filename": f"Final Exam {unique}",
                "academic_year": 2024,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        submission_data = body["submission"]
        assert submission_data["name"] == f"Final Exam {unique}"
        assert submission_data["professor"] == "Prof. Test"
        assert submission_data["status"] == SubmissionStatus.PENDING.value

        async with session_maker() as session:
            result = await session.execute(
                select(Course).where(Course.name == unique_course)
            )
            course = result.scalar_one_or_none()
            assert course is None

            result = await session.execute(
                select(ArchiveSubmission).where(ArchiveSubmission.id == submission_data["id"])
            )
            submission = result.scalar_one_or_none()
            assert submission is not None
            assert submission.subject == unique_course
            assert submission.requester_id == user_id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.requester_id == user_id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_returns_404_when_user_missing(
    client: AsyncClient,
    make_user,
    session_maker,
):
    user = await make_user()
    async with session_maker() as session:
        db_user = await session.get(User, user.id)
        await session.delete(db_user)
        await session.commit()

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "sample.pdf",
                    io.BytesIO(b"%PDF-1.4"),
                    "application/pdf",
                )
            },
            data={
                "subject": "Missing User Course",
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Missing",
                "archive_type": "midterm",
                "has_answers": "false",
                "filename": "Should Fail",
                "academic_year": 2024,
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_archive_reuses_existing_course(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    subject = "Existing Course"

    async with session_maker() as session:
        course = Course(name=subject, category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)

    class FakeMinio:
        def put_object(self, **kwargs):
            return None

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FakeMinio(),
    )

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "sample.pdf",
                    io.BytesIO(b"%PDF-1.4 reuse"),
                    "application/pdf",
                )
            },
            data={
                "subject": subject,
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Existing",
                "archive_type": "quiz",
                "has_answers": "false",
                "filename": "Reuse Archive",
                "academic_year": 2023,
            },
        )
        assert response.status_code == 200

        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.requester_id == user.id)
            )
            count = await session.execute(
                select(func.count()).where(Course.name == subject)
            )
            assert count.scalar() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.requester_id == user.id)
            )
            await session.execute(
                delete(Archive).where(Archive.uploader_id == user.id)
            )
            await session.execute(delete(Course).where(Course.name == subject))
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_rejects_large_file(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user

    class FakeMinio:
        def put_object(self, **kwargs):
            raise AssertionError("should not upload oversized file")

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FakeMinio(),
    )

    try:
        big_content = b"x" * (10 * 1024 * 1024 + 1)
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "huge.pdf",
                    io.BytesIO(big_content),
                    "application/pdf",
                )
            },
            data={
                "subject": "Oversized Course",
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Big",
                "archive_type": "midterm",
                "has_answers": "true",
                "filename": "Too Large",
                "academic_year": 2024,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "File size exceeds 10MB limit"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.name == "Oversized Course")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_handles_storage_failure(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user

    class FailingMinio:
        def put_object(self, **kwargs):
            raise RuntimeError("minio unavailable")

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FailingMinio(),
    )

    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "sample.pdf",
                    io.BytesIO(b"%PDF-1.4 fake"),
                    "application/pdf",
                )
            },
            data={
                "subject": "Fail Course",
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Fail",
                "archive_type": "final",
                "has_answers": "false",
                "filename": "Failure",
                "academic_year": 2024,
            },
        )
        assert response.status_code == 500
        assert "Failed to upload file" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.name == "Fail Course")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_function_covers_creation_and_reuse(
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    uploads = []
    first_id = None
    second_id = None
    course_id = None

    class RecordingMinio:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: RecordingMinio(),
    )

    async with session_maker() as session:
        uploader = UserRoles(user_id=user.id, is_admin=True)

        async def _call(subject, filename):
            upload = UploadFile(
                filename=filename,
                file=io.BytesIO(b"%PDF-1.4 direct test"),
            )
            uploads.append(upload)
            return await upload_archive(
                file=upload,
                subject=subject,
                category=CourseCategory.FRESHMAN,
                professor="Prof. Direct",
                archive_type="final",
                has_answers=True,
                filename=filename,
                academic_year=2024,
                current_user=uploader,
                db=session,
            )

        first = await _call("Direct Subject", "Direct Archive.pdf")
        second = await _call("Direct Subject", "Second Archive.pdf")

        assert first["success"] is True
        assert second["success"] is True
        assert first["archive"]["name"] == "Direct Archive.pdf"
        assert second["archive"]["name"] == "Second Archive.pdf"

        # Ensure both archives share the same course
        first_id = first["archive"]["id"]
        second_id = second["archive"]["id"]
        first_archive = await session.get(Archive, first_id)
        second_archive = await session.get(Archive, second_id)
        assert first_archive.course_id == second_archive.course_id
        course_id = first_archive.course_id

    if first_id and second_id and course_id:
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.created_archive_id.in_([first_id, second_id])
                )
            )
            await session.execute(
                delete(Archive).where(
                    Archive.id.in_([first_id, second_id])
                )
            )
            await session.execute(
                delete(Course).where(Course.id == course_id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_upload_persists_requested_category_caller_transaction(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    unique = uuid.uuid4().hex
    category_key = f"admin-upload-{unique[:12]}"
    category_name = f"Admin upload category {unique}"
    course_name = f"Admin Upload Course {unique}"
    archive_name = f"Admin Upload Exam {unique}"
    admin = await make_user(is_admin=True)

    class FakeMinio:
        def put_object(self, **kwargs):
            return None

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FakeMinio(),
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "admin-upload.pdf",
                    io.BytesIO(b"%PDF-1.4 admin upload"),
                    "application/pdf",
                )
            },
            data={
                "subject": course_name,
                "category": category_key,
                "professor": "Admin Upload Professor",
                "archive_type": "final",
                "has_answers": "false",
                "filename": archive_name,
                "academic_year": 2026,
                "request_new_course": "true",
                "request_new_category": "true",
                "requested_course_name": course_name,
                "requested_category_key": category_key,
                "requested_category_name": category_name,
                "requested_category_label": category_name,
                "requested_category_icon": "pi pi-book",
            },
        )
        assert response.status_code == 200

        async with session_maker() as session:
            category = (
                await session.execute(
                    select(CourseCategoryConfig).where(
                        CourseCategoryConfig.key == category_key
                    )
                )
            ).scalar_one()
            course = (
                await session.execute(
                    select(Course).where(
                        Course.category == category_key,
                        Course.name == course_name,
                    )
                )
            ).scalar_one()
            archive = (
                await session.execute(
                    select(Archive).where(
                        Archive.uploader_id == admin.id,
                        Archive.name == archive_name,
                    )
                )
            ).scalar_one()
            submission = (
                await session.execute(
                    select(ArchiveSubmission).where(
                        ArchiveSubmission.requester_id == admin.id,
                        ArchiveSubmission.name == archive_name,
                    )
                )
            ).scalar_one()

            assert category.is_active is True
            assert course.category == category.key
            assert archive.course_id == course.id
            assert submission.created_archive_id == archive.id
            assert submission.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == admin.id,
                    ArchiveSubmission.name == archive_name,
                )
            )
            await session.execute(
                delete(Archive).where(
                    Archive.uploader_id == admin.id,
                    Archive.name == archive_name,
                )
            )
            await session.execute(
                delete(Course).where(
                    Course.category == category_key,
                    Course.name == course_name,
                )
            )
            await session.execute(
                delete(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == category_key
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_edit_persists_requested_category_caller_transaction(
    client: AsyncClient,
    session_maker,
    make_user,
):
    unique = uuid.uuid4().hex
    original_course_name = f"Admin Edit Original Course {unique}"
    new_category_key = f"admin-edit-{unique[:12]}"
    new_category_name = f"Admin edit category {unique}"
    new_course_name = f"Admin Edit New Course {unique}"
    object_name = f"archive-submissions/admin-edit-{unique}.pdf"
    requester = await make_user()
    admin = await make_user(is_admin=True)

    async with session_maker() as session:
        original_course = Course(
            name=original_course_name,
            category=CourseCategory.FRESHMAN.value,
        )
        session.add(original_course)
        await session.flush()
        archive = Archive(
            course_id=original_course.id,
            name=f"Admin Edit Exam {unique}",
            academic_year=2025,
            archive_type=ArchiveType.MIDTERM,
            professor="Original Professor",
            object_name=object_name,
            uploader_id=requester.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=original_course_name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=object_name,
            requester_id=requester.id,
            created_archive_id=archive.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(original_course)
        await session.refresh(archive)
        await session.refresh(submission)
        original_course_id = original_course.id
        archive_id = archive.id
        submission_id = submission.id

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.put(
            f"/archives/admin/submissions/{submission_id}",
            json={
                "subject": new_course_name,
                "category": new_category_key,
                "requested_course_name": new_course_name,
                "requested_category_key": new_category_key,
                "requested_category_name": new_category_name,
                "requested_category_label": new_category_name,
                "requested_category_icon": "pi pi-folder",
            },
        )
        assert response.status_code == 200

        async with session_maker() as session:
            category = (
                await session.execute(
                    select(CourseCategoryConfig).where(
                        CourseCategoryConfig.key == new_category_key
                    )
                )
            ).scalar_one()
            course = (
                await session.execute(
                    select(Course).where(
                        Course.category == new_category_key,
                        Course.name == new_course_name,
                    )
                )
            ).scalar_one()
            stored_archive = await session.get(Archive, archive_id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )

            assert category.is_active is True
            assert course.category == category.key
            assert stored_archive.course_id == course.id
            assert stored_submission.subject == new_course_name
            assert stored_submission.category == new_category_key
            assert stored_submission.requested_category_key == new_category_key
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
            )
            await session.execute(delete(Archive).where(Archive.id == archive_id))
            await session.execute(
                delete(Course).where(
                    Course.category == new_category_key,
                    Course.name == new_course_name,
                )
            )
            await session.execute(delete(Course).where(Course.id == original_course_id))
            await session.execute(
                delete(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == new_category_key
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_requires_pdf(
    client: AsyncClient,
    make_user,
):
    user = await make_user()

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        response = await client.post(
            "/archives/upload",
            files={"file": ("sample.txt", io.BytesIO(b"text"), "text/plain")},
            data={
                "subject": "Non PDF Course",
                "category": CourseCategory.FRESHMAN.value,
                "professor": "Prof. Fake",
                "archive_type": "midterm",
                "has_answers": "false",
                "filename": "Not PDF",
                "academic_year": 2024,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Only PDF files are allowed"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_archive_function_user_missing(
    session_maker,
    make_user,
):
    user = await make_user()
    async with session_maker() as session:
        db_user = await session.get(User, user.id)
        await session.delete(db_user)
        await session.commit()

    upload = UploadFile(
        filename="missing.pdf",
        file=io.BytesIO(b"%PDF missing user"),
    )

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await upload_archive(
                file=upload,
                subject="Missing Subject",
                category=CourseCategory.FRESHMAN,
                professor="Prof. Missing",
                archive_type="midterm",
                has_answers=False,
                filename="Missing Archive",
                academic_year=2024,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_upload_archive_function_rejects_non_pdf(
    session_maker,
    make_user,
):
    user = await make_user()
    upload = UploadFile(filename="invalid.txt", file=io.BytesIO(b"text"))

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await upload_archive(
                file=upload,
                subject="Bad File",
                category=CourseCategory.FRESHMAN,
                professor="Prof. Text",
                archive_type="midterm",
                has_answers=False,
                filename="Bad File",
                academic_year=2024,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_archive_function_handles_storage_error(
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()

    class FailingMinio:
        def put_object(self, **kwargs):
            raise RuntimeError("storage down")

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FailingMinio(),
    )

    upload = UploadFile(filename="fail.pdf", file=io.BytesIO(b"%PDF fail"))

    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await upload_archive(
                file=upload,
                subject="Failure",
                category=CourseCategory.FRESHMAN,
                professor="Prof. Fail",
                archive_type="final",
                has_answers=False,
                filename="Failure",
                academic_year=2024,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 500
