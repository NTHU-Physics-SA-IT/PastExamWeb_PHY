import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models.models import AboutUsEntry, UserRoles
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


@pytest.mark.asyncio
async def test_about_us_is_readable_and_admin_managed(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    user = await make_user()
    created_ids = []

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        assert (await client.get("/about-us")).status_code == 200
        assert (
            await client.post(
                "/about-us/admin/entries",
                json={
                    "body": "Nope",
                    "body_en": "Nope in English",
                },
            )
        ).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        missing_english = await client.post(
            "/about-us/admin/entries",
            json={"body": "Missing English body"},
        )
        assert missing_english.status_code == 422
        for title in ("First", "Second"):
            response = await client.post(
                "/about-us/admin/entries",
                json={
                    "body": f"# {title}\n\n**Markdown**",
                    "body_en": f"# {title} English\n\n**Markdown**",
                },
            )
            assert response.status_code == 201
            assert response.json()["title_en"] == f"{title} English"
            created_ids.append(response.json()["id"])

        response = await client.put(
            f"/about-us/admin/entries/{created_ids[0]}",
            json={
                "body": "# First updated\n\n- persisted",
                "body_en": "# First updated in English\n\n- persisted in English",
            },
        )
        assert response.status_code == 200
        assert response.json()["title"] == "First updated"
        assert response.json()["title_en"] == "First updated in English"

        content_only = await client.put(
            f"/about-us/admin/entries/{created_ids[0]}",
            json={"body": "# First content-only edit\n\n- persisted"},
        )
        assert content_only.status_code == 200
        assert content_only.json()["title"] == "First content-only edit"
        assert content_only.json()["body_en"] == (
            "# First updated in English\n\n- persisted in English"
        )
        assert content_only.json()["title_en"] == "First updated in English"
        content_only_order = content_only.json()["order_index"]

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        forbidden_reorder = await client.put(
            "/about-us/admin/entries/reorder",
            json={"entry_ids": created_ids},
        )
        assert forbidden_reorder.status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        incomplete_reorder = await client.put(
            "/about-us/admin/entries/reorder",
            json={"entry_ids": created_ids[:1]},
        )
        assert incomplete_reorder.status_code == 409
        duplicate_reorder = await client.put(
            "/about-us/admin/entries/reorder",
            json={"entry_ids": [created_ids[0], created_ids[0]]},
        )
        assert duplicate_reorder.status_code == 409
        reordered = await client.put(
            "/about-us/admin/entries/reorder",
            json={"entry_ids": created_ids},
        )
        assert reordered.status_code == 200

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        entries = (await client.get("/about-us")).json()
        assert [entry["title"] for entry in entries] == [
            "First content-only edit",
            "Second",
        ]
        assert [entry["order_index"] for entry in entries] == [0, 1]
        assert content_only_order == 1
        assert entries[0]["body"] == "# First content-only edit\n\n- persisted"
        assert entries[0]["title_en"] == "First updated in English"
        assert (
            entries[0]["body_en"]
            == "# First updated in English\n\n- persisted in English"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(AboutUsEntry))
            await session.commit()


@pytest.mark.asyncio
async def test_about_us_permanent_delete_requires_admin(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    user = await make_user()
    entry_id = None
    try:
        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        created = await client.post(
            "/about-us/admin/entries",
            json={
                "body": "# Delete me\n\nBody",
                "body_en": "# Delete me in English\n\nBody in English",
            },
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        assert (
            await client.delete(f"/about-us/admin/entries/{entry_id}")
        ).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        deleted = await client.delete(f"/about-us/admin/entries/{entry_id}")
        assert deleted.status_code == 204
        async with session_maker() as session:
            assert await session.get(AboutUsEntry, entry_id) is None
        assert (
            await client.delete(f"/about-us/admin/entries/{entry_id}")
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if entry_id is not None:
            async with session_maker() as session:
                await session.execute(
                    delete(AboutUsEntry).where(AboutUsEntry.id == entry_id)
                )
                await session.commit()
