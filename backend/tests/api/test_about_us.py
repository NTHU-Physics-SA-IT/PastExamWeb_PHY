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
                json={"title": "Forbidden", "body": "Nope"},
            )
        ).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        missing_english = await client.post(
            "/about-us/admin/entries",
            json={"title": "Missing English", "body": "Missing English body"},
        )
        assert missing_english.status_code == 422
        for title in ("First", "Second"):
            response = await client.post(
                "/about-us/admin/entries",
                json={
                    "title": title,
                    "body": f"# {title}\n\n**Markdown**",
                    "title_en": f"{title} English",
                    "body_en": f"# {title} English\n\n**Markdown**",
                },
            )
            assert response.status_code == 201
            assert response.json()["title_en"] == f"{title} English"
            created_ids.append(response.json()["id"])

        response = await client.put(
            f"/about-us/admin/entries/{created_ids[0]}",
            json={
                "title": "First updated",
                "body": "- persisted",
                "title_en": "First updated in English",
                "body_en": "- persisted in English",
            },
        )
        assert response.status_code == 200
        assert response.json()["body_en"] == "- persisted in English"

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        entries = (await client.get("/about-us")).json()
        assert [entry["title"] for entry in entries] == ["First updated", "Second"]
        assert entries[0]["body"] == "- persisted"
        assert entries[0]["title_en"] == "First updated in English"
        assert entries[0]["body_en"] == "- persisted in English"
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
                "title": "Delete me",
                "body": "Body",
                "title_en": "Delete me in English",
                "body_en": "Body in English",
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
