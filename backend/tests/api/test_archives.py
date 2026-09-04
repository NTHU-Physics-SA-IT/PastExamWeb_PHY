import io
import uuid
from datetime import UTC, datetime

import pikepdf
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.services.archives import upload_archive
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    ArchiveWish,
    Course,
    CourseCategory,
    CourseCategoryConfig,
    PersonalNotification,
    SubmissionStatus,
    User,
    UserRoles,
)
from app.services import pdf_security
from app.services.archive_submission_review_revision import (
    compute_archive_submission_review_revision,
)
from app.utils.auth import get_current_user


def _build_valid_pdf_bytes() -> bytes:
    payload = io.BytesIO()
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(payload)
    return payload.getvalue()


VALID_PDF_BYTES = _build_valid_pdf_bytes()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_created_submission_events(session_maker):
    """Keep upload/review event rows owned by each test out of the shared baseline."""

    async with session_maker() as session:
        baseline_ids = set(
            (await session.execute(select(ArchiveSubmissionEvent.id))).scalars()
        )

    yield

    async with session_maker() as session:
        await session.execute(
            delete(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.id.not_in(baseline_ids)
            )
        )
        await session.commit()


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


def _override_user(user_id: int, *, is_admin: bool = False):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


async def _create_upload_course(session_maker, *, name: str) -> Course:
    async with session_maker() as session:
        course = Course(
            name=name,
            name_en=f"{name} English",
            category=CourseCategory.FRESHMAN.value,
        )
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course


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


async def _current_review_revision(session_maker, submission_id: int) -> str:
    async with session_maker() as session:
        submission = await session.get(ArchiveSubmission, submission_id)
        assert submission is not None
        return compute_archive_submission_review_revision(submission)


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
    ("creator_kind", "academic_year", "expected_count"),
    [
        ("normal", 2026, 1),
        ("admin", None, 1),
        ("self", 2026, 0),
    ],
)
@pytest.mark.asyncio
async def test_approval_notifies_cross_user_wish_creator_once(
    client: AsyncClient,
    session_maker,
    make_user,
    creator_kind,
    academic_year,
    expected_count,
):
    requester = await make_user(name=f"wish-publisher-{creator_kind}")
    reviewer = await make_user(name=f"wish-reviewer-{creator_kind}", is_admin=True)
    if creator_kind == "self":
        creator = requester
    else:
        creator = await make_user(
            name=f"wish-owner-{creator_kind}",
            is_admin=creator_kind == "admin",
        )
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        wish = ArchiveWish(
            title=f"Approval Wish {creator_kind}",
            target_key=f"approval-wish-{creator_kind}-{submission.id}",
            course_id=course.id,
            subject=course.name,
            category=course.category,
            name=submission.name,
            academic_year=academic_year,
            archive_type=submission.archive_type,
            professor=submission.professor,
            creator_id=creator.id,
        )
        session.add(wish)
        await session.commit()
        await session.refresh(wish)

    app.dependency_overrides[get_current_user] = _override_admin(reviewer.id)
    try:
        async with session_maker() as session:
            assert (
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.notification_type == "wish_fulfilled",
                        PersonalNotification.user_id == creator.id,
                    )
                )
                == 0
            )

        approved = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "note": "publish matching archive",
                "expected_status": "pending",
                "expected_revision": await _current_review_revision(
                    session_maker, submission.id
                ),
            },
        )
        assert approved.status_code == 200
        retry = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "note": "retry",
                "expected_status": "approved",
                "expected_revision": approved.json()["review_revision"],
            },
        )
        assert retry.status_code == 200
        assert retry.json()["changed"] is False

        async with session_maker() as session:
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.notification_type == "wish_fulfilled",
                            PersonalNotification.user_id == creator.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == expected_count
            if notifications:
                assert notifications[0].dedupe_key == f"wish_fulfilled:{wish.id}"
                assert notifications[0].metadata_json["wish_id"] == wish.id
                assert notifications[0].source_type is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.dedupe_key == f"wish_fulfilled:{wish.id}"
                )
            )
            await session.execute(delete(ArchiveWish).where(ArchiveWish.id == wish.id))
            await session.commit()
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_wish_notification_failure_rolls_back_archive_approval(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user(name="wish-rollback-publisher")
    creator = await make_user(name="wish-rollback-owner")
    reviewer = await make_user(name="wish-rollback-reviewer", is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        wish = ArchiveWish(
            title="Rollback Wish",
            target_key=f"rollback-wish-{submission.id}",
            course_id=course.id,
            subject=course.name,
            category=course.category,
            name=submission.name,
            academic_year=submission.academic_year,
            archive_type=submission.archive_type,
            professor=submission.professor,
            creator_id=creator.id,
        )
        session.add(wish)
        await session.commit()
        await session.refresh(wish)

    async def fail_notification(*args, **kwargs):
        raise RuntimeError("wish notification unavailable")

    monkeypatch.setattr(
        "app.api.services.archives.enqueue_new_wish_fulfillment_notifications",
        fail_notification,
    )
    app.dependency_overrides[get_current_user] = _override_admin(reviewer.id)
    try:
        with pytest.raises(RuntimeError, match="wish notification unavailable"):
            await client.post(
                f"/archives/admin/submissions/{submission.id}/approve",
                json={
                    "note": "must roll back",
                    "expected_status": "pending",
                    "expected_revision": await _current_review_revision(
                        session_maker, submission.id
                    ),
                },
            )
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.PENDING
            assert stored.created_archive_id is None
            assert (
                await session.scalar(
                    select(func.count(Archive.id)).where(Archive.course_id == course.id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.dedupe_key == f"wish_fulfilled:{wish.id}"
                    )
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(ArchiveWish).where(ArchiveWish.id == wish.id))
            await session.commit()
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


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
            json={
                "note": "initial approval",
                "expected_status": "pending",
                "expected_revision": await _current_review_revision(
                    session_maker, submission.id
                ),
            },
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
            json={
                "note": f"move to {target_status.value}",
                "expected_status": "approved",
                "expected_revision": approved_response.json()["review_revision"],
            },
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
            assert stored.review_note is None
            assert stored.lifecycle_reason == (
                "move to takedown"
                if target_status == SubmissionStatus.TAKEDOWN
                else None
            )
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
            json={
                "note": "initial rejection",
                "expected_status": "pending",
                "expected_revision": await _current_review_revision(
                    session_maker, submission.id
                ),
            },
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
            json={
                "note": "approved after rejection",
                "expected_status": "rejected",
                "expected_revision": rejected_response.json()["review_revision"],
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == SubmissionStatus.APPROVED.value

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.reviewer_id == admin.id
            assert stored.reviewed_at is not None
            assert stored.reviewed_at > rejected_reviewed_at
            assert stored.review_note is None
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
async def test_transferred_archive_republish_and_option_two_reapproval_preserve_course(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course_a, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )
    course_b = await _create_upload_course(
        session_maker,
        name=f"Transferred destination {uuid.uuid4().hex}",
    )

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    archive_id = None
    try:
        approved = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "expected_status": "pending",
                "expected_revision": await _current_review_revision(
                    session_maker, submission.id
                ),
            },
        )
        assert approved.status_code == 200
        archive_id = approved.json()["created_archive_id"]

        transferred = await client.patch(
            f"/courses/{course_a.id}/archives/{archive_id}/course",
            json={"course_id": course_b.id},
        )
        assert transferred.status_code == 200

        taken_down = await client.post(
            f"/archives/admin/submissions/{submission.id}/takedown",
            json={"expected_status": "approved"},
        )
        assert taken_down.status_code == 200
        edited_while_down = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={
                "subject": "Historical correction while down",
                "name": "Snapshot while down",
                "professor": "Snapshot professor while down",
                "academic_year": 2028,
                "archive_type": "midterm",
                "has_answers": True,
            },
        )
        assert edited_while_down.status_code == 200
        assert edited_while_down.json()["name"] == "Snapshot while down"
        assert edited_while_down.json()["professor"] == "Snapshot professor while down"
        assert edited_while_down.json()["academic_year"] == 2028
        assert edited_while_down.json()["archive_type"] == ArchiveType.MIDTERM.value
        assert edited_while_down.json()["has_answers"] is True
        republished = await client.post(
            f"/archives/admin/submissions/{submission.id}/republish",
            json={"expected_status": "takedown"},
        )
        assert republished.status_code == 200
        assert republished.json()["created_archive_id"] == archive_id

        async with session_maker() as session:
            after_republish = await session.get(Archive, archive_id)
            assert after_republish.course_id == course_b.id
            assert after_republish.name == "Snapshot while down"
            assert after_republish.professor == "Snapshot professor while down"
            assert after_republish.academic_year == 2028
            assert after_republish.archive_type == ArchiveType.MIDTERM
            assert after_republish.has_answers is True
            assert after_republish.object_name == submission.object_name
            assert after_republish.uploader_id == requester.id

        public_after_republish = await client.get(
            f"/courses/public/{course_b.id}/archives"
        )
        assert public_after_republish.status_code == 200
        published = next(
            item for item in public_after_republish.json() if item["id"] == archive_id
        )
        assert published["name"] == "Snapshot while down"
        assert published["professor"] == "Snapshot professor while down"
        assert published["academic_year"] == 2028
        assert published["archive_type"] == ArchiveType.MIDTERM.value
        assert published["has_answers"] is True

        rejected = await client.post(
            f"/archives/admin/submissions/{submission.id}/reject",
            json={
                "expected_status": "approved",
                "expected_revision": republished.json()["review_revision"],
            },
        )
        assert rejected.status_code == 200
        corrected = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={
                "subject": "Historical proposed course remains history",
                "name": "Reapproved corrected exam",
                "professor": "Reapproved corrected professor",
                "academic_year": 2029,
                "archive_type": "quiz",
                "has_answers": True,
            },
        )
        assert corrected.status_code == 200
        reapproved = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "expected_status": "rejected",
                "expected_revision": corrected.json()["review_revision"],
            },
        )
        assert reapproved.status_code == 200
        assert reapproved.json()["current_archive"]["course_id"] == course_b.id

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive_id)
            stored_submission = await session.get(ArchiveSubmission, submission.id)
            assert stored_archive.course_id == course_b.id
            assert stored_archive.name == "Reapproved corrected exam"
            assert stored_archive.professor == "Reapproved corrected professor"
            assert stored_archive.academic_year == 2029
            assert stored_archive.archive_type == ArchiveType.QUIZ
            assert stored_archive.has_answers is True
            assert (
                stored_submission.subject
                == "Historical proposed course remains history"
            )

        public_after_reapproval = await client.get(
            f"/courses/public/{course_b.id}/archives"
        )
        assert public_after_reapproval.status_code == 200
        reapproved_archive = next(
            item for item in public_after_reapproval.json() if item["id"] == archive_id
        )
        assert reapproved_archive["name"] == "Reapproved corrected exam"
        assert reapproved_archive["professor"] == "Reapproved corrected professor"
        assert reapproved_archive["academic_year"] == 2029
        assert reapproved_archive["archive_type"] == ArchiveType.QUIZ.value
        assert reapproved_archive["has_answers"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.source_type == "archive_submission",
                    PersonalNotification.source_id == submission.id,
                )
            )
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id == submission.id)
            )
            if archive_id is not None:
                await session.execute(delete(Archive).where(Archive.id == archive_id))
            await session.execute(
                delete(Course).where(Course.id.in_([course_a.id, course_b.id]))
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_projection_tracks_current_archive_course_without_rewriting_history(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course_a = await _create_upload_course(
        session_maker,
        name=f"Projection source {uuid.uuid4().hex}",
    )
    course_b = await _create_upload_course(
        session_maker,
        name=f"Projection target {uuid.uuid4().hex}",
    )
    async with session_maker() as session:
        archive = Archive(
            course_id=course_a.id,
            name="Projection archive",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Projection professor",
            object_name=f"archives/projection-{uuid.uuid4().hex}.pdf",
            uploader_id=requester.id,
        )
        session.add(archive)
        await session.flush()
        linked = ArchiveSubmission(
            subject="Historical course snapshot",
            category=CourseCategory.FRESHMAN.value,
            name="Historical exam snapshot",
            academic_year=2025,
            archive_type=ArchiveType.MIDTERM,
            professor="Historical professor",
            object_name=f"submissions/projection-{uuid.uuid4().hex}.pdf",
            requested_course_name="Historical requested course",
            requester_id=requester.id,
            status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
        )
        unlinked = ArchiveSubmission(
            subject="Unlinked historical course",
            category=CourseCategory.FRESHMAN.value,
            name="Unlinked exam",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Unlinked professor",
            object_name=f"submissions/unlinked-{uuid.uuid4().hex}.pdf",
            requester_id=requester.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(linked)
        session.add(unlinked)
        await session.commit()
        await session.refresh(archive)
        await session.refresh(linked)
        await session.refresh(unlinked)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        before = await client.get("/archives/admin/submissions")
        assert before.status_code == 200
        before_linked = next(item for item in before.json() if item["id"] == linked.id)
        before_unlinked = next(item for item in before.json() if item["id"] == unlinked.id)
        assert before_linked["current_archive"]["course_id"] == course_a.id
        assert before_linked["current_archive"]["course_name"] == course_a.name
        assert before_linked["requested_course_name"] == "Historical requested course"
        assert before_linked["subject"] == "Historical course snapshot"
        assert before_unlinked["current_archive"] is None

        moved = await client.patch(
            f"/courses/{course_a.id}/archives/{archive.id}/course",
            json={"course_id": course_b.id},
        )
        assert moved.status_code == 200
        after = await client.get("/archives/admin/submissions")
        after_linked = next(item for item in after.json() if item["id"] == linked.id)
        assert after_linked["current_archive"]["course_id"] == course_b.id
        assert after_linked["current_archive"]["course_name"] == course_b.name
        assert after_linked["requested_course_name"] == "Historical requested course"
        assert after_linked["subject"] == "Historical course snapshot"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id.in_([linked.id, unlinked.id])
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(
                delete(Course).where(Course.id.in_([course_a.id, course_b.id]))
            )
            await session.commit()


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
            await client.post(
                f"/archives/admin/submissions/{submissions[0].id}/approve",
                json={
                    "expected_status": "pending",
                    "expected_revision": await _current_review_revision(
                        session_maker, submissions[0].id
                    ),
                },
            ),
            await client.post(
                f"/archives/admin/submissions/{submissions[1].id}/reject",
                json={
                    "expected_status": "pending",
                    "expected_revision": await _current_review_revision(
                        session_maker, submissions[1].id
                    ),
                },
            ),
            await client.post(
                f"/archives/admin/submissions/{submissions[2].id}/takedown",
                json={"expected_status": "pending"},
            ),
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
                delete(CourseCategoryConfig).where(
                    CourseCategoryConfig.key == category_key
                )
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

    fake_pdf = io.BytesIO(VALID_PDF_BYTES)
    unique_course = f"Test Course {unique}"
    unique_course_en = f"Test Course English {unique}"

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
                "request_new_course": "true",
                "requested_course_name": unique_course,
                "requested_course_name_en": unique_course_en,
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
                select(ArchiveSubmission).where(
                    ArchiveSubmission.id == submission_data["id"]
                )
            )
            submission = result.scalar_one_or_none()
            assert submission is not None
            assert submission.subject == unique_course
            assert submission.requested_course_name == unique_course
            assert submission.requested_course_name_en == unique_course_en
            assert submission.requester_id == user_id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == user_id
                )
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
                    io.BytesIO(VALID_PDF_BYTES),
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
                    io.BytesIO(VALID_PDF_BYTES),
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
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == user.id
                )
            )
            count = await session.execute(
                select(func.count()).where(Course.name == subject)
            )
            assert count.scalar() == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == user.id
                )
            )
            await session.execute(delete(Archive).where(Archive.uploader_id == user.id))
            await session.execute(delete(Course).where(Course.name == subject))
            await session.commit()


@pytest.mark.asyncio
async def test_help_upload_preserves_source_wish_and_rejects_target_mismatch(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    user = await make_user()
    unique = uuid.uuid4().hex[:8]
    course = await _create_upload_course(
        session_maker,
        name=f"Wish Upload Course {unique}",
    )
    async with session_maker() as session:
        wish = ArchiveWish(
            title=f"Wish Upload {unique}",
            target_key=f"wish-upload-{unique}",
            course_id=course.id,
            subject=course.name,
            category=course.category,
            name="midterm1",
            academic_year=2026,
            archive_type=ArchiveType.MIDTERM,
            professor="Professor Wish Upload",
            creator_id=user.id,
        )
        session.add(wish)
        await session.commit()
        await session.refresh(wish)
        wish_id = wish.id

    uploaded_objects = []

    class FakeMinio:
        def put_object(self, **kwargs):
            uploaded_objects.append(kwargs["object_name"])

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FakeMinio(),
    )

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user
    common_data = {
        "subject": course.name,
        "category": str(course.category),
        "course_id": course.id,
        "professor": "Professor Wish Upload",
        "archive_type": "midterm",
        "has_answers": "false",
        "filename": "midterm1",
        "academic_year": 2027,
        "source_wish_id": wish_id,
    }
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": ("wish.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")
            },
            data=common_data,
        )
        assert response.status_code == 200
        submission_id = response.json()["submission"]["id"]
        async with session_maker() as session:
            submission = await session.get(ArchiveSubmission, submission_id)
            assert submission.source_wish_id == wish_id
            assert submission.academic_year == 2027

        mismatch = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "mismatch.pdf",
                    io.BytesIO(VALID_PDF_BYTES),
                    "application/pdf",
                )
            },
            data={**common_data, "filename": "final"},
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "wish_upload_target_mismatch"
        assert len(uploaded_objects) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == user.id
                )
            )
            await session.execute(delete(ArchiveWish).where(ArchiveWish.id == wish_id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_upload_archive_rejects_category_only_request_before_storage(
    client: AsyncClient,
    make_user,
    monkeypatch,
):
    user = await make_user()

    class UnexpectedMinio:
        def put_object(self, **kwargs):
            raise AssertionError("category-only validation must precede storage")

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: UnexpectedMinio(),
    )

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "category-only.pdf",
                    io.BytesIO(VALID_PDF_BYTES),
                    "application/pdf",
                )
            },
            data={
                "subject": "Category-only Course",
                "category": "category-only",
                "professor": "Category-only Professor",
                "archive_type": "final",
                "has_answers": "false",
                "filename": "Category-only Exam",
                "academic_year": 2026,
                "request_new_course": "false",
                "request_new_category": "true",
                "requested_category_key": "category-only",
                "requested_category_name": "Category only",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "新增分類必須同時申請新增課程。"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_new_course", "request_new_category"),
    [("true", "false"), ("true", "true")],
)
async def test_parent_requests_still_require_archive_upload(
    client: AsyncClient,
    make_user,
    request_new_course,
    request_new_category,
):
    user = await make_user()

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        response = await client.post(
            "/archives/upload",
            data={
                "subject": "Missing File Course",
                "category": "missing-file-category",
                "professor": "Missing File Professor",
                "archive_type": "final",
                "has_answers": "false",
                "filename": "Missing File Exam",
                "academic_year": 2026,
                "request_new_course": request_new_course,
                "request_new_category": request_new_category,
                "requested_course_name": "Missing File Course",
                "requested_category_key": "missing-file-category",
                "requested_category_name": "Missing File Category",
            },
        )
        assert response.status_code == 422
        assert any(
            error["loc"][-1] == "file" and error["type"] == "missing"
            for error in response.json()["detail"]
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_archive_rejects_large_file(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    course = await _create_upload_course(
        session_maker,
        name="Oversized Course",
    )

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
        big_content = b"x" * (20 * 1024 * 1024 + 1)
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
                "course_id": str(course.id),
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "File size exceeds 20MB limit"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(Course).where(Course.name == "Oversized Course")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_invalid_pdf_precedes_admin_parent_and_storage_mutation(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    admin = await make_user(is_admin=True)
    unique = uuid.uuid4().hex[:8]
    category_key = f"pdf-security-{unique}"
    course_name = f"PDF Security Course {unique}"

    async def fake_get_current_user():
        return UserRoles(user_id=admin.id, is_admin=True)

    class UnexpectedMinio:
        def put_object(self, **_kwargs):
            raise AssertionError("PDF validation must precede MinIO")

    app.dependency_overrides[get_current_user] = fake_get_current_user
    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client", lambda: UnexpectedMinio()
    )
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "invalid.pdf",
                    io.BytesIO(b"%PDF-not-structurally-valid"),
                    "application/pdf",
                )
            },
            data={
                "subject": course_name,
                "category": category_key,
                "professor": "PDF Security Professor",
                "archive_type": "final",
                "has_answers": "false",
                "filename": "Security Boundary",
                "academic_year": 2026,
                "request_new_course": "true",
                "request_new_category": "true",
                "requested_course_name": course_name,
                "requested_course_name_en": f"{course_name} English",
                "requested_category_key": category_key,
                "requested_category_name": f"PDF Security {unique}",
                "requested_category_name_en": f"PDF Security EN {unique}",
                "requested_category_label": f"Security {unique}",
                "requested_category_label_en": f"Security EN {unique}",
                "requested_category_icon": "pi pi-file-pdf",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid or unsupported PDF file"

        async with session_maker() as session:
            category = (
                await session.execute(
                    select(CourseCategoryConfig).where(
                        CourseCategoryConfig.key == category_key
                    )
                )
            ).scalar_one_or_none()
            course = (
                await session.execute(select(Course).where(Course.name == course_name))
            ).scalar_one_or_none()
            assert category is None
            assert course is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_invalid_pdf_uses_shared_validator_for_normal_upload(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    unique_subject = f"Invalid normal PDF {uuid.uuid4().hex}"

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    class UnexpectedMinio:
        def put_object(self, **_kwargs):
            raise AssertionError("shared PDF validation must precede MinIO")

    app.dependency_overrides[get_current_user] = fake_get_current_user
    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client", lambda: UnexpectedMinio()
    )
    try:
        response = await client.post(
            "/archives/upload",
            files={
                "file": (
                    "invalid.pdf",
                    io.BytesIO(b"%PDF-not-structurally-valid"),
                    "application/pdf",
                )
            },
            data={
                "subject": unique_subject,
                "category": CourseCategory.FRESHMAN.value,
                "professor": "PDF Security Professor",
                "archive_type": "final",
                "has_answers": "false",
                "filename": "Security Boundary",
                "academic_year": 2026,
                "request_new_course": "true",
                "requested_course_name": unique_subject,
                "requested_course_name_en": f"{unique_subject} English",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid or unsupported PDF file"
        async with session_maker() as session:
            count = (
                await session.execute(
                    select(func.count(ArchiveSubmission.id)).where(
                        ArchiveSubmission.subject == unique_subject
                    )
                )
            ).scalar_one()
            assert count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_authoritative_backend_pdf_size_limit_remains_20_mib() -> None:
    assert pdf_security.MAX_PDF_BYTES == 20 * 1024 * 1024


@pytest.mark.asyncio
async def test_upload_archive_handles_storage_failure(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    course = await _create_upload_course(
        session_maker,
        name="Fail Course",
    )

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
                    io.BytesIO(VALID_PDF_BYTES),
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
                "course_id": str(course.id),
            },
        )
        assert response.status_code == 500
        assert "Failed to upload file" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(Course).where(Course.name == "Fail Course"))
            await session.commit()


@pytest.mark.asyncio
async def test_post_minio_database_failure_removes_exact_unreferenced_object(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    course = await _create_upload_course(
        session_maker,
        name=f"Compensation zero refs {uuid.uuid4().hex}",
    )

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    class RecordingMinio:
        def __init__(self):
            self.put_names: list[str] = []
            self.removed_names: list[str] = []

        def put_object(self, **kwargs):
            self.put_names.append(kwargs["object_name"])

        def remove_object(self, _bucket: str, object_name: str):
            self.removed_names.append(object_name)

    minio = RecordingMinio()
    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(
                "app.api.services.archives.get_minio_client", lambda: minio
            )

            async def fail_commit(_session):
                raise RuntimeError("synthetic final commit failure")

            patcher.setattr(AsyncSession, "commit", fail_commit)
            response = await client.post(
                "/archives/upload",
                files={
                    "file": (
                        "compensate.pdf",
                        io.BytesIO(VALID_PDF_BYTES),
                        "application/pdf",
                    )
                },
                data={
                    "subject": course.name,
                    "category": course.category,
                    "professor": "Compensation Professor",
                    "archive_type": "final",
                    "has_answers": "false",
                    "filename": "Compensation",
                    "academic_year": 2026,
                    "course_id": str(course.id),
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to upload file"
        assert len(minio.put_names) == 1
        assert minio.removed_names == minio.put_names
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_post_commit_refresh_failure_retains_referenced_object(
    client: AsyncClient,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    course = await _create_upload_course(
        session_maker,
        name=f"Compensation committed ref {uuid.uuid4().hex}",
    )

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    class RecordingMinio:
        def __init__(self):
            self.put_names: list[str] = []
            self.removed_names: list[str] = []

        def put_object(self, **kwargs):
            self.put_names.append(kwargs["object_name"])

        def remove_object(self, _bucket: str, object_name: str):
            self.removed_names.append(object_name)

    minio = RecordingMinio()
    original_refresh = AsyncSession.refresh
    app.dependency_overrides[get_current_user] = fake_get_current_user
    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(
                "app.api.services.archives.get_minio_client", lambda: minio
            )

            async def fail_submission_refresh(session, instance, *args, **kwargs):
                if isinstance(instance, ArchiveSubmission):
                    raise OSError("synthetic response refresh failure")
                return await original_refresh(session, instance, *args, **kwargs)

            patcher.setattr(AsyncSession, "refresh", fail_submission_refresh)
            response = await client.post(
                "/archives/upload",
                files={
                    "file": (
                        "retain.pdf",
                        io.BytesIO(VALID_PDF_BYTES),
                        "application/pdf",
                    )
                },
                data={
                    "subject": course.name,
                    "category": course.category,
                    "professor": "Compensation Professor",
                    "archive_type": "final",
                    "has_answers": "false",
                    "filename": "Retain committed object",
                    "academic_year": 2026,
                    "course_id": str(course.id),
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to upload file"
        assert len(minio.put_names) == 1
        assert minio.removed_names == []
        async with session_maker() as session:
            reference_count = (
                await session.execute(
                    select(func.count(ArchiveSubmission.id)).where(
                        ArchiveSubmission.object_name == minio.put_names[0]
                    )
                )
            ).scalar_one()
            assert reference_count == 1
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.object_name == minio.put_names[0]
                )
            )
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


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

        async def _call(
            subject,
            filename,
            *,
            course_id=None,
            request_new_course=False,
        ):
            upload = UploadFile(
                filename=filename,
                file=io.BytesIO(VALID_PDF_BYTES),
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
                course_id=course_id,
                request_new_course=request_new_course,
                requested_course_name=subject if request_new_course else None,
                requested_course_name_en=(
                    "Direct Subject English" if request_new_course else None
                ),
                current_user=uploader,
                db=session,
            )

        first = await _call(
            "Direct Subject",
            "Direct Archive.pdf",
            request_new_course=True,
        )
        created_course = (
            await session.execute(select(Course).where(Course.name == "Direct Subject"))
        ).scalar_one()
        second = await _call(
            "Direct Subject",
            "Second Archive.pdf",
            course_id=created_course.id,
        )

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
                delete(Archive).where(Archive.id.in_([first_id, second_id]))
            )
            await session.execute(delete(Course).where(Course.id == course_id))
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
                    io.BytesIO(VALID_PDF_BYTES),
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
                "requested_course_name_en": f"{course_name} English",
                "requested_category_key": category_key,
                "requested_category_name": category_name,
                "requested_category_name_en": f"{category_name} English",
                "requested_category_label": category_name,
                "requested_category_label_en": "Admin upload",
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
            assert category.name_en == f"{category_name} English"
            assert category.label_en == "Admin upload"
            assert course.category == category.key
            assert course.name_en == f"{course_name} English"
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
async def test_admin_edit_updates_snapshot_without_parent_or_archive_drift(
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
        assert response.json()["available_actions"] == [
            "approve",
            "reject",
            "takedown",
            "delete",
        ]
        assert "changed" not in response.json()

        async with session_maker() as session:
            category = (
                await session.execute(
                    select(CourseCategoryConfig).where(
                        CourseCategoryConfig.key == new_category_key
                    )
                )
            ).scalar_one_or_none()
            course = (
                await session.execute(
                    select(Course).where(
                        Course.category == new_category_key,
                        Course.name == new_course_name,
                    )
                )
            ).scalar_one_or_none()
            stored_archive = await session.get(Archive, archive_id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )

            assert category is None
            assert course is None
            assert stored_archive.course_id == original_course_id
            assert stored_archive.name != new_course_name
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


@pytest.mark.parametrize(
    ("submission_status", "expected_http_status", "expected_editable"),
    (
        (SubmissionStatus.PENDING, 200, True),
        (SubmissionStatus.REJECTED, 200, True),
        (SubmissionStatus.TAKEDOWN, 200, True),
        (SubmissionStatus.APPROVED, 409, False),
        (SubmissionStatus.DELETED, 409, False),
    ),
)
@pytest.mark.asyncio
async def test_admin_edit_enforces_submission_state_contract(
    client: AsyncClient,
    session_maker,
    make_user,
    submission_status,
    expected_http_status,
    expected_editable,
):
    unique = uuid.uuid4().hex
    requester = await make_user()
    admin = await make_user(is_admin=True)
    deleted_at = (
        datetime.now(UTC) if submission_status == SubmissionStatus.DELETED else None
    )
    archive_deleted_at = (
        datetime.now(UTC) if submission_status == SubmissionStatus.TAKEDOWN else None
    )
    async with session_maker() as session:
        course = Course(
            name=f"Edit state course {unique}",
            category=CourseCategory.FRESHMAN.value,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"Edit state exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Original archive professor",
            object_name=f"archive-submissions/edit-state-{unique}.pdf",
            uploader_id=requester.id,
            deleted_at=archive_deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor="Original submission professor",
            object_name=archive.object_name,
            requester_id=requester.id,
            status=submission_status,
            previous_status=(
                SubmissionStatus.PENDING
                if submission_status == SubmissionStatus.DELETED
                else None
            ),
            created_archive_id=archive.id,
            deleted_at=deleted_at,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_id = submission.id

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.put(
            f"/archives/admin/submissions/{submission_id}",
            json={
                "professor": "Edited submission professor",
                "review_note": "  State-specific annotation  ",
            },
        )

        assert response.status_code == expected_http_status
        if expected_editable:
            assert response.json()["status"] == submission_status.value
            assert response.json()["professor"] == "Edited submission professor"
            assert response.json()["review_note"] == "State-specific annotation"
        else:
            assert response.json() == {
                "detail": {
                    "code": "archive_submission_edit_forbidden",
                    "message": "此狀態的投稿不可直接編輯。",
                    "reload_required": False,
                }
            }

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive_id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )
            assert stored_submission.status == submission_status
            assert stored_submission.professor == (
                "Edited submission professor"
                if expected_editable
                else "Original submission professor"
            )
            assert stored_submission.review_note == (
                "State-specific annotation" if expected_editable else None
            )
            assert stored_archive.professor == "Original archive professor"
            assert stored_archive.deleted_at == archive_deleted_at
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
            )
            await session.execute(delete(Archive).where(Archive.id == archive_id))
            await session.execute(delete(Course).where(Course.id == course_id))
            await session.commit()


@pytest.mark.asyncio
async def test_review_note_survives_takedown_republish_and_explicit_changes(
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
        approved = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "note": "approval action reason",
                "expected_status": "pending",
                "expected_revision": await _current_review_revision(
                    session_maker, submission.id
                ),
            },
        )
        assert approved.status_code == 200
        annotated = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "  stage-a-persistent-review-note  "},
        )
        assert annotated.status_code == 200
        assert annotated.json()["review_note"] == "stage-a-persistent-review-note"

        taken_down = await client.post(
            f"/archives/admin/submissions/{submission.id}/takedown",
            json={"note": "takedown action reason", "expected_status": "approved"},
        )
        assert taken_down.status_code == 200
        assert taken_down.json()["review_note"] == "stage-a-persistent-review-note"
        assert taken_down.json()["lifecycle_reason"] == "takedown action reason"

        republished = await client.post(
            f"/archives/admin/submissions/{submission.id}/republish",
            json={"note": "republish action reason", "expected_status": "takedown"},
        )
        assert republished.status_code == 200
        assert republished.json()["review_note"] == "stage-a-persistent-review-note"
        assert republished.json()["lifecycle_reason"] is None

        changed = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "explicitly changed annotation"},
        )
        assert changed.status_code == 200
        assert changed.json()["review_note"] == "explicitly changed annotation"

        app.dependency_overrides[get_current_user] = _override_user(
            requester.id, is_admin=False
        )
        mine = await client.get("/archives/submissions/me")
        assert mine.status_code == 200
        requester_record = next(
            item for item in mine.json() if item["id"] == submission.id
        )
        assert requester_record["review_note"] == "explicitly changed annotation"

        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        cleared = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "   "},
        )
        assert cleared.status_code == 200
        assert cleared.json()["review_note"] is None
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.review_note is None
            assert stored.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_approved_admin_edit_allows_review_note_only_and_preserves_review_lifecycle(
    client: AsyncClient,
    session_maker,
    make_user,
):
    unique = uuid.uuid4().hex
    requester = await make_user()
    admin = await make_user(is_admin=True)
    reviewed_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"Approved note course {unique}",
            category=CourseCategory.FRESHMAN.value,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"Approved note exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Approved archive professor",
            object_name=f"archives/approved-note-{unique}.pdf",
            uploader_id=requester.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor="Approved submission professor",
            object_name=archive.object_name,
            requester_id=requester.id,
            reviewer_id=admin.id,
            reviewed_at=reviewed_at,
            status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        saved = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={
                "subject": submission.subject,
                "category": submission.category,
                "name": submission.name,
                "academic_year": submission.academic_year,
                "archive_type": submission.archive_type.value,
                "professor": submission.professor,
                "has_answers": submission.has_answers,
                "review_note": "  stage-a-review-note-check  ",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["review_note"] == "stage-a-review-note-check"

        forbidden = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={
                "review_note": "must not persist",
                "professor": "Forbidden approved metadata edit",
            },
        )
        assert forbidden.status_code == 409
        assert forbidden.json()["detail"]["code"] == "archive_submission_edit_forbidden"

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.review_note == "stage-a-review-note-check"
            assert stored.professor == "Approved submission professor"

        cleared = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "   "},
        )
        assert cleared.status_code == 200
        assert cleared.json()["review_note"] is None

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.review_note is None
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.reviewer_id == admin.id
            assert stored.reviewed_at == reviewed_at
            assert stored.created_archive_id == archive.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize("legacy_marker", ("管理員上傳", "admin upload"))
@pytest.mark.asyncio
async def test_admin_edit_normalizes_review_note_and_preserves_legacy_admin_upload(
    client: AsyncClient,
    session_maker,
    make_user,
    legacy_marker,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, submission.id)
        stored.review_note = legacy_marker
        stored.is_admin_upload = False
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "  Updated review note  "},
        )
        assert response.status_code == 200
        assert response.json()["review_note"] == "Updated review note"
        assert response.json()["is_admin_upload"] is True

        cleared = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"review_note": "   "},
        )
        assert cleared.status_code == 200
        assert cleared.json()["review_note"] is None
        assert cleared.json()["is_admin_upload"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_admin_edit_authorization_and_missing_target_keep_existing_boundaries(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    non_admin = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )

    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=non_admin.id,
        is_admin=False,
    )
    try:
        forbidden = await client.put(
            f"/archives/admin/submissions/{submission.id}",
            json={"professor": "Unauthorized edit"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json() == {"detail": "Admin access required"}

        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        missing = await client.put(
            "/archives/admin/submissions/2147483647",
            json={"professor": "Missing edit"},
        )
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Submission not found"}

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.professor == "Lifecycle Professor"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_admin_edit_has_one_caller_owned_commit(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )
    commit_calls = 0
    original_commit = AsyncSession.commit

    async def observed_commit(session):
        nonlocal commit_calls
        commit_calls += 1
        return await original_commit(session)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with monkeypatch.context() as request_patch:
            request_patch.setattr(AsyncSession, "commit", observed_commit)
            response = await client.put(
                f"/archives/admin/submissions/{submission.id}",
                json={"professor": "Single commit professor"},
            )

        assert response.status_code == 200
        assert commit_calls == 1
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.professor == "Single commit professor"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_admin_edit_rolls_back_all_fields_when_final_commit_fails(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_pending_review_context(
        session_maker,
        requester_id=requester.id,
    )

    async def fail_commit(_session):
        raise RuntimeError("injected edit commit failure")

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with monkeypatch.context() as request_patch:
            request_patch.setattr(AsyncSession, "commit", fail_commit)
            with pytest.raises(
                RuntimeError,
                match="injected edit commit failure",
            ):
                await client.put(
                    f"/archives/admin/submissions/{submission.id}",
                    json={
                        "professor": "Must roll back",
                        "name": "Must also roll back",
                    },
                )

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.professor == "Lifecycle Professor"
            assert stored.name != "Must also roll back"
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission.id,
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


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
                "request_new_course": "true",
                "requested_course_name": "Non PDF Course",
                "requested_course_name_en": "Non-PDF Course",
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
        file=io.BytesIO(VALID_PDF_BYTES),
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
    course = await _create_upload_course(
        session_maker,
        name="Failure",
    )

    class FailingMinio:
        def put_object(self, **kwargs):
            raise RuntimeError("storage down")

    monkeypatch.setattr(
        "app.api.services.archives.get_minio_client",
        lambda: FailingMinio(),
    )

    upload = UploadFile(filename="fail.pdf", file=io.BytesIO(VALID_PDF_BYTES))

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
                course_id=course.id,
                current_user=UserRoles(user_id=user.id, is_admin=False),
                db=session,
            )
        assert exc.value.status_code == 500

    async with session_maker() as session:
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()
