import asyncio
import uuid

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.main import app
from app.models.models import (
    Archive,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool = False):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


async def _create_archive_context(
    session_maker,
    *,
    requester_id: int,
    with_submission: bool = True,
):
    unique = uuid.uuid4().hex[:8]
    async with session_maker() as session:
        course = Course(
            name=f"Archive report course {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"Final {unique}",
            academic_year=2025,
            archive_type=ArchiveType.FINAL,
            professor="Report Professor",
            object_name=f"archives/report-{unique}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        submission = None
        if with_submission:
            submission = ArchiveSubmission(
                subject=course.name,
                category=str(course.category),
                name=archive.name,
                academic_year=archive.academic_year,
                archive_type=archive.archive_type,
                professor=archive.professor,
                object_name=archive.object_name,
                status=SubmissionStatus.APPROVED,
                requester_id=requester_id,
                created_archive_id=archive.id,
            )
            session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        if submission is not None:
            await session.refresh(submission)
    return course, archive, submission


async def _cleanup_context(session_maker, *, course_id: int, archive_id: int):
    async with session_maker() as session:
        report_ids = list(
            (
                await session.execute(
                    select(ArchiveReport.id).where(
                        ArchiveReport.archive_id_snapshot == archive_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if report_ids:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.source_type == "archive_report",
                    PersonalNotification.source_id.in_(report_ids),
                )
            )
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission"
            )
        )
        await session.execute(
            delete(ArchiveReport).where(
                ArchiveReport.archive_id_snapshot == archive_id
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(
                ArchiveSubmission.created_archive_id == archive_id
            )
        )
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.commit()


@pytest.mark.asyncio
async def test_archive_report_creation_auth_validation_duplicate_and_notification(
    client, session_maker, make_user
):
    reporter = await make_user(name="archive-report-reporter")
    requester = await make_user(name="archive-report-requester")
    course, archive, _ = await _create_archive_context(
        session_maker, requester_id=requester.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        assert (
            await client.post(path, json={"report_reason": "duplicate_archive"})
        ).status_code == 401

        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        assert (
            await client.post(path, json={"report_reason": "invalid"})
        ).status_code == 422
        assert (
            await client.post(
                path,
                json={"report_reason": "other", "supplementary_detail": "   "},
            )
        ).status_code == 422
        assert (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id + 999}",
                json={"report_reason": "duplicate_archive"},
            )
        ).status_code == 404

        created = await client.post(
            path,
            json={
                "report_reason": "incomplete_or_low_quality",
                "supplementary_detail": "  第三頁模糊  ",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["supplementary_detail"] == "第三頁模糊"
        assert body["archive_id_snapshot"] == archive.id
        assert body["status"] == "pending"
        assert (
            await client.post(
                path,
                json={"report_reason": "file_unavailable_or_corrupt"},
            )
        ).status_code == 409
        assert (
            await client.get(f"{path}/pending")
        ).json()["id"] == body["id"]

        async with session_maker() as session:
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == reporter.id,
                            PersonalNotification.source_type == "archive_report",
                            PersonalNotification.source_id == body["id"],
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == 1
            assert notifications[0].dedupe_key == (
                f"archive_report_submitted:{body['id']}"
            )
            assert course.name in notifications[0].message
            assert archive.name in notifications[0].message
            assert "待審核" in notifications[0].message
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker, course_id=course.id, archive_id=archive.id
        )


@pytest.mark.asyncio
async def test_archive_report_review_optional_takedown_is_atomic_and_non_destructive(
    client, session_maker, make_user, monkeypatch
):
    reporter = await make_user(name="archive-review-reporter")
    requester = await make_user(name="archive-review-requester")
    admin = await make_user(name="archive-review-admin", is_admin=True)
    course, archive, submission = await _create_archive_context(
        session_maker, requester_id=requester.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        created = await client.post(
            path, json={"report_reason": "metadata_mismatch"}
        )
        report_id = created.json()["id"]
        assert (await client.get("/reports/admin/archives")).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        assert (
            await client.patch(
                f"/reports/admin/archives/{report_id}",
                json={"status": "dismissed", "take_down_archive": True},
            )
        ).status_code == 422

        from app.api.services import reports as reports_service

        original_enqueue = reports_service.enqueue_personal_notification

        async def fail_result_notification(*args, **kwargs):
            raise RuntimeError("result notification failed")

        monkeypatch.setattr(
            reports_service,
            "enqueue_personal_notification",
            fail_result_notification,
        )
        with pytest.raises(RuntimeError, match="result notification failed"):
            await client.patch(
                f"/reports/admin/archives/{report_id}",
                json={"status": "upheld", "take_down_archive": True},
            )
        monkeypatch.setattr(
            reports_service, "enqueue_personal_notification", original_enqueue
        )
        async with session_maker() as session:
            rolled_back_report = await session.get(ArchiveReport, report_id)
            rolled_back_submission = await session.get(
                ArchiveSubmission, submission.id
            )
            assert rolled_back_report.status == "pending"
            assert rolled_back_submission.status == SubmissionStatus.APPROVED

        reviewed = await client.patch(
            f"/reports/admin/archives/{report_id}",
            json={
                "status": "upheld",
                "admin_response": "確認內容不符",
                "take_down_archive": True,
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["archive_taken_down"] is True
        assert (
            await client.patch(
                f"/reports/admin/archives/{report_id}",
                json={"status": "dismissed"},
            )
        ).status_code == 409

        async with session_maker() as session:
            live_archive = await session.get(Archive, archive.id)
            live_submission = await session.get(ArchiveSubmission, submission.id)
            assert live_archive is not None
            assert live_archive.deleted_at is None
            assert live_archive.object_name == archive.object_name
            assert live_submission is not None
            assert live_submission.deleted_at is None
            assert live_submission.status == SubmissionStatus.TAKEDOWN
            result_notifications = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == reporter.id,
                        PersonalNotification.notification_type
                        == "archive_report_result",
                        PersonalNotification.source_id == report_id,
                    )
                )
                or 0
            )
            assert result_notifications == 1
            result = await session.scalar(
                select(PersonalNotification).where(
                    PersonalNotification.user_id == reporter.id,
                    PersonalNotification.notification_type
                    == "archive_report_result",
                    PersonalNotification.source_id == report_id,
                )
            )
            assert "已下架" in result.message
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker, course_id=course.id, archive_id=archive.id
        )


@pytest.mark.asyncio
async def test_archive_report_concurrent_create_and_review_have_single_winner(
    client, session_maker, make_user
):
    reporter = await make_user(name="archive-concurrent-reporter")
    requester = await make_user(name="archive-concurrent-requester")
    admin = await make_user(name="archive-concurrent-admin", is_admin=True)
    course, archive, submission = await _create_archive_context(
        session_maker, requester_id=requester.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        responses = await asyncio.gather(
            client.post(path, json={"report_reason": "duplicate_archive"}),
            client.post(path, json={"report_reason": "duplicate_archive"}),
        )
        assert sorted(response.status_code for response in responses) == [201, 409]
        report_id = next(
            response.json()["id"] for response in responses if response.status_code == 201
        )

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        reviews = await asyncio.gather(
            client.patch(
                f"/reports/admin/archives/{report_id}",
                json={"status": "upheld", "take_down_archive": False},
            ),
            client.patch(
                f"/reports/admin/archives/{report_id}",
                json={"status": "dismissed", "take_down_archive": False},
            ),
        )
        assert sorted(response.status_code for response in reviews) == [200, 409]
        async with session_maker() as session:
            assert int(
                await session.scalar(
                    select(func.count(ArchiveReport.id)).where(
                        ArchiveReport.archive_id_snapshot == archive.id
                    )
                )
                or 0
            ) == 1
            unchanged_submission = await session.get(
                ArchiveSubmission, submission.id
            )
            assert unchanged_submission.status == SubmissionStatus.APPROVED
            result = await session.scalar(
                select(PersonalNotification).where(
                    PersonalNotification.user_id == reporter.id,
                    PersonalNotification.notification_type
                    == "archive_report_result",
                    PersonalNotification.source_id == report_id,
                )
            )
            assert result is not None
            assert "未因本次審核下架" in result.message
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker, course_id=course.id, archive_id=archive.id
        )


@pytest.mark.asyncio
async def test_archive_report_review_accepts_missing_or_blank_admin_response(
    client, session_maker, make_user
):
    reporter = await make_user(name="archive-optional-response-reporter")
    requester = await make_user(name="archive-optional-response-requester")
    admin = await make_user(name="archive-optional-response-admin", is_admin=True)
    course, archive, _ = await _create_archive_context(
        session_maker, requester_id=requester.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        upheld_report = (
            await client.post(path, json={"report_reason": "metadata_mismatch"})
        ).json()

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        upheld = await client.patch(
            f"/reports/admin/archives/{upheld_report['id']}",
            json={"status": "upheld", "admin_response": None},
        )
        assert upheld.status_code == 200
        assert upheld.json()["admin_response"] is None

        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        dismissed_report = (
            await client.post(
                path, json={"report_reason": "file_unavailable_or_corrupt"}
            )
        ).json()

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        dismissed = await client.patch(
            f"/reports/admin/archives/{dismissed_report['id']}",
            json={"status": "dismissed", "admin_response": "   "},
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["admin_response"] is None

        async with session_maker() as session:
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.notification_type
                            == "archive_report_result",
                            PersonalNotification.source_id.in_(
                                [upheld_report["id"], dismissed_report["id"]]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notifications) == 2
            assert all(
                "管理員答覆：未提供答覆" in item.message
                for item in notifications
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker, course_id=course.id, archive_id=archive.id
        )
