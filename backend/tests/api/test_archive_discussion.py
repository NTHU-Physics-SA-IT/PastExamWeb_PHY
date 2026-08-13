import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import select
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.models.models import (
    Archive,
    ArchiveDiscussionLike,
    ArchiveDiscussionMessage,
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


def test_discussion_ws_rejects_unauthenticated_connection(monkeypatch):
    monkeypatch.setattr("app.main.init_db", AsyncMock())

    with TestClient(app) as ws_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_client.websocket_connect(
                "/courses/1/archives/1/discussion/ws"
            ) as websocket:
                websocket.receive_text()

    assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_discussion_messages_include_batched_current_author_experience(
    client, session_maker, make_user
):
    visible_author = await make_user(nickname="Visible", show_level_title=True)
    hidden_author = await make_user(nickname="Hidden", show_level_title=False)

    async with session_maker() as session:
        course = Course(name="Level Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Level Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="level.pdf",
            uploader_id=visible_author.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)

        for index, status_value in enumerate(
            [SubmissionStatus.APPROVED, SubmissionStatus.TAKEDOWN, SubmissionStatus.DELETED]
        ):
            session.add(
                ArchiveSubmission(
                    subject=f"Subject {index}",
                    category="freshman",
                    name=f"Exam {index}",
                    academic_year=2024,
                    archive_type=ArchiveType.FINAL,
                    professor="Prof",
                    object_name=f"submission-{index}.pdf",
                    requester_id=visible_author.id,
                    status=status_value,
                )
            )
        session.add_all(
            [
                ArchiveDiscussionMessage(
                    archive_id=archive.id, user_id=visible_author.id, content="Visible"
                ),
                ArchiveDiscussionMessage(
                    archive_id=archive.id, user_id=hidden_author.id, content="Hidden"
                ),
            ]
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_user(visible_author.id)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/discussion/messages"
        )
        assert response.status_code == 200
        messages = {message["content"]: message for message in response.json()}
        assert messages["Visible"]["author_show_level_title"] is True
        assert messages["Visible"]["author_experience"] == 2
        assert messages["Hidden"]["author_show_level_title"] is False
        assert messages["Hidden"]["author_experience"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.requester_id == visible_author.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_discussion_ws_sends_history_and_ignores_blank(
    client, session_maker, make_user, monkeypatch
):
    user = await make_user(name="ws-user", nickname="Nick")

    async with session_maker() as session:
        course = Course(name="Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)

        archive = Archive(
            name="Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="obj.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)

        archive_id = archive.id
        course_id = course.id

    async def fake_ws_payload(websocket):
        return {"uid": user.id, "exp": 4102444800}

    monkeypatch.setattr(
        "app.api.services.courses.get_ws_token_payload", fake_ws_payload
    )

    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/courses/{course_id}/archives/{archive_id}/discussion/ws"
        ) as ws:
            first = ws.receive_json()
            assert first["type"] == "history"
            assert first["messages"] == []

            ws.send_text(json.dumps({"type": "send", "content": "   "}))

    async with session_maker() as session:
        result = await session.execute(
            select(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.archive_id == archive_id
            )
        )
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_discussion_ws_accepts_padded_message_within_limit(
    client, session_maker, make_user, monkeypatch
):
    user = await make_user(name="ws-user-2", nickname="Nick2")

    async with session_maker() as session:
        course = Course(name="Course2", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)

        archive = Archive(
            name="Exam2",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="obj2.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)

        archive_id = archive.id
        course_id = course.id

    async def fake_ws_payload(websocket):
        return {"uid": user.id, "exp": 4102444800}

    monkeypatch.setattr(
        "app.api.services.courses.get_ws_token_payload", fake_ws_payload
    )

    content = "a" * 200
    raw = f"  {content}  "

    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/courses/{course_id}/archives/{archive_id}/discussion/ws"
        ) as ws:
            ws.receive_json()  # history
            ws.send_text(json.dumps({"type": "send", "content": raw}))
            msg = ws.receive_json()

    assert msg["type"] == "message"
    assert msg["message"]["content"] == content
    assert msg["message"]["user_name"] == "Nick2"
    assert msg["message"]["author_show_level_title"] is True
    assert msg["message"]["author_experience"] == 0

    async with session_maker() as session:
        await session.execute(
            delete(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.archive_id == archive_id
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_discussion_ws_rejects_message_too_long(
    client, session_maker, make_user, monkeypatch
):
    user = await make_user(name="ws-user-3", nickname="Nick3")

    async with session_maker() as session:
        course = Course(name="Course3", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)

        archive = Archive(
            name="Exam3",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="obj3.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)

        archive_id = archive.id
        course_id = course.id

    async def fake_ws_payload(websocket):
        return {"uid": user.id, "exp": 4102444800}

    monkeypatch.setattr(
        "app.api.services.courses.get_ws_token_payload", fake_ws_payload
    )

    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/courses/{course_id}/archives/{archive_id}/discussion/ws"
        ) as ws:
            ws.receive_json()  # history
            ws.send_text(json.dumps({"type": "send", "content": "a" * 201}))
            err = ws.receive_json()

    assert err["type"] == "error"
    assert err["code"] == "message_too_long"

    async with session_maker() as session:
        await session.execute(
            delete(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.archive_id == archive_id
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_discussion_like_is_idempotent_and_can_be_removed(
    client, session_maker, make_user
):
    user = await make_user(name="like-user")
    async with session_maker() as session:
        course = Course(name="Like Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Like Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="like.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        message = ArchiveDiscussionMessage(
            archive_id=archive.id, user_id=user.id, content="like me"
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)

    path = f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}/like"
    app.dependency_overrides[get_current_user] = _override_user(user.id)
    try:
        first = await client.put(path)
        second = await client.put(path)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == {"liked": True, "like_count": 1}
        assert second.json() == {"liked": True, "like_count": 1}

        async with session_maker() as session:
            likes = (
                await session.execute(
                    select(ArchiveDiscussionLike).where(
                        ArchiveDiscussionLike.message_id == message.id
                    )
                )
            ).scalars().all()
            assert len(likes) == 1

        removed = await client.delete(path)
        removed_again = await client.delete(path)
        assert removed.json() == {"liked": False, "like_count": 0}
        assert removed_again.json() == {"liked": False, "like_count": 0}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveDiscussionLike).where(
                    ArchiveDiscussionLike.message_id == message.id
                )
            )
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_discussion_like_and_pin_create_one_durable_notification(
    client, session_maker, make_user
):
    author = await make_user(name="notification-author", nickname="Author")
    actor = await make_user(name="notification-actor", nickname="Actor")
    admin = await make_user(name="notification-admin", is_admin=True)
    async with session_maker() as session:
        course = Course(name="Notification Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Notification Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            object_name="notification.pdf",
            uploader_id=author.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        message = ArchiveDiscussionMessage(
            archive_id=archive.id, user_id=author.id, content="notify me"
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)

    like_path = f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}/like"
    pin_path = f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}/pin"
    try:
        app.dependency_overrides[get_current_user] = _override_user(actor.id)
        assert (await client.put(like_path)).status_code == 200
        assert (await client.put(like_path)).status_code == 200
        assert (await client.delete(like_path)).status_code == 200

        app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
        assert (await client.patch(pin_path, data={"pinned": "true"})).status_code == 200
        assert (await client.patch(pin_path, data={"pinned": "true"})).status_code == 200
        assert (await client.patch(pin_path, data={"pinned": "false"})).status_code == 200

        async with session_maker() as session:
            notifications = list(
                (
                    await session.execute(
                        select(PersonalNotification).where(
                            PersonalNotification.user_id == author.id,
                            PersonalNotification.notification_type.in_(
                                ["discussion_like", "discussion_pin"]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [item.notification_type for item in notifications].count(
                "discussion_like"
            ) == 1
            assert [item.notification_type for item in notifications].count(
                "discussion_pin"
            ) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.user_id == author.id
                )
            )
            await session.execute(
                delete(ArchiveDiscussionLike).where(
                    ArchiveDiscussionLike.message_id == message.id
                )
            )
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_discussion_like_requires_authentication(client, session_maker, make_user):
    user = await make_user(name="anonymous-like-owner")
    async with session_maker() as session:
        course = Course(name="Auth Like Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Auth Like Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="auth-like.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        message = ArchiveDiscussionMessage(
            archive_id=archive.id, user_id=user.id, content="protected"
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)

    response = await client.put(
        f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}/like"
    )
    assert response.status_code == 401

    async with session_maker() as session:
        await session.execute(
            delete(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.archive_id == archive.id
            )
        )
        await session.execute(delete(Archive).where(Archive.id == archive.id))
        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()


@pytest.mark.asyncio
async def test_discussion_sorting_prioritizes_pin_then_likes_then_newest(
    client, session_maker, make_user
):
    author = await make_user(name="sort-author")
    liker_one = await make_user(name="sort-liker-one")
    liker_two = await make_user(name="sort-liker-two")
    now = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(name="Sort Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Sort Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="sort.pdf",
            uploader_id=author.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        pinned = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=author.id,
            content="pinned",
            is_pinned=True,
            created_at=now - timedelta(days=2),
        )
        popular = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=author.id,
            content="popular",
            created_at=now - timedelta(days=1),
        )
        newer_tied = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=author.id,
            content="newer tied",
            created_at=now,
        )
        older_tied = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=author.id,
            content="older tied",
            created_at=now - timedelta(hours=1),
        )
        session.add_all([pinned, popular, newer_tied, older_tied])
        await session.commit()
        for message in [pinned, popular, newer_tied, older_tied]:
            await session.refresh(message)
        session.add_all(
            [
                ArchiveDiscussionLike(message_id=popular.id, user_id=liker_one.id),
                ArchiveDiscussionLike(message_id=popular.id, user_id=liker_two.id),
                ArchiveDiscussionLike(message_id=newer_tied.id, user_id=liker_one.id),
                ArchiveDiscussionLike(message_id=older_tied.id, user_id=liker_one.id),
            ]
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_user(liker_one.id)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/discussion/messages"
        )
        assert response.status_code == 200
        payload = response.json()
        assert [message["content"] for message in payload] == [
            "pinned",
            "popular",
            "newer tied",
            "older tied",
        ]
        assert payload[1]["like_count"] == 2
        assert payload[1]["liked_by_current_user"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveDiscussionLike).where(
                    ArchiveDiscussionLike.message_id.in_(
                        [pinned.id, popular.id, newer_tied.id, older_tied.id]
                    )
                )
            )
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_discussion_reply_is_threaded_and_cross_archive_reply_is_rejected(
    client, session_maker, make_user, monkeypatch
):
    user = await make_user(name="reply-author", nickname="Reply Author")
    replier = await make_user(name="reply-writer", nickname="Reply Writer")
    async with session_maker() as session:
        course = Course(name="Reply Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        first_archive = Archive(
            name="First Reply Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="reply-one.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        second_archive = Archive(
            name="Second Reply Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="reply-two.pdf",
            uploader_id=user.id,
            course_id=course.id,
        )
        session.add_all([first_archive, second_archive])
        await session.commit()
        await session.refresh(first_archive)
        await session.refresh(second_archive)
        root = ArchiveDiscussionMessage(
            archive_id=first_archive.id, user_id=user.id, content="root"
        )
        foreign_root = ArchiveDiscussionMessage(
            archive_id=second_archive.id, user_id=user.id, content="foreign root"
        )
        session.add_all([root, foreign_root])
        await session.commit()
        await session.refresh(root)
        await session.refresh(foreign_root)

    async def fake_ws_payload(websocket):
        return {"uid": replier.id, "exp": 4102444800}

    monkeypatch.setattr(
        "app.api.services.courses.get_ws_token_payload", fake_ws_payload
    )
    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/courses/{course.id}/archives/{first_archive.id}/discussion/ws"
        ) as ws:
            ws.receive_json()
            ws.send_text(
                json.dumps(
                    {"type": "send", "content": "reply", "reply_to_message_id": root.id}
                )
            )
            reply_event = ws.receive_json()
            assert reply_event["message"]["parent_id"] == root.id
            assert reply_event["message"]["reply_to_message_id"] == root.id

            ws.send_text(
                json.dumps(
                    {
                        "type": "send",
                        "content": "cross archive",
                        "reply_to_message_id": foreign_root.id,
                    }
                )
            )
            error_event = ws.receive_json()
            assert error_event["type"] == "error"
            assert error_event["code"] == "invalid_reply_target"

    async def fake_self_ws_payload(websocket):
        return {"uid": user.id, "exp": 4102444800}

    monkeypatch.setattr(
        "app.api.services.courses.get_ws_token_payload", fake_self_ws_payload
    )
    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/courses/{course.id}/archives/{first_archive.id}/discussion/ws"
        ) as ws:
            ws.receive_json()
            ws.send_text(
                json.dumps(
                    {
                        "type": "send",
                        "content": "self reply",
                        "reply_to_message_id": root.id,
                    }
                )
            )
            assert ws.receive_json()["type"] == "message"

    async with session_maker() as session:
        personal = (
            await session.execute(
                select(PersonalNotification).where(
                    PersonalNotification.user_id == user.id,
                    PersonalNotification.notification_type == "discussion_reply",
                )
            )
        ).scalar_one()
        assert personal.source_id == root.id
        assert personal.metadata_json["archive_id"] == first_archive.id

    app.dependency_overrides[get_current_user] = _override_user(user.id)
    try:
        response = await client.get(
            f"/courses/{course.id}/archives/{first_archive.id}/discussion/messages"
        )
        assert response.status_code == 200
        root_payload = response.json()[0]
        assert [reply["content"] for reply in root_payload["replies"]] == [
            "reply",
            "self reply",
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.user_id == user.id
                )
            )
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id.in_(
                        [first_archive.id, second_archive.id]
                    )
                )
            )
            await session.execute(
                delete(Archive).where(
                    Archive.id.in_([first_archive.id, second_archive.id])
                )
            )
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_non_admin_cannot_pin_and_deleted_root_keeps_active_replies(
    client, session_maker, make_user
):
    owner = await make_user(name="thread-owner")
    async with session_maker() as session:
        course = Course(name="Thread Policy Course", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Thread Policy Exam",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="thread-policy.pdf",
            uploader_id=owner.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        root = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=owner.id,
            content="root to delete",
            is_pinned=True,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        reply = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=owner.id,
            parent_id=root.id,
            reply_to_message_id=root.id,
            content="preserved reply",
        )
        session.add(reply)
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_user(owner.id)
    try:
        pin_response = await client.patch(
            f"/courses/{course.id}/archives/{archive.id}/discussion/{root.id}/pin",
            data={"pinned": "true"},
        )
        assert pin_response.status_code == 403

        delete_response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}/discussion/{root.id}"
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["preserve_thread"] is True

        list_response = await client.get(
            f"/courses/{course.id}/archives/{archive.id}/discussion/messages"
        )
        root_payload = list_response.json()[0]
        assert root_payload["is_deleted"] is True
        assert root_payload["is_pinned"] is False
        assert root_payload["content"] == ""
        assert root_payload["replies"][0]["content"] == "preserved reply"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()


@pytest.mark.asyncio
async def test_discussion_delete_requires_owner_or_admin(
    client, session_maker, make_user
):
    owner = await make_user(name="owner", nickname="Owner")
    other = await make_user(name="other", nickname="Other")

    async with session_maker() as session:
        course = Course(name="Course4", category=CourseCategory.FRESHMAN)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        archive = Archive(
            name="Exam4",
            academic_year=2024,
            archive_type=ArchiveType.FINAL,
            professor="Prof",
            has_answers=False,
            object_name="obj4.pdf",
            uploader_id=owner.id,
            course_id=course.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        message = ArchiveDiscussionMessage(
            archive_id=archive.id,
            user_id=owner.id,
            content="hello",
            created_at=datetime.now(UTC),
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)

    app.dependency_overrides[get_current_user] = _override_user(other.id)
    try:
        response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}"
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    app.dependency_overrides[get_current_user] = _override_user(owner.id)
    try:
        response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}/discussion/{message.id}"
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.archive_id == archive.id
                )
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()
