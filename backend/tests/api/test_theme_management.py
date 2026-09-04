import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import delete
from sqlmodel import select
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.services import theme_management
from app.db.session import get_session
from app.main import app
from app.models.models import FestivalThemeRead, SystemSetting, UserRoles
from app.services import theme_management as theme_management_service
from app.services.theme_management import (
    ACTIVE_THEME_SETTING_KEY,
    FESTIVAL_THEME_CATALOG_SETTING_KEY,
)
from app.utils.auth import get_current_user


def _override_user(*, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=1, is_admin=is_admin)

    return _get_current_user


def _dependency_calls(dependant):
    calls = set()
    for dependency in dependant.dependencies:
        calls.add(dependency.call)
        calls.update(_dependency_calls(dependency))
    return calls


@pytest.mark.asyncio
async def test_admin_theme_management_returns_registered_capabilities(
    client: AsyncClient,
):
    app.dependency_overrides[get_current_user] = _override_user(is_admin=True)
    try:
        response = await client.get("/admin/theme-management")
        assert response.status_code == 200
        assert response.json() == {
            "general_theme": {
                "active": True,
                "user_selectable": True,
                "supported_modes": ["light", "dark"],
            },
            "festival_theme": {
                "active": None,
                "themes": [
                    {
                        "id": "christmas",
                        "name": "聖誕模式",
                        "name_en": "Christmas Theme",
                        "description": "這是專門為聖誕節準備的主題，只會在聖誕節使用。",
                        "description_en": "A theme prepared especially for Christmas and used only during Christmas.",
                        "supports_color_modes": False,
                        "starts_at": None,
                        "ends_at": None,
                    }
                ],
            },
        }

        route = next(
            route
            for route in theme_management.router.routes
            if isinstance(route, APIRoute) and route.path == "/admin/theme-management"
        )
        assert route.methods == {"GET"}
        assert get_session in _dependency_calls(route.dependant)

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            mutation = await client.request(method, "/admin/theme-management")
            assert mutation.status_code == 405
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_admin_theme_management_rejects_non_admin_users(
    client: AsyncClient,
):
    app.dependency_overrides[get_current_user] = _override_user(is_admin=False)
    try:
        response = await client.get("/admin/theme-management")
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin access required"}
        activation = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "spring"},
        )
        assert activation.status_code == 403
        update = await client.patch(
            "/admin/theme-management/themes/christmas",
            json={"name": "不可更新"},
        )
        assert update.status_code == 403
        deletion = await client.delete("/admin/theme-management/themes/christmas")
        assert deletion.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_default_general_activation_is_a_noop_without_a_setting():
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    result = await theme_management_service.activate_theme(
        db,
        theme_id="general",
        updated_by_id=1,
    )

    assert result.general_theme.active is True
    assert result.festival_theme.active is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_activation_persists_exactly_one_registered_theme(
    client: AsyncClient,
    make_user,
    monkeypatch,
    session_maker,
):
    admin = await make_user(is_admin=True)
    themes = (
        FestivalThemeRead(
            id="spring",
            name="春日",
            name_en="Spring",
            description="春季節日主題",
            description_en="Spring festival theme",
        ),
        FestivalThemeRead(
            id="mid_autumn",
            name="中秋",
            name_en="Mid-Autumn",
            description="中秋節日主題",
            description_en="Mid-Autumn festival theme",
        ),
    )
    monkeypatch.setattr(theme_management_service, "REGISTERED_FESTIVAL_THEMES", themes)
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=admin.id,
        is_admin=True,
    )

    try:
        initial = await client.get("/admin/theme-management")
        assert initial.status_code == 200
        assert initial.json()["general_theme"]["active"] is True
        assert initial.json()["festival_theme"] == {
            "active": None,
            "themes": [theme.model_dump() for theme in themes],
        }

        spring = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "spring"},
        )
        assert spring.status_code == 200
        assert spring.json()["general_theme"]["active"] is False
        assert spring.json()["festival_theme"]["active"] == "spring"

        async with session_maker() as session:
            stored = await session.scalar(
                select(SystemSetting).where(
                    SystemSetting.key == ACTIVE_THEME_SETTING_KEY
                )
            )
            assert stored is not None
            first_updated_at = stored.updated_at
            assert stored.value == "spring"

        same_target = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "spring"},
        )
        assert same_target.status_code == 200
        async with session_maker() as session:
            stored = await session.scalar(
                select(SystemSetting).where(
                    SystemSetting.key == ACTIVE_THEME_SETTING_KEY
                )
            )
            assert stored is not None
            assert stored.updated_at == first_updated_at

        general = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "general"},
        )
        assert general.status_code == 200
        assert general.json()["general_theme"]["active"] is True
        assert general.json()["festival_theme"]["active"] is None

        async with session_maker() as session:
            stored = await session.scalar(
                select(SystemSetting).where(
                    SystemSetting.key == ACTIVE_THEME_SETTING_KEY
                )
            )
            assert stored is not None
            assert stored.value == "general"

        mid_autumn = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "mid_autumn"},
        )
        assert mid_autumn.status_code == 200
        assert mid_autumn.json()["general_theme"]["active"] is False
        assert mid_autumn.json()["festival_theme"]["active"] == "mid_autumn"

        unknown = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "unknown"},
        )
        assert unknown.status_code == 404
        assert unknown.json() == {"detail": "Theme not found"}

        reloaded = await client.get("/admin/theme-management")
        assert reloaded.json()["festival_theme"]["active"] == "mid_autumn"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key == ACTIVE_THEME_SETTING_KEY
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_public_active_theme_is_guest_readable_and_exposes_only_active_id(
    client: AsyncClient,
    make_user,
    session_maker,
):
    initial = await client.get("/theme-management/active-theme")
    assert initial.status_code == 200
    assert initial.json() == {"active_theme": "general"}

    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=admin.id,
        is_admin=True,
    )
    try:
        activated = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "christmas"},
        )
        assert activated.status_code == 200

        public = await client.get("/theme-management/active-theme")
        assert public.status_code == 200
        assert public.json() == {"active_theme": "christmas"}
        assert set(public.json()) == {"active_theme"}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key.in_(
                        [ACTIVE_THEME_SETTING_KEY, FESTIVAL_THEME_CATALOG_SETTING_KEY]
                    )
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_can_update_and_delete_inactive_christmas_catalog_entry(
    client: AsyncClient,
    make_user,
    session_maker,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=admin.id,
        is_admin=True,
    )
    try:
        updated = await client.patch(
            "/admin/theme-management/themes/christmas",
            json={
                "name": "聖誕模式",
                "name_en": "Christmas Theme",
                "description": "這是專門為聖誕節準備的主題，只會在聖誕節使用。",
                "description_en": "Christmas presentation",
                "starts_at": "2026-12-24T00:00:00Z",
                "ends_at": "2026-12-26T00:00:00Z",
            },
        )
        assert updated.status_code == 200
        christmas = updated.json()["festival_theme"]["themes"][0]
        assert christmas["id"] == "christmas"
        assert christmas["supports_color_modes"] is False
        assert christmas["starts_at"] == "2026-12-24T00:00:00Z"
        assert christmas["ends_at"] == "2026-12-26T00:00:00Z"

        deleted = await client.delete("/admin/theme-management/themes/christmas")
        assert deleted.status_code == 200
        assert deleted.json()["festival_theme"]["themes"] == []

        reloaded = await client.get("/admin/theme-management")
        assert reloaded.status_code == 200
        assert reloaded.json()["festival_theme"]["themes"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key.in_(
                        [ACTIVE_THEME_SETTING_KEY, FESTIVAL_THEME_CATALOG_SETTING_KEY]
                    )
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_admin_cannot_delete_active_christmas_theme(
    client: AsyncClient,
    make_user,
    session_maker,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=admin.id,
        is_admin=True,
    )
    try:
        activated = await client.patch(
            "/admin/theme-management/active-theme",
            json={"theme_id": "christmas"},
        )
        assert activated.status_code == 200

        deletion = await client.delete("/admin/theme-management/themes/christmas")
        assert deletion.status_code == 409
        assert deletion.json() == {"detail": "Deactivate theme before deletion"}

        reloaded = await client.get("/admin/theme-management")
        assert reloaded.json()["festival_theme"]["active"] == "christmas"
        assert [theme["id"] for theme in reloaded.json()["festival_theme"]["themes"]] == [
            "christmas"
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key.in_(
                        [ACTIVE_THEME_SETTING_KEY, FESTIVAL_THEME_CATALOG_SETTING_KEY]
                    )
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_activation_rolls_back_when_the_setting_write_fails(monkeypatch):
    theme = FestivalThemeRead(
        id="spring",
        name="春日",
        name_en="Spring",
        description="春季節日主題",
        description_en="Spring festival theme",
    )
    monkeypatch.setattr(
        theme_management_service,
        "REGISTERED_FESTIVAL_THEMES",
        (theme,),
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        execute=AsyncMock(side_effect=RuntimeError("write failed")),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await theme_management_service.activate_theme(
            db,
            theme_id="spring",
            updated_by_id=1,
        )

    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once_with()
