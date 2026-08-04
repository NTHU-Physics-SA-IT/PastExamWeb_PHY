import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, text
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
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import LifecycleResourceClass


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


async def _run_two_request_lock_race(
    *,
    monkeypatch,
    first_request,
    second_request,
):
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    call_count = 0
    traces = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        nonlocal call_count
        call_count += 1
        call_number = call_count
        traces.append(
            [(resource.resource_class, resource.row_id) for resource in plan.resources]
        )
        if call_number == 1:
            locked = await original_acquire(db, plan)
            first_locked.set()
            await asyncio.wait_for(release_first.wait(), timeout=5)
            return locked
        if call_number == 2:
            second_attempted.set()
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    first_task = asyncio.create_task(first_request())
    await asyncio.wait_for(first_locked.wait(), timeout=5)
    second_task = asyncio.create_task(second_request())
    await asyncio.wait_for(second_attempted.wait(), timeout=5)
    release_first.set()
    return (
        await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=10,
        ),
        traces,
    )


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
async def test_legacy_archive_can_be_reported_without_submission(
    client, session_maker, make_user
):
    reporter = await make_user(name=f"legacy-reporter-{uuid.uuid4().hex[:8]}")
    uploader = await make_user(name=f"legacy-uploader-{uuid.uuid4().hex[:8]}")
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=uploader.id,
        with_submission=False,
    )
    assert submission is None
    path = f"/reports/courses/{course.id}/archives/{archive.id}"

    async with session_maker() as session:
        notifications_before = int(
            await session.scalar(
                select(func.count(PersonalNotification.id)).where(
                    PersonalNotification.user_id == reporter.id,
                    PersonalNotification.notification_type
                    == "archive_report_submitted",
                )
            )
            or 0
        )

    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        response = await client.post(
            path,
            json={"report_reason": "duplicate_archive"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["archive_submission_id"] is None
        assert body["archive_id_snapshot"] == archive.id
        assert body["archive_name"] == archive.name
        assert body["course_name"] == course.name
        assert body["academic_year"] == archive.academic_year
        assert body["archive_type"] == archive.archive_type.value
        assert body["professor"] == archive.professor
        assert body["reporter_user_id"] == reporter.id
        assert body["reviewed_by"] is None
        assert body["reviewed_at"] is None

        async with session_maker() as session:
            persisted = await session.get(ArchiveReport, body["id"])
            assert persisted is not None
            assert persisted.status == "pending"
            assert persisted.archive_submission_id is None
            assert persisted.archive_id_snapshot == archive.id
            assert persisted.archive_name_snapshot == archive.name
            assert persisted.course_name_snapshot == course.name
            assert persisted.academic_year_snapshot == archive.academic_year
            assert persisted.archive_type_snapshot == archive.archive_type.value
            assert persisted.professor_snapshot == archive.professor
            assert persisted.reporter_user_id == reporter.id
            assert persisted.reporter_name_snapshot == reporter.name
            assert persisted.reviewed_by is None
            assert persisted.reviewed_at is None
            assert persisted.created_at is not None

            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == reporter.id,
                            PersonalNotification.notification_type
                            == "archive_report_submitted",
                            PersonalNotification.source_type == "archive_report",
                            PersonalNotification.source_id == body["id"],
                        )
                    )
                )
                .scalars()
                .all()
            )
            notifications_after = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == reporter.id,
                        PersonalNotification.notification_type
                        == "archive_report_submitted",
                    )
                )
                or 0
            )
            assert notifications_after == notifications_before + 1
            assert len(notifications) == 1
            assert notifications[0].dedupe_key == (
                f"archive_report_submitted:{body['id']}"
            )
            assert notifications[0].metadata_json["archive_id"] == archive.id
            assert notifications[0].metadata_json["course_id"] == course.id
            assert notifications[0].metadata_json["status"] == "pending"
            assert course.name in notifications[0].message
            assert archive.name in notifications[0].message
            assert "待審核" in notifications[0].message
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )
        async with session_maker() as session:
            assert await session.get(Archive, archive.id) is None
            assert await session.get(Course, course.id) is None
            assert (
                await session.scalar(
                    select(func.count(ArchiveReport.id)).where(
                        ArchiveReport.archive_id_snapshot == archive.id
                    )
                )
                or 0
            ) == 0


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


@pytest.mark.asyncio
async def test_archive_report_review_locks_exact_parents_before_report(
    client, session_maker, make_user, monkeypatch
):
    reporter = await make_user(name=f"report-lock-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"report-lock-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"report-lock-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    traces: list[list[tuple[LifecycleResourceClass, int]]] = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(
            [(resource.resource_class, resource.row_id) for resource in plan.resources]
        )
        return await original_acquire(db, plan)

    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(path, json={"report_reason": "metadata_mismatch"})
        ).json()
        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_lifecycle_locks",
            observed_acquire,
        )
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        response = await client.patch(
            f"/reports/admin/archives/{report['id']}",
            json={"status": "dismissed"},
        )

        assert response.status_code == 200
        assert traces, "ArchiveReport review did not execute the canonical planner"
        assert traces == [
            [
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, submission.id),
                (LifecycleResourceClass.ARCHIVE_REPORT, report["id"]),
            ]
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.asyncio
async def test_legacy_archive_report_plan_omits_submission_without_fabrication(
    client, session_maker, make_user, monkeypatch
):
    reporter = await make_user(name=f"legacy-lock-reporter-{uuid.uuid4().hex[:8]}")
    uploader = await make_user(name=f"legacy-lock-uploader-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"legacy-lock-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=uploader.id,
        with_submission=False,
    )
    assert submission is None
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    traces: list[list[tuple[LifecycleResourceClass, int]]] = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(
            [(resource.resource_class, resource.row_id) for resource in plan.resources]
        )
        return await original_acquire(db, plan)

    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(path, json={"report_reason": "duplicate_archive"})
        ).json()
        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_lifecycle_locks",
            observed_acquire,
        )
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        from app.api.services import reports as reports_service

        original_enqueue = reports_service.enqueue_personal_notification

        async def fail_result_notification(*args, **kwargs):
            raise RuntimeError("legacy result notification failed")

        monkeypatch.setattr(
            reports_service,
            "enqueue_personal_notification",
            fail_result_notification,
        )
        with pytest.raises(RuntimeError, match="legacy result notification failed"):
            await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "upheld", "take_down_archive": True},
            )
        monkeypatch.setattr(
            reports_service,
            "enqueue_personal_notification",
            original_enqueue,
        )
        async with session_maker() as session:
            rolled_back_archive = await session.get(Archive, archive.id)
            rolled_back_report = await session.get(ArchiveReport, report["id"])
            assert rolled_back_archive is not None
            assert rolled_back_archive.deleted_at is None
            assert rolled_back_report is not None
            assert rolled_back_report.status == "pending"
            assert rolled_back_report.archive_taken_down is False

        legacy_takedown = await client.patch(
            f"/reports/admin/archives/{report['id']}",
            json={"status": "upheld", "take_down_archive": True},
        )
        retry = await client.patch(
            f"/reports/admin/archives/{report['id']}",
            json={"status": "upheld", "take_down_archive": True},
        )

        assert legacy_takedown.status_code == 200
        assert legacy_takedown.json()["status"] == "upheld"
        assert legacy_takedown.json()["archive_taken_down"] is True
        assert retry.status_code == 409
        assert retry.json()["detail"] == "A finalized report cannot be changed"
        assert traces, "Legacy ArchiveReport review did not execute the planner"
        expected = [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_REPORT, report["id"]),
        ]
        assert traces == [
            expected,
            expected,
            expected,
        ]
        async with session_maker() as session:
            persisted_archive = await session.get(Archive, archive.id)
            persisted_report = await session.get(ArchiveReport, report["id"])
            submission_count = int(
                await session.scalar(
                    select(func.count(ArchiveSubmission.id)).where(
                        ArchiveSubmission.created_archive_id == archive.id
                    )
                )
                or 0
            )
            assert persisted_archive is not None
            assert persisted_archive.deleted_at is not None
            assert persisted_archive.deleted_by_id == admin.id
            assert persisted_report is not None
            assert persisted_report.status == "upheld"
            assert persisted_report.archive_taken_down is True
            assert submission_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.asyncio
async def test_archive_report_soft_trash_and_restore_share_parent_first_plan(
    client, session_maker, make_user, monkeypatch
):
    reporter = await make_user(name=f"trash-lock-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"trash-lock-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"trash-lock-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    traces: list[list[tuple[LifecycleResourceClass, int]]] = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(
            [(resource.resource_class, resource.row_id) for resource in plan.resources]
        )
        return await original_acquire(db, plan)

    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(path, json={"report_reason": "metadata_mismatch"})
        ).json()
        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_lifecycle_locks",
            observed_acquire,
        )
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        deleted = await client.delete(f"/reports/admin/archives/{report['id']}")
        repeated_delete = await client.delete(f"/reports/admin/archives/{report['id']}")
        restored = await client.post(
            "/trash/restore",
            json={"item_type": "archive_report", "item_id": report["id"]},
        )
        repeated_restore = await client.post(
            "/trash/restore",
            json={"item_type": "archive_report", "item_id": report["id"]},
        )

        assert deleted.status_code == 200
        assert repeated_delete.status_code == 404
        assert restored.status_code == 200
        assert repeated_restore.status_code == 404
        assert traces, "ArchiveReport trash/restore did not execute the planner"
        expected = [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, submission.id),
            (LifecycleResourceClass.ARCHIVE_REPORT, report["id"]),
        ]
        assert traces == [expected, expected, expected, expected]
        async with session_maker() as session:
            assert (
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_report",
                        PersonalNotification.source_id == report["id"],
                    )
                )
                or 0
            ) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize("review_first", [True, False])
@pytest.mark.asyncio
async def test_archive_report_review_and_archive_trash_serialize_parent_first(
    client, session_maker, make_user, monkeypatch, review_first
):
    reporter = await make_user(name=f"archive-race-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"archive-race-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"archive-race-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        async def review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "upheld", "take_down_archive": False},
            )

        async def trash_archive():
            return await client.delete(f"/courses/{course.id}/archives/{archive.id}")

        requests = (review, trash_archive) if review_first else (trash_archive, review)
        responses, traces = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=requests[0],
            second_request=requests[1],
        )

        assert [response.status_code for response in responses] == [200, 200]
        assert all(
            trace[:3]
            == [
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, submission.id),
            ]
            for trace in traces
        )
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission.id,
            )
            assert stored_report.status == "upheld"
            assert stored_archive.deleted_at is not None
            assert stored_submission.status == SubmissionStatus.TAKEDOWN
            assert (
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.notification_type
                        == "archive_report_result",
                        PersonalNotification.source_id == report["id"],
                    )
                )
                or 0
            ) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize("restore_first", [True, False])
@pytest.mark.asyncio
async def test_archive_report_takedown_and_archive_restore_serialize(
    client, session_maker, make_user, monkeypatch, restore_first
):
    reporter = await make_user(name=f"restore-race-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"restore-race-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"restore-race-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )
        assert (
            await client.delete(f"/courses/{course.id}/archives/{archive.id}")
        ).status_code == 200

        async def review_with_takedown():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "upheld", "take_down_archive": True},
            )

        async def restore_archive():
            return await client.post(
                "/trash/restore",
                json={"item_type": "archive", "item_id": archive.id},
            )

        requests = (
            (restore_archive, review_with_takedown)
            if restore_first
            else (review_with_takedown, restore_archive)
        )
        responses, _ = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=requests[0],
            second_request=requests[1],
        )

        if restore_first:
            assert [response.status_code for response in responses] == [200, 200]
        else:
            assert [response.status_code for response in responses] == [409, 200]
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission.id,
            )
            assert stored_archive.deleted_at is None
            if restore_first:
                assert stored_report.status == "upheld"
                assert stored_submission.status == SubmissionStatus.TAKEDOWN
            else:
                assert stored_report.status == "pending"
                assert stored_submission.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize("course_first", [True, False])
@pytest.mark.asyncio
async def test_archive_report_review_and_course_trash_serialize(
    client, session_maker, make_user, monkeypatch, course_first
):
    reporter = await make_user(name=f"course-race-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"course-race-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"course-race-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        async def review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "dismissed"},
            )

        async def trash_course():
            return await client.delete(f"/courses/admin/courses/{course.id}")

        requests = (trash_course, review) if course_first else (review, trash_course)
        responses, _ = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=requests[0],
            second_request=requests[1],
        )

        assert [response.status_code for response in responses] == [200, 200]
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            stored_course = await session.get(Course, course.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission.id,
            )
            assert stored_report.status == "dismissed"
            assert stored_course.deleted_at is not None
            assert stored_submission.status == SubmissionStatus.TAKEDOWN
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize("restore_first", [True, False])
@pytest.mark.asyncio
async def test_archive_report_review_and_course_restore_serialize(
    client, session_maker, make_user, monkeypatch, restore_first
):
    reporter = await make_user(name=f"course-restore-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"course-restore-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"course-restore-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )
        assert (
            await client.delete(f"/courses/admin/courses/{course.id}")
        ).status_code == 200

        async def review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "dismissed"},
            )

        async def restore_course():
            return await client.post(
                "/trash/restore",
                json={"item_type": "course", "item_id": course.id},
            )

        requests = (
            (restore_course, review) if restore_first else (review, restore_course)
        )
        responses, _ = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=requests[0],
            second_request=requests[1],
        )

        assert [response.status_code for response in responses] == [200, 200]
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            stored_course = await session.get(Course, course.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                submission.id,
            )
            assert stored_report.status == "dismissed"
            assert stored_course.deleted_at is None
            assert stored_submission.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize(
    ("first_status", "second_status"),
    [("upheld", "dismissed"), ("dismissed", "upheld")],
)
@pytest.mark.asyncio
async def test_archive_report_concurrent_finalization_has_one_winner(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_status,
    second_status,
):
    reporter = await make_user(name=f"decision-race-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"decision-race-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"decision-race-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, _ = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        async def first_review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": first_status},
            )

        async def second_review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": second_status},
            )

        responses, _ = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=first_review,
            second_request=second_review,
        )

        assert [response.status_code for response in responses] == [200, 409]
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            assert stored_report.status == first_status
            assert (
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.notification_type
                        == "archive_report_result",
                        PersonalNotification.source_id == report["id"],
                    )
                )
                or 0
            ) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.parametrize("trash_first", [True, False])
@pytest.mark.asyncio
async def test_archive_report_review_and_soft_trash_serialize_same_row(
    client, session_maker, make_user, monkeypatch, trash_first
):
    reporter = await make_user(name=f"report-trash-reporter-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"report-trash-requester-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"report-trash-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )
    course, archive, _ = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = (
            await client.post(
                f"/reports/courses/{course.id}/archives/{archive.id}",
                json={"report_reason": "metadata_mismatch"},
            )
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id,
            is_admin=True,
        )

        async def review():
            return await client.patch(
                f"/reports/admin/archives/{report['id']}",
                json={"status": "upheld"},
            )

        async def trash_report():
            return await client.delete(f"/reports/admin/archives/{report['id']}")

        requests = (trash_report, review) if trash_first else (review, trash_report)
        responses, _ = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=requests[0],
            second_request=requests[1],
        )

        assert [response.status_code for response in responses] == (
            [200, 404] if trash_first else [200, 200]
        )
        async with session_maker() as session:
            stored_report = await session.get(ArchiveReport, report["id"])
            assert stored_report.deleted_at is not None
            assert stored_report.status == ("pending" if trash_first else "upheld")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )


@pytest.mark.asyncio
async def test_two_archive_reports_reverse_input_lock_in_numeric_order(
    client, session_maker, make_user
):
    first_reporter = await make_user(name=f"reverse-report-a-{uuid.uuid4().hex[:8]}")
    second_reporter = await make_user(name=f"reverse-report-b-{uuid.uuid4().hex[:8]}")
    requester = await make_user(name=f"reverse-requester-{uuid.uuid4().hex[:8]}")
    course, archive, _ = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    path = f"/reports/courses/{course.id}/archives/{archive.id}"
    try:
        app.dependency_overrides[get_current_user] = _override_user(first_reporter.id)
        first_report = (
            await client.post(path, json={"report_reason": "metadata_mismatch"})
        ).json()
        app.dependency_overrides[get_current_user] = _override_user(second_reporter.id)
        second_report = (
            await client.post(path, json={"report_reason": "duplicate_archive"})
        ).json()

        reverse = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            report_ids=[second_report["id"], first_report["id"]]
        )
        forward = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            report_ids=[first_report["id"], second_report["id"]]
        )
        assert reverse == forward
        assert reverse.ids_for(LifecycleResourceClass.ARCHIVE_REPORT) == tuple(
            sorted([first_report["id"], second_report["id"]])
        )

        first_locked = asyncio.Event()
        release_first = asyncio.Event()
        second_attempted = asyncio.Event()

        async def lock_first():
            async with session_maker() as session:
                await session.execute(text("SET LOCAL lock_timeout = '3s'"))
                await archive_lifecycle_locks.acquire_lifecycle_locks(
                    session,
                    reverse,
                )
                first_locked.set()
                await asyncio.wait_for(release_first.wait(), timeout=5)
                await session.commit()

        async def lock_second():
            async with session_maker() as session:
                await session.execute(text("SET LOCAL lock_timeout = '3s'"))
                second_attempted.set()
                await archive_lifecycle_locks.acquire_lifecycle_locks(
                    session,
                    forward,
                )
                await session.commit()

        first_task = asyncio.create_task(lock_first())
        await asyncio.wait_for(first_locked.wait(), timeout=5)
        second_task = asyncio.create_task(lock_second())
        await asyncio.wait_for(second_attempted.wait(), timeout=5)
        release_first.set()
        await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=10,
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            course_id=course.id,
            archive_id=archive.id,
        )
