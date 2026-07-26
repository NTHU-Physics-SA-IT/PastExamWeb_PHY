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


async def _create_archive_report_context(
    session_maker, *, requester_id: int
) -> tuple[Course, Archive, ArchiveSubmission]:
    unique = uuid.uuid4().hex[:8]
    async with session_maker() as session:
        course = Course(
            name=f"Archive Report Course {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"Archive Report Exam {unique}",
            academic_year=2025,
            archive_type=ArchiveType.FINAL,
            professor="Prof Report",
            has_answers=True,
            object_name=f"archive-report-{unique}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            has_answers=archive.has_answers,
            object_name=archive.object_name,
            status=SubmissionStatus.APPROVED,
            requester_id=requester_id,
            owner_id=requester_id,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
    return course, archive, submission


@pytest.mark.asyncio
async def test_archive_report_creation_validates_auth_scope_reason_and_duplicate(
    client, session_maker, make_user
):
    reporter = await make_user(name="archive-reporter")
    course, archive, submission = await _create_archive_report_context(
        session_maker, requester_id=reporter.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        assert (
            await client.post(path, json={"report_reason": "file_unavailable"})
        ).status_code == 401

        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        assert (
            await client.post(path, json={"report_reason": "not_a_reason"})
        ).status_code == 422
        assert (
            await client.post(
                path, json={"report_reason": "other", "custom_message": "  "}
            )
        ).status_code == 422
        assert (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id + 999}",
                json={"report_reason": "file_unavailable"},
            )
        ).status_code == 404

        created = await client.post(
            path,
            json={
                "report_reason": "file_unavailable",
                "custom_message": "下載會失敗",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["archive_submission_id"] == submission.id
        assert body["course_name"] == course.name
        assert body["archive_name"] == archive.name
        assert body["status"] == "pending"
        assert body["can_take_down"] is True
        assert body["custom_message"] == "下載會失敗"
        assert (
            await client.post(path, json={"report_reason": "file_unavailable"})
        ).status_code == 409

        async with session_maker() as session:
            notification = await session.scalar(
                select(PersonalNotification).where(
                    PersonalNotification.user_id == reporter.id,
                    PersonalNotification.notification_type
                    == "archive_report_submitted",
                    PersonalNotification.source_id == body["id"],
                )
            )
            assert notification is not None
            assert notification.title == "已收到考古回報"
            assert f"#{body['id']}" in notification.message
            assert "待審核" in notification.message
            assert notification.metadata_json["archive_id"] == archive.id
        center = await client.get("/notifications/center")
        assert center.status_code == 200
        submitted_item = next(
            item
            for item in center.json()["personal_notifications"]
            if item["notification_type"] == "archive_report_submitted"
            and item["source_id"] == body["id"]
        )
        assert submitted_item["source_available"] is True
        assert submitted_item["metadata"]["course_id"] == course.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.user_id == reporter.id
                )
            )
            await session.execute(
                delete(ArchiveReport).where(ArchiveReport.archive_id == archive.id)
            )
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id == submission.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_archive_report_review_permissions_filters_optional_takedown_and_atomicity(
    client, session_maker, make_user
):
    reporter = await make_user(name="archive-review-reporter")
    admin = await make_user(name="archive-review-admin", is_admin=True)
    course, archive, submission = await _create_archive_report_context(
        session_maker, requester_id=reporter.id
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    reasons = [
        "file_unavailable",
        "metadata_incorrect",
        "privacy_information",
        "duplicate_or_misplaced",
    ]
    report_ids: list[int] = []
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        for reason in reasons:
            response = await client.post(
                path,
                json={"report_reason": reason, "custom_message": f"detail {reason}"},
            )
            assert response.status_code == 201
            report_ids.append(response.json()["id"])

        assert (await client.get("/reports/admin/archives")).status_code == 403
        assert (
            await client.patch(
                f"/reports/admin/archives/{report_ids[0]}",
                json={"status": "dismissed"},
            )
        ).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        page = await client.get(
            "/reports/admin/archives",
            params={
                "search": course.name,
                "sort_by": "reason",
                "sort_order": "asc",
                "limit": 2,
                "offset": 1,
            },
        )
        assert page.status_code == 200
        assert page.json()["total"] == 4
        assert len(page.json()["items"]) == 2
        filtered = await client.get(
            "/reports/admin/archives",
            params={"status": "pending", "reason": "privacy_information"},
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert (
            await client.get(
                "/reports/admin/archives", params={"sort_by": "unknown"}
            )
        ).status_code == 422

        invalid_disposition = await client.patch(
            f"/reports/admin/archives/{report_ids[0]}",
            json={"status": "dismissed", "take_down_archive": True},
        )
        assert invalid_disposition.status_code == 422
        dismissed = await client.patch(
            f"/reports/admin/archives/{report_ids[0]}",
            json={
                "status": "dismissed",
                "admin_response": "查核後檔案正常",
                "take_down_archive": False,
            },
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["archive_taken_down"] is False

        upheld_only = await client.patch(
            f"/reports/admin/archives/{report_ids[1]}",
            json={
                "status": "upheld",
                "admin_response": "資訊將另行修正",
                "take_down_archive": False,
            },
        )
        assert upheld_only.status_code == 200
        assert upheld_only.json()["archive_taken_down"] is False

        async with session_maker() as session:
            current_submission = await session.get(ArchiveSubmission, submission.id)
            assert current_submission.status == SubmissionStatus.APPROVED
            assert await session.get(Archive, archive.id) is not None

        taken_down = await client.patch(
            f"/reports/admin/archives/{report_ids[2]}",
            json={
                "status": "upheld",
                "admin_response": "含有不應公開的個人資料",
                "take_down_archive": True,
            },
        )
        assert taken_down.status_code == 200
        assert taken_down.json()["archive_taken_down"] is True
        assert taken_down.json()["source_state"] == "taken_down"
        assert taken_down.json()["can_take_down"] is False

        public_archives = await client.get(f"/courses/{course.id}/archives")
        assert public_archives.status_code == 200
        assert public_archives.json() == []
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        notification_center = await client.get("/notifications/center")
        assert notification_center.status_code == 200
        taken_down_result = next(
            item
            for item in notification_center.json()["personal_notifications"]
            if item["notification_type"] == "archive_report_result"
            and item["source_id"] == report_ids[2]
        )
        assert taken_down_result["source_available"] is False
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )

        conflict = await client.patch(
            f"/reports/admin/archives/{report_ids[3]}",
            json={"status": "upheld", "take_down_archive": True},
        )
        assert conflict.status_code == 409
        assert (
            await client.patch(
                f"/reports/admin/archives/{report_ids[2]}",
                json={"status": "dismissed"},
            )
        ).status_code == 409

        async with session_maker() as session:
            current_submission = await session.get(ArchiveSubmission, submission.id)
            assert current_submission.status == SubmissionStatus.TAKEDOWN
            source_archive = await session.get(Archive, archive.id)
            assert source_archive is not None
            assert source_archive.object_name == archive.object_name
            pending_conflict = await session.get(ArchiveReport, report_ids[3])
            assert pending_conflict.status == "pending"
            assert pending_conflict.reviewed_at is None
            result_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == reporter.id,
                        PersonalNotification.notification_type
                        == "archive_report_result",
                    )
                )
                or 0
            )
            assert result_count == 3
            result_notification = await session.scalar(
                select(PersonalNotification).where(
                    PersonalNotification.notification_type
                    == "archive_report_result",
                    PersonalNotification.source_id == report_ids[2],
                )
            )
            assert result_notification is not None
            assert "回報成立" in result_notification.message
            assert "已下架" in result_notification.message
            assert result_notification.metadata_json["archive_taken_down"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.user_id.in_([reporter.id, admin.id])
                )
            )
            await session.execute(
                delete(ArchiveReport).where(ArchiveReport.archive_id == archive.id)
            )
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id == submission.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()
