import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_ARCHIVE_TRASHED,
)
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


async def _create_approved_pair(
    client: AsyncClient,
    session_maker,
    *,
    requester_id: int,
    label: str,
):
    unique = uuid.uuid4().hex
    async with session_maker() as session:
        course = Course(
            name=f"Trash Lifecycle Course {label} {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"Trash Lifecycle Exam {label} {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor=f"Trash Professor {label}",
            object_name=f"submissions/trash-{label}-{unique}.pdf",
            requester_id=requester_id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)

    response = await client.post(
        f"/archives/admin/submissions/{submission.id}/approve",
        json={
            "note": f"approve pair {label}",
            "expected_status": "pending",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == SubmissionStatus.APPROVED.value

    async with session_maker() as session:
        stored_submission = await session.get(ArchiveSubmission, submission.id)
        archive = await session.get(Archive, stored_submission.created_archive_id)
        assert stored_submission.status == SubmissionStatus.APPROVED
        assert archive is not None
        assert archive.object_name == submission.object_name
        return course, stored_submission, archive


async def _notification_count(session_maker, *, user_ids: list[int]) -> int:
    async with session_maker() as session:
        return int(
            await session.scalar(
                select(func.count(PersonalNotification.id)).where(
                    PersonalNotification.user_id.in_(user_ids)
                )
            )
            or 0
        )


async def _cleanup_pairs(
    session_maker,
    *,
    course_ids: list[int],
    archive_ids: list[int],
    submission_ids: list[int],
):
    async with session_maker() as session:
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id.in_(submission_ids),
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(
                ArchiveSubmission.id.in_(submission_ids)
            )
        )
        await session.execute(delete(Archive).where(Archive.id.in_(archive_ids)))
        await session.execute(delete(Course).where(Course.id.in_(course_ids)))
        await session.commit()

        assert (
            int(
                await session.scalar(
                    select(func.count(ArchiveSubmission.id)).where(
                        ArchiveSubmission.id.in_(submission_ids)
                    )
                )
                or 0
            )
            == 0
        )
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
        assert (
            int(
                await session.scalar(
                    select(func.count(Course.id)).where(Course.id.in_(course_ids))
                )
                or 0
            )
            == 0
        )


@pytest.mark.asyncio
async def test_archive_trash_restore_temporarily_takes_down_submission_without_notification(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    course, submission, archive = await _create_approved_pair(
        client,
        session_maker,
        requester_id=requester.id,
        label="archive",
    )
    notification_baseline = await _notification_count(
        session_maker,
        user_ids=[requester.id],
    )

    try:
        delete_response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}"
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted"]["archives"] == 1
        assert delete_response.json()["deleted"]["submissions_takedown"] == 1

        async with session_maker() as session:
            trashed_archive = await session.get(Archive, archive.id)
            temporary_submission = await session.get(
                ArchiveSubmission, submission.id
            )
            assert trashed_archive.deleted_at is not None
            assert trashed_archive.deleted_by_id == admin.id
            assert trashed_archive.deleted_reason == "archive deleted"
            assert trashed_archive.restored_at is None
            assert temporary_submission.status == SubmissionStatus.TAKEDOWN
            assert temporary_submission.deleted_at is None
            assert temporary_submission.deleted_by_id is None
            assert (
                temporary_submission.lifecycle_reason
                == LIFECYCLE_ARCHIVE_TRASHED
            )
            assert temporary_submission.reviewer_id == admin.id
            assert temporary_submission.reviewed_at > submission.reviewed_at
            trashed_reviewed_at = temporary_submission.reviewed_at

        assert (
            await _notification_count(
                session_maker,
                user_ids=[requester.id],
            )
            == notification_baseline
        )

        restore_response = await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )
        assert restore_response.status_code == 200
        assert restore_response.json()["restoredArchivesCount"] == 1
        assert restore_response.json()["restoredSubmissionsCount"] == 1

        async with session_maker() as session:
            restored_archive = await session.get(Archive, archive.id)
            restored_submission = await session.get(
                ArchiveSubmission, submission.id
            )
            assert restored_archive.deleted_at is None
            assert restored_archive.deleted_by_id is None
            assert restored_archive.deleted_reason is None
            assert restored_archive.restored_at is not None
            assert restored_archive.restored_by_id == admin.id
            assert restored_submission.status == SubmissionStatus.APPROVED
            assert restored_submission.deleted_at is None
            assert restored_submission.lifecycle_reason is None
            assert restored_submission.reviewer_id == admin.id
            assert restored_submission.reviewed_at > trashed_reviewed_at

        assert (
            await _notification_count(
                session_maker,
                user_ids=[requester.id],
            )
            == notification_baseline
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_pairs(
            session_maker,
            course_ids=[course.id],
            archive_ids=[archive.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_submission_trash_moves_only_its_paired_archive_to_trash(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester_a = await make_user()
    requester_b = await make_user()
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    course_a, submission_a, archive_a = await _create_approved_pair(
        client,
        session_maker,
        requester_id=requester_a.id,
        label="A",
    )
    course_b, submission_b, archive_b = await _create_approved_pair(
        client,
        session_maker,
        requester_id=requester_b.id,
        label="B",
    )
    assert course_a.id != course_b.id
    assert archive_a.object_name != archive_b.object_name
    assert submission_a.object_name != submission_b.object_name
    notification_baseline = await _notification_count(
        session_maker,
        user_ids=[requester_a.id, requester_b.id],
    )

    try:
        response = await client.delete(
            f"/archives/admin/submissions/{submission_a.id}"
        )
        assert response.status_code == 200
        assert response.json()["deleted"]["submissions"] == 1
        assert response.json()["deleted"]["archives"] == 1

        async with session_maker() as session:
            stored_submission_a = await session.get(
                ArchiveSubmission, submission_a.id
            )
            stored_archive_a = await session.get(Archive, archive_a.id)
            stored_submission_b = await session.get(
                ArchiveSubmission, submission_b.id
            )
            stored_archive_b = await session.get(Archive, archive_b.id)

            assert stored_submission_a.status == SubmissionStatus.DELETED
            assert stored_submission_a.deleted_at is not None
            assert stored_submission_a.deleted_by_id == admin.id
            assert stored_submission_a.delete_reason == "admin deleted"
            assert stored_archive_a.deleted_at is not None
            assert stored_archive_a.deleted_by_id == admin.id
            assert stored_archive_a.deleted_reason == "admin deleted"

            assert stored_submission_b.status == SubmissionStatus.APPROVED
            assert stored_submission_b.deleted_at is None
            assert stored_submission_b.created_archive_id == archive_b.id
            assert stored_submission_b.object_name == submission_b.object_name
            assert stored_archive_b.deleted_at is None
            assert stored_archive_b.object_name == archive_b.object_name

        assert (
            await _notification_count(
                session_maker,
                user_ids=[requester_a.id, requester_b.id],
            )
            == notification_baseline
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_pairs(
            session_maker,
            course_ids=[course_a.id, course_b.id],
            archive_ids=[archive_a.id, archive_b.id],
            submission_ids=[submission_a.id, submission_b.id],
        )
