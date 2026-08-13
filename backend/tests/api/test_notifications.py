import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func
from sqlmodel import select

from app.main import app
from app.models.models import (
    AnnouncementReadReceipt,
    Notification,
    NotificationCreate,
    NotificationSeverity,
    PersonalNotification,
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
