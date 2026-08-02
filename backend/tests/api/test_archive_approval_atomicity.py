from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import delete, func, select

from app.api.services import archives as archives_service
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategoryConfig,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


def _column_snapshot(instance) -> dict:
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
    }


async def _cleanup_approval_context(
    session_maker,
    *,
    submission_id: int,
    category_key: str,
    course_name: str,
    object_names: list[str],
) -> None:
    async with session_maker() as session:
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id == submission_id,
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        await session.execute(
            delete(Archive).where(Archive.object_name.in_(object_names))
        )
        await session.execute(
            delete(Course).where(
                Course.category == category_key,
                Course.name == course_name,
            )
        )
        await session.execute(
            delete(CourseCategoryConfig).where(CourseCategoryConfig.key == category_key)
        )
        await session.commit()


def _install_notification_failure(
    monkeypatch,
    *,
    category_key: str,
    course_name: str,
    expected_archive_id: int | None = None,
) -> None:
    original_enqueue = archives_service.enqueue_submission_status_notification

    async def enqueue_then_fail(db, submission, new_status):
        await original_enqueue(db, submission, new_status)
        await db.flush()

        assert new_status == SubmissionStatus.APPROVED
        assert submission.status == SubmissionStatus.APPROVED
        assert submission.reviewer_id is not None
        assert submission.reviewed_at is not None

        category = (
            await db.execute(
                select(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == category_key
                )
            )
        ).scalar_one()
        course = (
            await db.execute(
                select(Course).where(
                    Course.category == category_key,
                    Course.name == course_name,
                )
            )
        ).scalar_one()
        archive = await db.get(Archive, submission.created_archive_id)

        assert category is not None
        assert course is not None
        assert archive is not None
        assert archive.course_id == course.id
        if expected_archive_id is not None:
            assert archive.id == expected_archive_id
        assert (
            int(
                await db.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission.id,
                        PersonalNotification.notification_type
                        == "archive_submission_approved",
                    )
                )
                or 0
            )
            == 1
        )

        raise RuntimeError("approval notification failed")

    monkeypatch.setattr(
        archives_service,
        "enqueue_submission_status_notification",
        enqueue_then_fail,
    )


@pytest.mark.asyncio
async def test_approve_rolls_back_new_category_course_archive_on_notification_failure(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    unique = uuid.uuid4().hex
    category_key = f"atomic-{unique[:12]}"
    category_name = f"Atomic category {unique}"
    course_name = f"Atomic Course {unique}"
    object_name = f"archive-submissions/atomic-{unique}.pdf"
    requester = await make_user(name=f"atomic-requester-{unique[:8]}")
    admin = await make_user(name=f"atomic-admin-{unique[:8]}", is_admin=True)

    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=course_name,
            category=category_key,
            name=f"Atomic Exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Atomic Professor",
            object_name=object_name,
            requested_course_name=course_name,
            requested_category_key=category_key,
            requested_category_name=category_name,
            requested_category_label=category_name,
            requested_category_icon="pi pi-book",
            requester_id=requester.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        submission_id = submission.id
        submission_snapshot = _column_snapshot(submission)

    _install_notification_failure(
        monkeypatch,
        category_key=category_key,
        course_name=course_name,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with pytest.raises(RuntimeError, match="approval notification failed"):
            await client.post(
                f"/archives/admin/submissions/{submission_id}/approve",
                json={
                    "note": "must roll back",
                    "expected_status": "pending",
                },
            )

        async with session_maker() as session:
            stored_submission = await session.get(ArchiveSubmission, submission_id)
            counts = {
                "category": int(
                    await session.scalar(
                        select(func.count(CourseCategoryConfig.id)).where(
                            CourseCategoryConfig.key == category_key
                        )
                    )
                    or 0
                ),
                "course": int(
                    await session.scalar(
                        select(func.count(Course.id)).where(
                            Course.category == category_key,
                            Course.name == course_name,
                        )
                    )
                    or 0
                ),
                "archive": int(
                    await session.scalar(
                        select(func.count(Archive.id)).where(
                            Archive.object_name == object_name
                        )
                    )
                    or 0
                ),
                "notification": int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission_id,
                        )
                    )
                    or 0
                ),
            }

            assert stored_submission is not None
            assert _column_snapshot(stored_submission) == submission_snapshot
            assert counts == {
                "category": 0,
                "course": 0,
                "archive": 0,
                "notification": 0,
            }
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_approval_context(
            session_maker,
            submission_id=submission_id,
            category_key=category_key,
            course_name=course_name,
            object_names=[object_name],
        )


@pytest.mark.asyncio
async def test_rejected_reapproval_rolls_back_on_notification_failure(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    unique = uuid.uuid4().hex
    category_key = f"reapprove-{unique[:10]}"
    category_name = f"Reapproval category {unique}"
    course_name = f"Reapproval Course {unique}"
    object_name = f"archive-submissions/reapproval-{unique}.pdf"
    requester = await make_user(name=f"reapproval-requester-{unique[:8]}")
    admin = await make_user(name=f"reapproval-admin-{unique[:8]}", is_admin=True)
    previous_reviewed_at = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)

    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=category_key,
            name=category_name,
            label=category_name,
            icon="pi pi-book",
            order_index=731,
            is_active=True,
        )
        course = Course(
            name=course_name,
            category=category_key,
            order_index=17,
        )
        session.add_all([category, course])
        await session.flush()
        submission = ArchiveSubmission(
            subject=course_name,
            category=category_key,
            name=f"Reapproval Exam {unique}",
            academic_year=2025,
            archive_type=ArchiveType.MIDTERM,
            professor="Reapproval Professor",
            object_name=object_name,
            requested_course_name=course_name,
            requester_id=requester.id,
            status=SubmissionStatus.REJECTED,
            reviewer_id=admin.id,
            review_note="original rejection",
            reviewed_at=previous_reviewed_at,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(category)
        await session.refresh(course)
        await session.refresh(submission)
        submission_id = submission.id
        category_snapshot = _column_snapshot(category)
        course_snapshot = _column_snapshot(course)
        submission_snapshot = _column_snapshot(submission)

    _install_notification_failure(
        monkeypatch,
        category_key=category_key,
        course_name=course_name,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with pytest.raises(RuntimeError, match="approval notification failed"):
            await client.post(
                f"/archives/admin/submissions/{submission_id}/approve",
                json={
                    "note": "replacement approval",
                    "expected_status": "rejected",
                },
            )

        async with session_maker() as session:
            stored_category = (
                await session.execute(
                    select(CourseCategoryConfig).where(
                        CourseCategoryConfig.key == category_key
                    )
                )
            ).scalar_one()
            stored_course = (
                await session.execute(
                    select(Course).where(
                        Course.category == category_key,
                        Course.name == course_name,
                    )
                )
            ).scalar_one()
            stored_submission = await session.get(ArchiveSubmission, submission_id)
            archive_count = int(
                await session.scalar(
                    select(func.count(Archive.id)).where(
                        Archive.object_name == object_name
                    )
                )
                or 0
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission_id,
                    )
                )
                or 0
            )

            assert _column_snapshot(stored_category) == category_snapshot
            assert _column_snapshot(stored_course) == course_snapshot
            assert _column_snapshot(stored_submission) == submission_snapshot
            assert archive_count == 0
            assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_approval_context(
            session_maker,
            submission_id=submission_id,
            category_key=category_key,
            course_name=course_name,
            object_names=[object_name],
        )


@pytest.mark.asyncio
async def test_approve_rolls_back_existing_archive_update_on_notification_failure(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    unique = uuid.uuid4().hex
    category_key = f"reuse-{unique[:12]}"
    category_name = f"Reuse category {unique}"
    course_name = f"Reuse Course {unique}"
    old_object_name = f"archives/reuse-old-{unique}.pdf"
    new_object_name = f"archive-submissions/reuse-new-{unique}.pdf"
    requester = await make_user(name=f"reuse-requester-{unique[:8]}")
    admin = await make_user(name=f"reuse-admin-{unique[:8]}", is_admin=True)
    previous_reviewed_at = datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc)
    previous_archive_updated_at = datetime(2025, 12, 1, tzinfo=timezone.utc)
    previous_archive_deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=category_key,
            name=category_name,
            label=category_name,
            icon="pi pi-folder",
            order_index=732,
            is_active=True,
        )
        course = Course(
            name=course_name,
            category=category_key,
            order_index=18,
        )
        session.add_all([category, course])
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"Old Archive {unique}",
            academic_year=2020,
            archive_type=ArchiveType.QUIZ,
            professor="Old Professor",
            has_answers=True,
            object_name=old_object_name,
            uploader_id=admin.id,
            updated_at=previous_archive_updated_at,
            deleted_at=previous_archive_deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course_name,
            category=category_key,
            name=f"New Archive {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="New Professor",
            has_answers=False,
            object_name=new_object_name,
            requested_course_name=course_name,
            requester_id=requester.id,
            status=SubmissionStatus.REJECTED,
            reviewer_id=admin.id,
            review_note="keep this review",
            reviewed_at=previous_reviewed_at,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(archive)
        await session.refresh(submission)
        archive_id = archive.id
        submission_id = submission.id
        archive_snapshot = _column_snapshot(archive)
        submission_snapshot = _column_snapshot(submission)

    _install_notification_failure(
        monkeypatch,
        category_key=category_key,
        course_name=course_name,
        expected_archive_id=archive_id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with pytest.raises(RuntimeError, match="approval notification failed"):
            await client.post(
                f"/archives/admin/submissions/{submission_id}/approve",
                json={
                    "note": "must not replace review",
                    "expected_status": "rejected",
                },
            )

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive_id)
            stored_submission = await session.get(ArchiveSubmission, submission_id)
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission_id,
                    )
                )
                or 0
            )

            assert _column_snapshot(stored_archive) == archive_snapshot
            assert _column_snapshot(stored_submission) == submission_snapshot
            assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_approval_context(
            session_maker,
            submission_id=submission_id,
            category_key=category_key,
            course_name=course_name,
            object_names=[old_object_name, new_object_name],
        )


@pytest.mark.asyncio
async def test_approve_commits_complete_result_visible_to_new_session(
    client,
    session_maker,
    make_user,
):
    unique = uuid.uuid4().hex
    category_key = f"success-{unique[:10]}"
    category_name = f"Success category {unique}"
    course_name = f"Success Course {unique}"
    object_name = f"archive-submissions/success-{unique}.pdf"
    requester = await make_user(name=f"success-requester-{unique[:8]}")
    admin = await make_user(name=f"success-admin-{unique[:8]}", is_admin=True)

    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=course_name,
            category=category_key,
            name=f"Success Exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Success Professor",
            object_name=object_name,
            requested_course_name=course_name,
            requested_category_key=category_key,
            requested_category_name=category_name,
            requested_category_label=category_name,
            requested_category_icon="pi pi-book",
            requester_id=requester.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        submission_id = submission.id

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission_id}/approve",
            json={
                "note": "complete approval",
                "expected_status": "pending",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == SubmissionStatus.APPROVED.value

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
            stored_submission = await session.get(ArchiveSubmission, submission_id)
            archive = await session.get(Archive, stored_submission.created_archive_id)
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission_id,
                            PersonalNotification.notification_type
                            == "archive_submission_approved",
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert category.is_active is True
            assert course.category == category.key
            assert archive.course_id == course.id
            assert archive.object_name == object_name
            assert stored_submission.status == SubmissionStatus.APPROVED
            assert stored_submission.reviewer_id == admin.id
            assert stored_submission.review_note == "complete approval"
            assert stored_submission.reviewed_at is not None
            assert stored_submission.created_archive_id == archive.id
            assert len(notifications) == 1
            assert notifications[0].metadata_json["archive_id"] == archive.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_approval_context(
            session_maker,
            submission_id=submission_id,
            category_key=category_key,
            course_name=course_name,
            object_names=[object_name],
        )


@pytest.mark.asyncio
async def test_approve_preserves_authorization_and_not_found_errors(
    client,
    make_user,
):
    user = await make_user()
    admin = await make_user(is_admin=True)

    async def _get_non_admin():
        return UserRoles(user_id=user.id, is_admin=False)

    try:
        app.dependency_overrides[get_current_user] = _get_non_admin
        forbidden = await client.post(
            "/archives/admin/submissions/999999999/approve",
            json={"expected_status": "pending"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == "Admin access required"

        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        missing = await client.post(
            "/archives/admin/submissions/999999999/approve",
            json={"expected_status": "pending"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Submission not found"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_approve_invalid_course_rolls_back_without_mutation(
    client,
    session_maker,
    make_user,
):
    unique = uuid.uuid4().hex
    category_key = f"invalid-{unique[:12]}"
    object_name = f"archive-submissions/invalid-{unique}.pdf"
    requester = await make_user(name=f"invalid-requester-{unique[:8]}")
    admin = await make_user(name=f"invalid-admin-{unique[:8]}", is_admin=True)

    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="   ",
            category=category_key,
            name=f"Invalid Course Exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Invalid Course Professor",
            object_name=object_name,
            requester_id=requester.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        submission_id = submission.id
        submission_snapshot = _column_snapshot(submission)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission_id}/approve",
            json={"expected_status": "pending"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid course name"

        async with session_maker() as session:
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )
            assert _column_snapshot(stored_submission) == submission_snapshot
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_approval_context(
            session_maker,
            submission_id=submission_id,
            category_key=category_key,
            course_name="",
            object_names=[object_name],
        )
