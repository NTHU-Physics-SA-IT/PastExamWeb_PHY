import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func
from sqlmodel import select

from app.main import app
from app.models.models import (
    AnnouncementReadReceipt,
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveType,
    CommentReport,
    Course,
    Notification,
    NotificationCreate,
    NotificationSeverity,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


async def _create_notification(session_maker, **overrides):
    now = datetime.now(UTC)
    data = NotificationCreate(
        title=f"Test Notification {uuid.uuid4().hex[:6]}",
        body="Hello world",
        severity=NotificationSeverity.INFO,
        is_active=True,
        starts_at=overrides.pop("starts_at", now - timedelta(minutes=5)),
        ends_at=overrides.pop("ends_at", now + timedelta(minutes=5)),
    )
    for field, value in overrides.items():
        setattr(data, field, value)

    async with session_maker() as session:
        notification = Notification(
            **data.model_dump(),
            created_at=now,
            updated_at=now,
        )
        session.add(notification)
        await session.commit()
        await session.refresh(notification)
        return notification


def _override_user(user):
    async def _get_current_user():
        return UserRoles(user_id=user["id"], is_admin=user["is_admin"])

    return _get_current_user


def _personal_notification(*, user_id: int, source_type, source_id=None, source_message_id=None):
    return PersonalNotification(
        user_id=user_id,
        notification_type="c2_test",
        title="C2 notification",
        message="C2 historical notification content",
        source_type=source_type,
        source_id=source_id,
        source_message_id=source_message_id,
        dedupe_key=f"c2:{uuid.uuid4().hex}",
    )


async def _cleanup_c2_source_records(session_maker):
    async with session_maker() as session:
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.dedupe_key.like("c2:%")
            )
        )
        await session.execute(
            delete(CommentReport).where(
                CommentReport.archive_name_snapshot.like("C2 %")
            )
        )
        await session.execute(
            delete(ArchiveReport).where(
                ArchiveReport.archive_name_snapshot.like("C2 %")
            )
        )
        await session.execute(
            delete(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.content.like("C2 %"),
                ArchiveDiscussionMessage.parent_id.is_not(None),
            )
        )
        await session.execute(
            delete(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.content.like("C2 %")
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.subject.like("C2 %"))
        )
        await session.execute(delete(Archive).where(Archive.name.like("C2 %")))
        await session.execute(delete(Course).where(Course.name.like("C2 %")))
        await session.commit()


async def _add_public_archive(session, *, owner_id: int, label: str):
    course = Course(name=f"C2 course {label}", category="freshman")
    session.add(course)
    await session.flush()
    archive = Archive(
        name=f"C2 archive {label}",
        academic_year=2026,
        archive_type=ArchiveType.FINAL,
        professor="C2 Professor",
        object_name=f"archives/c2-{uuid.uuid4().hex}.pdf",
        uploader_id=owner_id,
        course_id=course.id,
    )
    session.add(archive)
    await session.flush()
    return course, archive


async def _notification_projection(client: AsyncClient, user_id: int):
    app.dependency_overrides[get_current_user] = _override_user(
        {"id": user_id, "is_admin": False}
    )
    response = await client.get("/notifications/center")
    assert response.status_code == 200
    return {
        item["id"]: item for item in response.json()["personal_notifications"]
    }


@pytest.mark.asyncio
async def test_public_notification_endpoints_return_active_only(
    client: AsyncClient,
    session_maker,
):
    async with session_maker() as session:
        await session.execute(delete(Notification))
        await session.commit()

    active = await _create_notification(session_maker)
    await _create_notification(
        session_maker,
        is_active=False,
        starts_at=datetime.now(UTC) - timedelta(days=2),
        ends_at=datetime.now(UTC) - timedelta(days=1),
    )

    for path in ("/notifications", "/notifications/active"):
        response = await client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == active.id

    async with session_maker() as session:
        await session.execute(delete(Notification))
        await session.commit()


@pytest.mark.asyncio
async def test_admin_can_crud_notifications(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    editor = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_user(
        {"id": admin.id, "is_admin": True}
    )

    created_id = None

    try:
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)
        payload = {
            "title": "Site maintenance",
            "body": "Expected downtime",
            "severity": NotificationSeverity.DANGER.value,
            "is_active": True,
            "starts_at": start_time.isoformat(),
            "ends_at": end_time.isoformat(),
        }
        response = await client.post(
            "/notifications/admin/notifications",
            json=payload,
        )
        assert response.status_code == 201
        created = response.json()
        created_id = created["id"]
        assert created["title"] == payload["title"]
        assert created["updated_by_username"] == admin.name

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": editor.id, "is_admin": True}
        )
        update_payload = {"title": "Updated title", "is_active": False}
        response = await client.put(
            f"/notifications/admin/notifications/{created_id}",
            json=update_payload,
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["title"] == "Updated title"
        assert updated["is_active"] is False
        assert updated["updated_by_username"] == editor.name

        response = await client.get("/notifications/admin/notifications")
        assert response.status_code == 200
        admin_list = response.json()
        listed = next(item for item in admin_list if item["id"] == created_id)
        assert listed["updated_by_username"] == editor.name

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": admin.id, "is_admin": True}
        )
        response = await client.delete(
            f"/notifications/admin/notifications/{created_id}"
        )
        assert response.status_code == 204

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": editor.id, "is_admin": True}
        )
        response = await client.get("/trash", params={"item_type": "notification"})
        assert response.status_code == 200
        trashed = next(item for item in response.json() if item["id"] == created_id)
        assert trashed["deleted_by_id"] == admin.id
        assert trashed["deleted_by_name"] == admin.name
        assert trashed["canRestore"] is True
        assert trashed["canPermanentDelete"] is True

        response = await client.post(
            "/trash/restore",
            json={"item_type": "notification", "item_id": created_id},
        )
        assert response.status_code == 200
        response = await client.delete(
            f"/notifications/admin/notifications/{created_id}"
        )
        assert response.status_code == 204
        response = await client.get("/trash", params={"item_type": "notification"})
        assert response.status_code == 200
        trashed = next(item for item in response.json() if item["id"] == created_id)
        assert trashed["deleted_by_id"] == editor.id
        assert trashed["deleted_by_name"] == editor.name

        async with session_maker() as session:
            stored = await session.get(Notification, created_id)
            assert stored is not None
            assert stored.updated_by_id == editor.id
            assert stored.deleted_by_id == editor.id
        created_id = None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(Notification))
            await session.commit()


@pytest.mark.asyncio
async def test_update_notification_not_found(client: AsyncClient, make_user):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_user(
        {"id": admin.id, "is_admin": True}
    )

    try:
        response = await client.put(
            "/notifications/admin/notifications/99999",
            json={"title": "Missing"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_delete_notification_not_found(client: AsyncClient, make_user):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_user(
        {"id": admin.id, "is_admin": True}
    )

    try:
        response = await client.delete("/notifications/admin/notifications/424242")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_admin_notifications_require_admin(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    app.dependency_overrides[get_current_user] = _override_user(
        {"id": user.id, "is_admin": False}
    )

    try:
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(hours=1)
        payload = {
            "title": "Forbidden",
            "body": "Nope",
            "severity": NotificationSeverity.INFO.value,
            "is_active": True,
            "starts_at": start_time.isoformat(),
            "ends_at": end_time.isoformat(),
        }

        response = await client.get("/notifications/admin/notifications")
        assert response.status_code == 403

        response = await client.post("/notifications/admin/notifications", json=payload)
        assert response.status_code == 403

        response = await client.put(
            "/notifications/admin/notifications/1", json={"title": "Nope"}
        )
        assert response.status_code == 403

        response = await client.delete("/notifications/admin/notifications/1")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(Notification))
            await session.commit()


@pytest.mark.asyncio
async def test_announcement_reads_are_per_user_and_update_reopens_unread(
    client: AsyncClient, session_maker, make_user
):
    first_user = await make_user()
    second_user = await make_user()
    announcement = await _create_notification(session_maker)
    try:
        app.dependency_overrides[get_current_user] = _override_user(
            {"id": first_user.id, "is_admin": False}
        )
        response = await client.put(
            f"/notifications/announcements/{announcement.id}/read"
        )
        assert response.status_code == 200
        first_center = (await client.get("/notifications/center")).json()
        assert first_center["announcements"][0]["is_read"] is True

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": second_user.id, "is_admin": False}
        )
        second_center = (await client.get("/notifications/center")).json()
        assert second_center["announcements"][0]["is_read"] is False

        async with session_maker() as session:
            stored = await session.get(Notification, announcement.id)
            stored.updated_at = datetime.now(UTC) + timedelta(seconds=1)
            session.add(stored)
            await session.commit()

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": first_user.id, "is_admin": False}
        )
        counts = (await client.get("/notifications/counts")).json()
        assert counts["announcements"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(AnnouncementReadReceipt))
            await session.execute(
                delete(Notification).where(Notification.id == announcement.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_personal_notifications_are_owned_and_can_be_marked_read(
    client: AsyncClient, session_maker, make_user
):
    owner = await make_user()
    other = await make_user()
    async with session_maker() as session:
        item = PersonalNotification(
            user_id=owner.id,
            notification_type="discussion_reply",
            title="有人回覆了你的留言",
            message="reply",
            dedupe_key=f"test:{uuid.uuid4().hex}",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            {"id": other.id, "is_admin": False}
        )
        center = (await client.get("/notifications/center")).json()
        assert center["personal_notifications"] == []
        assert (
            await client.put(f"/notifications/personal/{item.id}/read")
        ).status_code == 404

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": owner.id, "is_admin": False}
        )
        summary = (await client.get("/notifications/unread-summary")).json()
        assert summary["counts"]["personal_notifications"] == 1
        assert summary["personal_notifications"][0]["id"] == item.id
        assert (
            await client.put(f"/notifications/personal/{item.id}/read")
        ).status_code == 200
        assert (await client.get("/notifications/counts")).json()[
            "personal_notifications"
        ] == 0
        assert (await client.put("/notifications/personal/read-all")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(PersonalNotification.id == item.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_archive_submission_notification_fails_closed_for_wrong_owner(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    other = await make_user()
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="Authorization-safe notification source",
            category="freshman",
            name="Final",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Professor",
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.PENDING,
            requester_id=other.id,
        )
        session.add(submission)
        await session.flush()
        item = PersonalNotification(
            user_id=recipient.id,
            notification_type="archive_submission_approved",
            title="投稿審核結果",
            message="Historical notification content",
            source_type="archive_submission",
            source_id=submission.id,
            dedupe_key=f"test-source-authorization:{uuid.uuid4().hex}",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            {"id": recipient.id, "is_admin": False}
        )
        center = (await client.get("/notifications/center")).json()
        projected = next(
            notification
            for notification in center["personal_notifications"]
            if notification["id"] == item.id
        )
        assert projected["message"] == "Historical notification content"
        assert projected["source_available"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(PersonalNotification.id == item.id)
            )
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id == submission.id
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_supported_notification_sources_are_available_when_authorized(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="C2 authorized submission",
            category="freshman",
            name="Final",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="C2 Professor",
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.REJECTED,
            requester_id=recipient.id,
        )
        session.add(submission)
        course, archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        report = ArchiveReport(
            reporter_user_id=recipient.id,
            reporter_name_snapshot="C2 reporter",
            archive_id=archive.id,
            archive_id_snapshot=archive.id,
            course_id=course.id,
            reason="incorrect_metadata",
            archive_name_snapshot=archive.name,
            course_name_snapshot=course.name,
            academic_year_snapshot=archive.academic_year,
            archive_type_snapshot=archive.archive_type.value,
            professor_snapshot=archive.professor,
        )
        root = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            content="C2 authorized root",
        )
        session.add_all([report, root])
        await session.flush()
        reply = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            parent_id=root.id,
            reply_to_message_id=root.id,
            content="C2 authorized reply",
        )
        session.add(reply)
        await session.flush()
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
                source_id=submission.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_report",
                source_id=report.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=root.id,
                source_message_id=reply.id,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert [projected[item_id]["source_available"] for item_id in notification_ids] == [
            True,
            True,
            True,
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_supported_notification_sources_fail_closed_when_missing(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    async with session_maker() as session:
        _, archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        message = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            content="C2 message with missing referenced root",
        )
        session.add(message)
        await session.flush()
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
                source_id=2_000_000_001,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_report",
                source_id=2_000_000_002,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=2_000_000_003,
                source_message_id=message.id,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert all(
            projected[item_id]["source_available"] is False
            for item_id in notification_ids
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_missing_and_unauthorized_sources_have_identical_projection(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    other = await make_user()
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="C2 unauthorized submission",
            category="freshman",
            name="Final",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="C2 Professor",
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.PENDING,
            requester_id=other.id,
        )
        session.add(submission)
        course, archive = await _add_public_archive(
            session, owner_id=other.id, label=uuid.uuid4().hex
        )
        report = ArchiveReport(
            reporter_user_id=other.id,
            reporter_name_snapshot="C2 unauthorized reporter",
            archive_id=archive.id,
            archive_id_snapshot=archive.id,
            course_id=course.id,
            reason="incorrect_metadata",
            archive_name_snapshot=archive.name,
            course_name_snapshot=course.name,
            academic_year_snapshot=archive.academic_year,
            archive_type_snapshot=archive.archive_type.value,
            professor_snapshot=archive.professor,
        )
        session.add(report)
        await session.flush()
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
                source_id=submission.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
                source_id=2_000_000_011,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_report",
                source_id=report.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_report",
                source_id=2_000_000_012,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert {
            projected[item_id]["source_available"] for item_id in notification_ids
        } == {False}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_soft_deleted_or_inactive_sources_are_unavailable(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    now = datetime.now(UTC)
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="C2 deleted submission",
            category="freshman",
            name="Final",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="C2 Professor",
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.REJECTED,
            requester_id=recipient.id,
            deleted_at=now,
        )
        session.add(submission)
        course, archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        course.deleted_at = now
        report = ArchiveReport(
            reporter_user_id=recipient.id,
            reporter_name_snapshot="C2 inactive destination reporter",
            archive_id=archive.id,
            archive_id_snapshot=archive.id,
            course_id=course.id,
            reason="incorrect_metadata",
            archive_name_snapshot=archive.name,
            course_name_snapshot=course.name,
            academic_year_snapshot=archive.academic_year,
            archive_type_snapshot=archive.archive_type.value,
            professor_snapshot=archive.professor,
        )
        session.add(report)
        await session.flush()
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
                source_id=submission.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_report",
                source_id=report.id,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert all(
            projected[item_id]["source_available"] is False
            for item_id in notification_ids
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_discussion_source_requires_coherent_active_root_and_message(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    now = datetime.now(UTC)
    async with session_maker() as session:
        course, archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        other_course, other_archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        deleted_root = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            content="C2 deleted root",
            deleted_at=now,
        )
        active_root = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            content="C2 active root",
        )
        other_root = ArchiveDiscussionMessage(
            archive_id=other_archive.id,
            user_id=recipient.id,
            content="C2 other root",
        )
        session.add_all([deleted_root, active_root, other_root])
        await session.flush()
        child_of_deleted_root = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            parent_id=deleted_root.id,
            content="C2 child of deleted root",
        )
        deleted_child = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            parent_id=active_root.id,
            content="C2 deleted child",
            deleted_at=now,
        )
        other_child = ArchiveDiscussionMessage(
            archive_id=other_archive.id,
            user_id=recipient.id,
            parent_id=other_root.id,
            content="C2 other child",
        )
        session.add_all([child_of_deleted_root, deleted_child, other_child])
        await session.flush()
        course.deleted_at = now
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=deleted_root.id,
                source_message_id=child_of_deleted_root.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=active_root.id,
                source_message_id=deleted_child.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=active_root.id,
                source_message_id=other_child.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_id=active_root.id,
                source_message_id=active_root.id,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert all(
            projected[item_id]["source_available"] is False
            for item_id in notification_ids
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_comment_report_notification_is_readable_but_detail_only(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    async with session_maker() as session:
        report = CommentReport(
            reporter_user_id=recipient.id,
            reason="other",
            comment_content_snapshot="C2 reported content",
            comment_author_name_snapshot="C2 author",
            comment_created_at_snapshot=datetime.now(UTC),
            archive_name_snapshot="C2 comment report archive",
            course_name_snapshot="C2 comment report course",
        )
        session.add(report)
        await session.flush()
        item = _personal_notification(
            user_id=recipient.id,
            source_type="comment_report",
            source_id=report.id,
        )
        session.add(item)
        await session.commit()
        item_id = item.id

    try:
        projected = (await _notification_projection(client, recipient.id))[item_id]
        assert projected["message"] == "C2 historical notification content"
        assert projected["source_available"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_malformed_and_unknown_source_references_fail_closed(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    async with session_maker() as session:
        _, archive = await _add_public_archive(
            session, owner_id=recipient.id, label=uuid.uuid4().hex
        )
        message = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=recipient.id,
            content="C2 valid message for unknown type",
        )
        session.add(message)
        await session.flush()
        notifications = [
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_submission",
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="archive_discussion_thread",
                source_message_id=message.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type="legacy_unknown",
                source_message_id=message.id,
            ),
            _personal_notification(
                user_id=recipient.id,
                source_type=None,
                source_id=archive.id,
            ),
        ]
        session.add_all(notifications)
        await session.commit()
        notification_ids = [item.id for item in notifications]

    try:
        projected = await _notification_projection(client, recipient.id)
        assert all(
            projected[item_id]["source_available"] is False
            for item_id in notification_ids
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)


@pytest.mark.asyncio
async def test_source_less_and_removed_source_notifications_remain_readable(
    client: AsyncClient, session_maker, make_user
):
    recipient = await make_user()
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject="C2 removed submission",
            category="freshman",
            name="Final",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="C2 Professor",
            object_name=f"submissions/{uuid.uuid4().hex}.pdf",
            status=SubmissionStatus.PENDING,
            requester_id=recipient.id,
        )
        session.add(submission)
        await session.flush()
        source_less = _personal_notification(user_id=recipient.id, source_type=None)
        removed = _personal_notification(
            user_id=recipient.id,
            source_type="archive_submission",
            source_id=submission.id,
        )
        session.add_all([source_less, removed])
        await session.commit()
        source_less_id = source_less.id
        removed_id = removed.id
        await session.delete(submission)
        await session.commit()

    try:
        projected = await _notification_projection(client, recipient.id)
        assert projected[source_less_id]["source_available"] is True
        assert projected[removed_id]["source_available"] is False
        assert projected[removed_id]["message"] == "C2 historical notification content"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_c2_source_records(session_maker)



@pytest.mark.asyncio
async def test_personal_notifications_can_be_permanently_deleted_by_owner_only(
    client: AsyncClient, session_maker, make_user, monkeypatch
):
    async def _no_announcements(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.api.services.notifications._list_announcements_for_user",
        _no_announcements,
    )
    owner = await make_user()
    other = await make_user()
    async with session_maker() as session:
        announcement_count_before = int(
            await session.scalar(select(func.count(Notification.id))) or 0
        )
        receipt_count_before = int(
            await session.scalar(select(func.count(AnnouncementReadReceipt.id))) or 0
        )
        owner_items = [
            PersonalNotification(
                user_id=owner.id,
                notification_type="discussion_reply",
                title=f"owner notification {index}",
                message="message",
                dedupe_key=f"delete-owner:{uuid.uuid4().hex}",
            )
            for index in range(2)
        ]
        other_item = PersonalNotification(
            user_id=other.id,
            notification_type="discussion_reply",
            title="other notification",
            message="message",
            dedupe_key=f"delete-other:{uuid.uuid4().hex}",
        )
        session.add_all([*owner_items, other_item])
        await session.commit()
        for item in [*owner_items, other_item]:
            await session.refresh(item)

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            {"id": other.id, "is_admin": False}
        )
        assert (
            await client.delete(f"/notifications/personal/{owner_items[0].id}")
        ).status_code == 404

        app.dependency_overrides[get_current_user] = _override_user(
            {"id": owner.id, "is_admin": False}
        )
        deleted = await client.delete(
            f"/notifications/personal/{owner_items[0].id}"
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"success": True}
        assert (
            await client.delete(f"/notifications/personal/{owner_items[0].id}")
        ).status_code == 404
        assert (await client.get("/notifications/counts")).json()[
            "personal_notifications"
        ] == 1

        deleted_all = await client.delete("/notifications/personal")
        assert deleted_all.status_code == 200
        assert deleted_all.json() == {"deleted_count": 1}
        assert (await client.get("/notifications/counts")).json()[
            "personal_notifications"
        ] == 0
        assert (await client.get("/notifications/unread-summary")).json()[
            "personal_notifications"
        ] == []
        async with session_maker() as session:
            assert await session.get(PersonalNotification, other_item.id) is not None
            assert int(
                await session.scalar(select(func.count(Notification.id))) or 0
            ) == announcement_count_before
            assert int(
                await session.scalar(select(func.count(AnnouncementReadReceipt.id))) or 0
            ) == receipt_count_before
            assert int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.user_id == owner.id
                    )
                )
                or 0
            ) == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.id.in_(
                        [owner_items[0].id, owner_items[1].id, other_item.id]
                    )
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_notification_center_requires_authentication(client: AsyncClient):
    for method, path in (
        (client.get, "/notifications/center"),
        (client.get, "/notifications/counts"),
        (client.get, "/notifications/unread-summary"),
        (client.put, "/notifications/personal/read-all"),
        (client.delete, "/notifications/personal/1"),
        (client.delete, "/notifications/personal"),
    ):
        assert (await method(path)).status_code == 401
