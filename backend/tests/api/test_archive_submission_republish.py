import asyncio
import uuid

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


async def _create_submission_context(session_maker, *, requester_id: int, status):
    unique = uuid.uuid4().hex[:8]
    async with session_maker() as session:
        course = Course(
            name=f"Republish course {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"Midterm {unique}",
            academic_year=2026,
            archive_type=ArchiveType.MIDTERM,
            professor="Republish Professor",
            object_name=f"archives/republish-{unique}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=str(course.category),
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            status=status,
            requester_id=requester_id,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
    return course, archive, submission


async def _cleanup(
    session_maker, *, course_id: int, archive_id: int, submission_id: int
):
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
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.commit()


@pytest.mark.asyncio
async def test_republish_restores_approved_and_notifies_requester_once(
    client, session_maker, make_user
):
    requester = await make_user(name="republish-requester")
    admin = await make_user(name="republish-admin", is_admin=True)
    course, archive, submission = await _create_submission_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.TAKEDOWN,
    )
    path = f"/archives/admin/submissions/{submission.id}/republish"
    try:
        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        responses = await asyncio.gather(
            client.post(path, json={"note": "重新公開"}),
            client.post(path, json={"note": "重複請求"}),
        )
        assert sorted(response.status_code for response in responses) == [200, 400]
        successful = next(
            response for response in responses if response.status_code == 200
        )
        assert successful.json()["status"] == SubmissionStatus.APPROVED.value

        repeated = await client.post(path, json={"note": "再次重試"})
        assert repeated.status_code == 400

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.APPROVED
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == requester.id,
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission.id,
                            PersonalNotification.notification_type
                            == "archive_submission_republished",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == 1
            notification = notifications[0]
            assert "重新上架" in notification.message
            assert course.name in notification.message
            assert archive.name in notification.message
            assert "已通過" in notification.message
            assert "公開" in notification.message
            assert notification.metadata_json["status"] == "approved"
            assert notification.metadata_json["destination"] == "my_submission_status"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_republish_rejects_other_status_and_rolls_back_notification_failure(
    client, session_maker, make_user, monkeypatch
):
    requester = await make_user(name="republish-rollback-requester")
    admin = await make_user(name="republish-rollback-admin", is_admin=True)
    (
        approved_course,
        approved_archive,
        approved_submission,
    ) = await _create_submission_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.APPROVED,
    )
    course, archive, submission = await _create_submission_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.TAKEDOWN,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        not_takedown = await client.post(
            f"/archives/admin/submissions/{approved_submission.id}/republish"
        )
        assert not_takedown.status_code == 400

        from app.services import archive_submission_status as status_service

        async def fail_notification(*args, **kwargs):
            raise RuntimeError("republish notification failed")

        monkeypatch.setattr(
            status_service,
            "enqueue_personal_notification",
            fail_notification,
        )
        with pytest.raises(RuntimeError, match="republish notification failed"):
            await client.post(f"/archives/admin/submissions/{submission.id}/republish")

        async with session_maker() as session:
            unchanged = await session.get(ArchiveSubmission, submission.id)
            assert unchanged.status == SubmissionStatus.TAKEDOWN
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id.in_(
                                [approved_submission.id, submission.id]
                            ),
                            PersonalNotification.notification_type
                            == "archive_submission_republished",
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_id=approved_course.id,
            archive_id=approved_archive.id,
            submission_id=approved_submission.id,
        )
        await _cleanup(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )
