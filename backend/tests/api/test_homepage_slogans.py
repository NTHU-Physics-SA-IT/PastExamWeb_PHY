import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models.models import HomepageSloganSubmission, UserRoles
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


@pytest.mark.asyncio
async def test_homepage_slogan_submission_moderation_visibility_and_delete(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user(nickname="Slogan Author")
    admin = await make_user(is_admin=True, nickname="Slogan Reviewer")
    created_ids: list[int] = []
    try:
        anonymous = await client.post(
            "/homepage-slogans", json={"content": "Anonymous slogan"}
        )
        assert anonymous.status_code in {401, 403}

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        multiline = await client.post(
            "/homepage-slogans", json={"content": "first\nsecond"}
        )
        assert multiline.status_code == 422
        blank = await client.post("/homepage-slogans", json={"content": "   "})
        assert blank.status_code == 422

        created = await client.post(
            "/homepage-slogans", json={"content": "  A better homepage  "}
        )
        assert created.status_code == 201
        assert created.json() == {
            "id": created.json()["id"],
            "content": "A better homepage",
        }
        slogan_id = created.json()["id"]
        created_ids.append(slogan_id)

        async with session_maker() as session:
            persisted = await session.get(HomepageSloganSubmission, slogan_id)
            assert persisted.status == "pending"
            assert persisted.occurrence_level == "normal"
            assert persisted.submitter_user_id == user.id
            assert persisted.submitter_name_snapshot == "Slogan Author"

        selected = await client.get("/homepage-slogans/selected")
        assert selected.status_code == 200
        assert selected.json() is None

        forbidden_list = await client.get("/homepage-slogans/admin")
        assert forbidden_list.status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        listing = await client.get("/homepage-slogans/admin")
        assert listing.status_code == 200
        assert listing.json()["status_counts"] == {
            "pending": 1,
            "enabled": 0,
            "disabled": 0,
        }
        assert listing.json()["items"][0]["submitter_name"] == "Slogan Author"
        assert listing.json()["items"][0]["reviewer_name"] is None

        invalid_level = await client.patch(
            f"/homepage-slogans/admin/{slogan_id}",
            json={"status": "enabled", "occurrence_level": "always"},
        )
        assert invalid_level.status_code == 422

        enabled = await client.patch(
            f"/homepage-slogans/admin/{slogan_id}",
            json={"status": "enabled", "occurrence_level": "normal"},
        )
        assert enabled.status_code == 200
        enabled_body = enabled.json()
        assert enabled_body["status"] == "enabled"
        assert enabled_body["reviewer_name"] == "Slogan Reviewer"
        assert enabled_body["reviewed_at"] is not None

        selected = await client.get("/homepage-slogans/selected")
        assert selected.json() == {
            "id": slogan_id,
            "content": "A better homepage",
        }
        assert set(selected.json()) == {"id", "content"}

        occurrence_only = await client.patch(
            f"/homepage-slogans/admin/{slogan_id}",
            json={"status": "enabled", "occurrence_level": "super_frequent"},
        )
        assert occurrence_only.status_code == 200
        assert occurrence_only.json()["reviewed_at"] == enabled_body["reviewed_at"]
        assert occurrence_only.json()["reviewer_user_id"] == admin.id

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        second = await client.post(
            "/homepage-slogans", json={"content": "Pending never appears"}
        )
        assert second.status_code == 201
        created_ids.append(second.json()["id"])
        assert (await client.get("/homepage-slogans/selected")).json()["id"] == slogan_id
        assert (
            await client.delete(
                f"/homepage-slogans/admin/{second.json()['id']}"
            )
        ).status_code == 403

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        disabled = await client.patch(
            f"/homepage-slogans/admin/{slogan_id}",
            json={"status": "disabled", "occurrence_level": "super_frequent"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        assert (await client.get("/homepage-slogans/selected")).json() is None

        deleted = await client.delete(
            f"/homepage-slogans/admin/{second.json()['id']}"
        )
        assert deleted.status_code == 204
        created_ids.remove(second.json()["id"])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if created_ids:
                await session.execute(
                    delete(HomepageSloganSubmission).where(
                        HomepageSloganSubmission.id.in_(created_ids)
                    )
                )
                await session.commit()
