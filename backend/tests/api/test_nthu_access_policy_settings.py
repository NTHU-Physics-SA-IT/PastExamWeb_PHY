import pytest
from sqlalchemy import delete

from app.main import app
from app.models.models import SystemSetting, UserRoles
from app.services.nthu_access_policy import NTHU_ACCESS_POLICY_SETTING_KEY
from app.utils.auth import get_current_user


PATH = "/settings/nthu-access-policy"


@pytest.mark.asyncio
async def test_admin_reads_default_and_persists_selected_departments(
    client,
    make_user,
    session_maker,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=admin.id,
        is_admin=True,
    )

    try:
        default_response = await client.get(PATH)
        assert default_response.status_code == 200
        default_body = default_response.json()
        assert default_body["mode"] == "all_nthu"
        assert default_body["allowed_department_codes"] == []
        assert default_body["staff_access"] == "none"
        assert default_body["allowed_staff_userids"] == []
        physics = next(
            item for item in default_body["departments"] if item["code"] == "022"
        )
        assert physics["name"] == "物理學系"
        assert physics["college_name"] == "理學院"

        update_response = await client.put(
            PATH,
            json={
                "mode": "selected_departments",
                "allowed_department_codes": ["025", "022", "022"],
                "staff_access": "allowlist",
                "allowed_staff_userids": [" W90001 "],
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["allowed_department_codes"] == ["022", "025"]
        assert update_response.json()["allowed_staff_userids"] == ["W90001"]

        reload_response = await client.get(PATH)
        assert reload_response.status_code == 200
        assert reload_response.json()["mode"] == "selected_departments"
        assert reload_response.json()["allowed_department_codes"] == ["022", "025"]
        assert reload_response.json()["staff_access"] == "allowlist"
        assert reload_response.json()["allowed_staff_userids"] == ["W90001"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(SystemSetting).where(
                    SystemSetting.key == NTHU_ACCESS_POLICY_SETTING_KEY
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_non_admin_cannot_read_or_update_nthu_access_policy(client):
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=1,
        is_admin=False,
    )
    try:
        assert (await client.get(PATH)).status_code == 403
        response = await client.put(
            PATH,
            json={"mode": "all_nthu", "allowed_department_codes": []},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "invalid", "allowed_department_codes": []},
        {"mode": "selected_departments", "allowed_department_codes": []},
        {"mode": "selected_departments", "allowed_department_codes": ["999"]},
    ],
)
async def test_invalid_nthu_access_policy_returns_422(client, payload):
    app.dependency_overrides[get_current_user] = lambda: UserRoles(
        user_id=1,
        is_admin=True,
    )
    try:
        response = await client.put(PATH, json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
