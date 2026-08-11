from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import delete, select

from app.api.services import auth as auth_service
from app.core.config import settings
from app.models.models import SystemSetting, User
from app.services import nthu_dev_mock


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set(self, key, value, *, ex, nx):
        assert 60 <= ex <= 90
        assert nx is True
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def getdel(self, key):
        return self.values.pop(key, None)


POLICIES = {
    "all_nthu": None,
    "selected_022": {
        "mode": "selected_departments",
        "allowed_department_codes": ["022"],
        "staff_access": "none",
        "allowed_staff_userids": [],
    },
    "selected_022_staff": {
        "mode": "selected_departments",
        "allowed_department_codes": ["022"],
        "staff_access": "allowlist",
        "allowed_staff_userids": ["W90001"],
    },
    "staff_only": {
        "mode": "selected_departments",
        "allowed_department_codes": [],
        "staff_access": "allowlist",
        "allowed_staff_userids": ["W90001"],
    },
}

EXPECTED = {
    "all_nthu": {
        "physics",
        "other_department",
        "special_userid",
        "missing_userid",
        "staff_allowed",
        "staff_unlisted",
    },
    "selected_022": {"physics"},
    "selected_022_staff": {"physics", "staff_allowed"},
    "staff_only": {"staff_allowed"},
}


@pytest.fixture(autouse=True)
def enabled_dev_mock(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_ENABLED", True)
    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_TTL_SECONDS", 75)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:8080")
    monkeypatch.setattr(nthu_dev_mock, "redis_client", FakeRedis())


@pytest.mark.asyncio
async def test_dev_profile_catalog_is_gated_and_backend_owned(client):
    response = await client.get("/auth/dev/nthu/profiles")

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert [profile["key"] for profile in profiles] == [
        definition.key for definition in nthu_dev_mock.NTHU_DEV_PROFILES
    ]
    assert all("uuid" not in profile and "email" not in profile for profile in profiles)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_name", POLICIES)
@pytest.mark.parametrize(
    "profile_key", [profile.key for profile in nthu_dev_mock.NTHU_DEV_PROFILES]
)
async def test_dev_login_uses_real_callback_policy_and_user_lifecycle(
    client,
    monkeypatch,
    session_maker,
    policy_name,
    profile_key,
):
    policy = POLICIES[policy_name]
    definition = next(
        profile
        for profile in nthu_dev_mock.NTHU_DEV_PROFILES
        if profile.key == profile_key
    )
    if policy is not None:
        async with session_maker() as session:
            session.add(SystemSetting(key="nthu_access_policy", value=policy))
            await session.commit()

    handoffs: list[int] = []
    monkeypatch.setattr(
        auth_service,
        "create_login_handoff",
        lambda user_id: handoffs.append(user_id) or "opaque-handoff",
    )
    provider_calls: list[str] = []

    async def forbidden_provider(code):
        provider_calls.append(code)
        raise AssertionError("development codes must not call the NTHU provider")

    monkeypatch.setattr(auth_service, "fetch_nthu_profile", forbidden_provider)

    try:
        start = await client.get(
            f"/auth/dev/nthu/login/{profile_key}", follow_redirects=False
        )
        assert start.status_code in {302, 307}
        query = parse_qs(urlparse(start.headers["location"]).query)
        callback = await client.get(
            "/auth/nthu/callback",
            params={"code": query["code"][0], "state": query["state"][0]},
            follow_redirects=False,
        )

        allowed = profile_key in EXPECTED[policy_name]
        callback_query = parse_qs(urlparse(callback.headers["location"]).query)
        async with session_maker() as session:
            user = await session.scalar(
                select(User).where(
                    User.oauth_provider == "nthu",
                    User.oauth_sub == definition.uuid,
                )
            )
            if allowed:
                assert callback_query == {"code": ["opaque-handoff"]}
                assert user is not None
                assert user.is_local is False
                assert user.student_id == definition.userid
                assert handoffs == [user.id]
            else:
                assert "error" in callback_query
                assert user is None
                assert handoffs == []
        assert provider_calls == []
    finally:
        async with session_maker() as session:
            await session.execute(
                delete(User).where(
                    User.oauth_provider == "nthu",
                    User.oauth_sub == definition.uuid,
                )
            )
            await session.execute(
                delete(SystemSetting).where(SystemSetting.key == "nthu_access_policy")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_dev_code_and_oauth_state_are_each_one_time(client, monkeypatch):
    monkeypatch.setattr(auth_service, "create_login_handoff", lambda user_id: "handoff")
    start = await client.get("/auth/dev/nthu/login/physics", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    params = {"code": query["code"][0], "state": query["state"][0]}

    first = await client.get(
        "/auth/nthu/callback", params=params, follow_redirects=False
    )
    second = await client.get(
        "/auth/nthu/callback", params=params, follow_redirects=False
    )

    assert parse_qs(urlparse(first.headers["location"]).query) == {"code": ["handoff"]}
    assert parse_qs(urlparse(second.headers["location"]).query) == {
        "error": ["oauth_state_invalid"]
    }
