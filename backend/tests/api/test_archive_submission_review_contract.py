import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import archives as archives_service
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    Course,
    CourseCategory,
    CourseCategoryConfig,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_submission_status as status_service
from app.utils.auth import get_current_user


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


def _override_user(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=False)

    return _get_current_user


async def _fail_if_notification_called(*_args, **_kwargs):
    raise AssertionError("non-transition must not call notification owner")


async def _create_review_context(
    session_maker,
    *,
    requester_id: int,
    reviewer_id: int,
    submission_status: SubmissionStatus,
):
    unique = uuid.uuid4().hex
    async with session_maker() as session:
        course = Course(
            name=f"Review contract course {unique}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()

        archive = None
        if submission_status in {
            SubmissionStatus.APPROVED,
            SubmissionStatus.TAKEDOWN,
        }:
            archive = Archive(
                name=f"Review contract exam {unique}",
                academic_year=2026,
                archive_type=ArchiveType.FINAL,
                professor="Review Contract Professor",
                object_name=f"archives/review-contract-{unique}.pdf",
                uploader_id=requester_id,
                course_id=course.id,
            )
            session.add(archive)
            await session.flush()

        reviewed_at = (
            None
            if submission_status == SubmissionStatus.PENDING
            else datetime(2026, 1, 1, tzinfo=UTC)
        )
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"Review contract exam {unique}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Review Contract Professor",
            object_name=f"archives/review-contract-{unique}.pdf",
            requester_id=requester_id,
            reviewer_id=reviewer_id if reviewed_at else None,
            review_note="original review" if reviewed_at else None,
            reviewed_at=reviewed_at,
            status=submission_status,
            created_archive_id=archive.id if archive else None,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)
        if archive:
            await session.refresh(archive)
    return course, archive, submission


async def _review_snapshot(session_maker, submission_id: int):
    async with session_maker() as session:
        submission = await session.get(ArchiveSubmission, submission_id)
        archive = (
            await session.get(Archive, submission.created_archive_id)
            if submission and submission.created_archive_id
            else None
        )
        notifications = int(
            await session.scalar(
                select(func.count(PersonalNotification.id)).where(
                    PersonalNotification.source_type == "archive_submission",
                    PersonalNotification.source_id == submission_id,
                )
            )
            or 0
        )
        events = int(
            await session.scalar(
                select(func.count(ArchiveSubmissionEvent.id)).where(
                    ArchiveSubmissionEvent.submission_id == submission_id
                )
            )
            or 0
        )
        course = (
            await session.execute(
                select(Course).where(Course.name == submission.subject)
            )
        ).scalar_one()
        return {
            "submission": (
                submission.status,
                submission.reviewer_id,
                submission.reviewed_at,
                submission.review_note,
                submission.lifecycle_reason,
                submission.created_archive_id,
                submission.deleted_at,
                submission.restored_at,
            ),
            "archive": (
                None
                if archive is None
                else (
                    archive.id,
                    archive.course_id,
                    archive.name,
                    archive.academic_year,
                    archive.archive_type,
                    archive.professor,
                    archive.has_answers,
                    archive.object_name,
                    archive.uploader_id,
                    archive.deleted_at,
                    archive.updated_at,
                )
            ),
            "course": (
                course.id,
                course.name,
                course.category,
                course.deleted_at,
            ),
            "category_count": int(
                await session.scalar(
                    select(func.count(CourseCategoryConfig.id)).where(
                        CourseCategoryConfig.key == submission.category
                    )
                )
                or 0
            ),
            "notifications": notifications,
            "events": events,
        }


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
            delete(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.submission_id == submission_id
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        if archive_ids:
            await session.execute(delete(Archive).where(Archive.id.in_(archive_ids)))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.commit()


_MISSING_BODY = object()


@pytest.mark.parametrize(
    ("action", "current_status"),
    [
        ("approve", SubmissionStatus.PENDING),
        ("reject", SubmissionStatus.PENDING),
        ("takedown", SubmissionStatus.PENDING),
        ("republish", SubmissionStatus.TAKEDOWN),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        _MISSING_BODY,
        {"note": None},
        {"expected_status": None},
    ],
    ids=["body-omitted", "field-omitted", "explicit-null"],
)
@pytest.mark.asyncio
async def test_direct_review_routes_require_expected_status(
    client,
    session_maker,
    make_user,
    action,
    current_status,
    payload,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=current_status,
    )
    before = await _review_snapshot(session_maker, submission.id)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        path = f"/archives/admin/submissions/{submission.id}/{action}"
        response = (
            await client.post(path)
            if payload is _MISSING_BODY
            else await client.post(path, json=payload)
        )

        assert response.status_code == 428
        assert response.json()["detail"] == {
            "code": "archive_submission_precondition_required",
            "message": "請重新載入投稿狀態後再執行操作。",
            "reload_required": True,
        }
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize(
    ("action", "current_status"),
    [
        ("approve", SubmissionStatus.PENDING),
        ("reject", SubmissionStatus.PENDING),
        ("takedown", SubmissionStatus.PENDING),
        ("republish", SubmissionStatus.TAKEDOWN),
    ],
)
@pytest.mark.asyncio
async def test_direct_review_routes_reject_malformed_expected_status(
    client,
    session_maker,
    make_user,
    action,
    current_status,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=current_status,
    )
    before = await _review_snapshot(session_maker, submission.id)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={"expected_status": "unknown"},
        )

        assert response.status_code == 422
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_direct_review_authorizes_before_row_disclosure_and_precondition(client):
    async def _non_admin():
        return UserRoles(user_id=999_999_998, is_admin=False)

    app.dependency_overrides[get_current_user] = _non_admin
    try:
        response = await client.post("/archives/admin/submissions/999999999/approve")

        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_direct_review_missing_row_precedes_missing_precondition(
    client,
    make_user,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post("/archives/admin/submissions/999999999/approve")

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.asyncio
async def test_direct_review_routes_classify_expected_state_mismatch_as_stale(
    client,
    session_maker,
    make_user,
    monkeypatch,
    action,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=SubmissionStatus.APPROVED,
    )
    before = await _review_snapshot(session_maker, submission.id)
    monkeypatch.setattr(
        archives_service,
        "enqueue_submission_status_notification",
        _fail_if_notification_called,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={"note": "stale request", "expected_status": "pending"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "archive_submission_stale_state",
            "message": "投稿狀態已變更，請重新載入後再操作。",
            "actual_status": "approved",
            "reload_required": True,
        }
        assert "changed" not in response.json()
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_direct_review_route_rejects_illegal_transition_without_side_effects(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=SubmissionStatus.REJECTED,
    )
    before = await _review_snapshot(session_maker, submission.id)
    monkeypatch.setattr(
        status_service,
        "enqueue_submission_status_notification",
        _fail_if_notification_called,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/takedown",
            json={"note": "illegal request", "expected_status": "rejected"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "archive_submission_illegal_transition",
            "message": "此投稿目前不能執行該審核操作。",
            "actual_status": "rejected",
            "reload_required": False,
        }
        assert "changed" not in response.json()
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize("action", ["approve", "reject", "takedown", "republish"])
@pytest.mark.asyncio
async def test_deleted_submission_rejects_every_direct_review_action(
    client,
    session_maker,
    make_user,
    action,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=SubmissionStatus.DELETED,
    )
    before = await _review_snapshot(session_maker, submission.id)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={"expected_status": "deleted"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "archive_submission_illegal_transition",
            "message": "此投稿目前不能執行該審核操作。",
            "actual_status": "deleted",
            "reload_required": False,
        }
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize(
    ("action", "current_status"),
    [
        ("approve", SubmissionStatus.APPROVED),
        ("reject", SubmissionStatus.REJECTED),
        ("takedown", SubmissionStatus.TAKEDOWN),
        ("republish", SubmissionStatus.APPROVED),
    ],
)
@pytest.mark.asyncio
async def test_direct_review_same_target_actions_are_flat_response_no_ops(
    client,
    session_maker,
    make_user,
    monkeypatch,
    action,
    current_status,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=current_status,
    )
    before = await _review_snapshot(session_maker, submission.id)
    monkeypatch.setattr(
        archives_service,
        "enqueue_submission_status_notification",
        _fail_if_notification_called,
    )
    monkeypatch.setattr(
        status_service,
        "enqueue_submission_status_notification",
        _fail_if_notification_called,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={
                "note": "must not replace original review",
                "expected_status": current_status.value,
            },
        )

        assert response.status_code == 200
        assert response.json()["id"] == submission.id
        assert response.json()["status"] == current_status.value
        assert response.json()["changed"] is False
        assert response.json()["available_actions"] == {
            SubmissionStatus.APPROVED: ["reject", "takedown", "delete"],
            SubmissionStatus.REJECTED: ["approve", "delete"],
            SubmissionStatus.TAKEDOWN: ["republish", "delete"],
        }[current_status]
        assert "submission" not in response.json()
        assert await _review_snapshot(session_maker, submission.id) == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )

@pytest.mark.parametrize(
    ("action", "current_status", "resulting_status", "available_actions"),
    [
        (
            "approve",
            SubmissionStatus.PENDING,
            SubmissionStatus.APPROVED,
            ["reject", "takedown", "delete"],
        ),
        (
            "reject",
            SubmissionStatus.PENDING,
            SubmissionStatus.REJECTED,
            ["approve", "delete"],
        ),
        (
            "takedown",
            SubmissionStatus.PENDING,
            SubmissionStatus.TAKEDOWN,
            ["republish", "delete"],
        ),
        (
            "approve",
            SubmissionStatus.REJECTED,
            SubmissionStatus.APPROVED,
            ["reject", "takedown", "delete"],
        ),
        (
            "republish",
            SubmissionStatus.TAKEDOWN,
            SubmissionStatus.APPROVED,
            ["reject", "takedown", "delete"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_direct_review_true_transitions_return_flat_changed_response(
    client,
    session_maker,
    make_user,
    action,
    current_status,
    resulting_status,
    available_actions,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=current_status,
    )
    before = await _review_snapshot(session_maker, submission.id)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission.id}/{action}",
            json={
                "note": f"true {action}",
                "expected_status": current_status.value,
            },
        )

        assert response.status_code == 200
        assert response.json()["id"] == submission.id
        assert response.json()["status"] == resulting_status.value
        assert response.json()["changed"] is True
        assert response.json()["available_actions"] == available_actions
        assert "submission" not in response.json()

        after = await _review_snapshot(session_maker, submission.id)
        assert after["submission"][0] == resulting_status
        assert after["submission"][1] == admin.id
        assert after["submission"][2] is not None
        assert after["submission"][3] == before["submission"][3]
        assert after["notifications"] == before["notifications"] + 1
        assert after["events"] == before["events"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_repeated_review_cycles_create_distinct_durable_notifications(
    client,
    session_maker,
    make_user,
):
    requester = await make_user(name="repeated-review-requester")
    admin = await make_user(name="repeated-review-admin", is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=SubmissionStatus.PENDING,
    )
    transitions = [
        ("approve", SubmissionStatus.PENDING, SubmissionStatus.APPROVED),
        ("reject", SubmissionStatus.APPROVED, SubmissionStatus.REJECTED),
        ("approve", SubmissionStatus.REJECTED, SubmissionStatus.APPROVED),
        ("reject", SubmissionStatus.APPROVED, SubmissionStatus.REJECTED),
        ("approve", SubmissionStatus.REJECTED, SubmissionStatus.APPROVED),
    ]
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        for action, expected_status, resulting_status in transitions:
            response = await client.post(
                f"/archives/admin/submissions/{submission.id}/{action}",
                json={
                    "note": f"cycle {action}",
                    "expected_status": expected_status.value,
                },
            )

            assert response.status_code == 200
            assert response.json()["changed"] is True
            assert response.json()["status"] == resulting_status.value

        async with session_maker() as session:
            stored_submission = await session.get(ArchiveSubmission, submission.id)
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification)
                        .where(
                            PersonalNotification.user_id == requester.id,
                            PersonalNotification.source_type
                            == "archive_submission",
                            PersonalNotification.source_id == submission.id,
                        )
                        .order_by(PersonalNotification.id)
                    )
                )
                .scalars()
                .all()
            )

        approved_notifications = [
            notification
            for notification in notifications
            if notification.notification_type == "archive_submission_approved"
        ]
        rejected_notifications = [
            notification
            for notification in notifications
            if notification.notification_type == "archive_submission_rejected"
        ]
        assert len(approved_notifications) == 3
        assert len(rejected_notifications) == 2
        assert len(notifications) == 5
        assert {
            notification.notification_type for notification in notifications
        } == {
            "archive_submission_approved",
            "archive_submission_rejected",
        }
        assert len(
            {notification.dedupe_key for notification in approved_notifications}
        ) == 3
        for notification in approved_notifications:
            assert notification.metadata_json == {
                "submission_id": submission.id,
                "archive_id": stored_submission.created_archive_id,
                "course_name": course.name,
                "course_name_en": None,
                "archive_name": submission.name,
                "status": SubmissionStatus.APPROVED.value,
                "destination": "my_submission_status",
            }
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )


@pytest.mark.asyncio
async def test_admin_submission_list_projects_stable_available_actions(
    client,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    contexts = []
    expected_by_id = {}
    try:
        for submission_status, actions in [
            (
                SubmissionStatus.PENDING,
                ["approve", "reject", "takedown", "delete"],
            ),
            (
                SubmissionStatus.APPROVED,
                ["reject", "takedown", "delete"],
            ),
            (SubmissionStatus.REJECTED, ["approve", "delete"]),
            (SubmissionStatus.TAKEDOWN, ["republish", "delete"]),
            (SubmissionStatus.DELETED, []),
        ]:
            course, _, submission = await _create_review_context(
                session_maker,
                requester_id=requester.id,
                reviewer_id=admin.id,
                submission_status=submission_status,
            )
            contexts.append((course.id, submission.id))
            expected_by_id[submission.id] = (
                submission_status.value,
                actions,
            )

        deleted_course, _, deleted_submission = await _create_review_context(
            session_maker,
            requester_id=requester.id,
            reviewer_id=admin.id,
            submission_status=SubmissionStatus.PENDING,
        )
        contexts.append((deleted_course.id, deleted_submission.id))
        async with session_maker() as session:
            row = await session.get(ArchiveSubmission, deleted_submission.id)
            row.deleted_at = datetime.now(UTC)
            await session.commit()
        expected_by_id[deleted_submission.id] = ("deleted", [])

        app.dependency_overrides[get_current_user] = _override_admin(admin.id)
        response = await client.get("/archives/admin/submissions")

        assert response.status_code == 200
        rows_by_id = {
            row["id"]: row for row in response.json() if row["id"] in expected_by_id
        }
        assert set(rows_by_id) == set(expected_by_id)
        for submission_id, (expected_status, actions) in expected_by_id.items():
            row = rows_by_id[submission_id]
            assert row["status"] == expected_status
            assert row["available_actions"] == actions
            assert len(row["available_actions"]) == len(set(row["available_actions"]))
            assert "changed" not in row
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        for course_id, submission_id in contexts:
            await _cleanup_review_context(
                session_maker,
                course_id=course_id,
                submission_id=submission_id,
            )


@pytest.mark.asyncio
async def test_owner_submission_response_does_not_expose_admin_capabilities(
    client,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    course, _, submission = await _create_review_context(
        session_maker,
        requester_id=requester.id,
        reviewer_id=admin.id,
        submission_status=SubmissionStatus.PENDING,
    )
    app.dependency_overrides[get_current_user] = _override_user(requester.id)
    try:
        response = await client.get("/archives/submissions/me")

        assert response.status_code == 200
        row = next(item for item in response.json() if item["id"] == submission.id)
        assert "available_actions" not in row
        assert "changed" not in row
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_review_context(
            session_maker,
            course_id=course.id,
            submission_id=submission.id,
        )
