from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import uuid

import pytest
from sqlmodel import select

from fastapi import HTTPException

from app.main import app
from app.models.models import User, UserPresenceSession, UserRoles
from app.core.config import settings
from app.services.nthu_oauth import NthuProfile
from app.utils.auth import get_current_user
from app.api.services import auth as auth_service

LEGACY_BCRYPT_HASH = "$2b$04$abcdefghijklmnopqrstuOFeWHo6yW/rrUEe9j8D8ueOhu.9wpWwO"


@pytest.mark.asyncio
async def test_local_login_success(client, make_user):
    user = await make_user()

    response = await client.post(
        "/auth/login",
        data={
            "username": user.name,
            "password": user.password,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]


@pytest.mark.asyncio
async def test_local_login_failure(client):
    response = await client.post(
        "/auth/login",
        data={"username": "unknown", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_local_login_supports_password_longer_than_bcrypt_limit(
    client,
    make_user,
):
    password = "密" * 25
    user = await make_user(password=password)

    response = await client.post(
        "/auth/login",
        data={"username": user.name, "password": password},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_local_login_rejects_password_over_server_limit_without_500(
    client,
    make_user,
):
    user = await make_user()

    response = await client.post(
        "/auth/login",
        data={"username": user.name, "password": "a" * 257},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_local_login_upgrades_legacy_bcrypt_hash(
    client,
    make_user,
    session_maker,
):
    user = await make_user(
        password="LegacyPass123!",
        password_hash=LEGACY_BCRYPT_HASH,
    )

    response = await client.post(
        "/auth/login",
        data={"username": user.name, "password": user.password},
    )

    assert response.status_code == 200
    async with session_maker() as session:
        upgraded = await session.get(User, user.id)
        assert upgraded.password_hash.startswith("$bcrypt-sha256$v=2,t=2b,r=12$")


@pytest.mark.asyncio
async def test_nthu_oauth_login_redirect_and_state_validation(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "OAUTH_CLIENT_ID", "nthu-client")
    monkeypatch.setattr(settings, "OAUTH_CLIENT_SECRET", "nthu-secret")
    monkeypatch.setattr(
        settings,
        "OAUTH_AUTHORIZE_URL",
        "https://oauth.ccxp.nthu.edu.tw/v1.1/authorize.php",
    )
    monkeypatch.setattr(
        settings,
        "OAUTH_REDIRECT_URI",
        "https://physarchive.com/api/auth/nthu/callback",
    )

    login_response = await client.get(
        "/auth/nthu/login",
        follow_redirects=False,
    )
    assert login_response.status_code in {302, 307}
    location = login_response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == settings.OAUTH_AUTHORIZE_URL
    )
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [settings.OAUTH_REDIRECT_URI]
    assert query["scope"] == ["uuid inschool userid name email"]
    assert query["state"][0]

    for params in (
        {"code": "provider-code"},
        {"code": "provider-code", "state": "mismatch"},
    ):
        callback_response = await client.get(
            "/auth/nthu/callback",
            params=params,
            follow_redirects=False,
        )
        assert callback_response.status_code in {302, 307}
        assert parse_qs(urlparse(callback_response.headers["location"]).query) == {
            "error": ["oauth_state_invalid"]
        }


@pytest.mark.asyncio
async def test_nthu_callback_creates_user_and_state_is_single_use(
    client,
    monkeypatch,
    session_maker,
):
    suffix = uuid.uuid4().hex[:8]
    profile = NthuProfile(
        uuid=f"nthu-uuid-{suffix}",
        userid=f"student-{suffix}",
        name=f"NTHU User {suffix}",
        email=f"nthu-{suffix}@example.com",
        inschool=True,
    )
    monkeypatch.setattr(settings, "OAUTH_CLIENT_ID", "nthu-client")
    monkeypatch.setattr(settings, "OAUTH_CLIENT_SECRET", "nthu-secret")
    monkeypatch.setattr(
        settings,
        "OAUTH_AUTHORIZE_URL",
        "https://oauth.ccxp.nthu.edu.tw/v1.1/authorize.php",
    )
    monkeypatch.setattr(
        settings,
        "OAUTH_REDIRECT_URI",
        "https://physarchive.com/api/auth/nthu/callback",
    )
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://physarchive.com")

    async def fake_fetch_profile(code):
        assert code == "provider-code"
        return profile

    monkeypatch.setattr(auth_service, "fetch_nthu_profile", fake_fetch_profile)
    monkeypatch.setattr(
        auth_service,
        "create_login_handoff",
        lambda user_id: "one-time-exchange-code",
    )

    login_response = await client.get("/auth/nthu/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    callback_response = await client.get(
        "/auth/nthu/callback",
        params={"code": "provider-code", "state": state},
        follow_redirects=False,
    )
    assert callback_response.status_code in {302, 307}
    assert parse_qs(urlparse(callback_response.headers["location"]).query) == {
        "code": ["one-time-exchange-code"]
    }

    replay_response = await client.get(
        "/auth/nthu/callback",
        params={"code": "provider-code", "state": state},
        follow_redirects=False,
    )
    assert parse_qs(urlparse(replay_response.headers["location"]).query) == {
        "error": ["oauth_state_invalid"]
    }

    async with session_maker() as session:
        user = (
            await session.execute(
                select(User).where(
                    User.oauth_provider == "nthu",
                    User.oauth_sub == profile.uuid,
                )
            )
        ).scalar_one()
        assert user.last_login is None
        await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_nthu_exchange_is_single_use_and_records_login_presence(
    client,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user(is_local=False, password_hash=None)
    consumed = [user.id, None]
    monkeypatch.setattr(
        auth_service,
        "consume_login_handoff",
        lambda code: consumed.pop(0),
    )
    monkeypatch.setattr(
        "app.api.services.auth.jwt.encode",
        lambda payload, key, algorithm: "application-token",
    )

    response = await client.post(
        "/auth/nthu/exchange",
        json={"code": "one-time-code"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "access_token": "application-token",
        "token_type": "bearer",
    }

    replay = await client.post(
        "/auth/nthu/exchange",
        json={"code": "one-time-code"},
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "oauth_exchange_invalid"

    async with session_maker() as session:
        stored = await session.get(User, user.id)
        assert stored.last_login is not None
        assert stored.last_seen_at is not None
        presence = (
            await session.execute(
                select(UserPresenceSession).where(
                    UserPresenceSession.user_id == user.id
                )
            )
        ).scalar_one()
        assert presence.last_seen_at is not None


@pytest.mark.asyncio
async def test_nthu_exchange_rejects_malformed_and_unknown_codes(client, monkeypatch):
    monkeypatch.setattr(auth_service, "consume_login_handoff", lambda code: None)

    for payload in ({}, {"code": ""}, {"code": "unknown-code"}):
        response = await client.post("/auth/nthu/exchange", json=payload)
        assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_logout_updates_last_logout_and_blacklists(
    client,
    make_user,
    session_maker,
    monkeypatch,
):
    user = await make_user()
    captured_tokens: list[str] = []

    def fake_blacklist(token: str):
        captured_tokens.append(token)

    async def fake_get_current_user():
        return UserRoles(user_id=user.id, is_admin=False)

    monkeypatch.setattr(
        "app.api.services.auth.blacklist_token",
        fake_blacklist,
    )
    app.dependency_overrides[get_current_user] = fake_get_current_user

    try:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer token-123"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"
        assert captured_tokens == ["token-123"]

        async with session_maker() as session:
            refreshed = await session.get(User, user.id)
            assert refreshed.last_logout is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_login_direct_returns_token(
    monkeypatch,
    make_user,
    session_maker,
):
    user = await make_user()
    captured = {}

    def fake_encode(payload, key, algorithm):
        captured["payload"] = payload
        return "fake-token"

    monkeypatch.setattr("app.api.services.auth.jwt.encode", fake_encode)

    async with session_maker() as session:
        response = await auth_service.login(
            form_data=SimpleNamespace(
                username=user.name,
                password=user.password,
            ),
            db=session,
        )
        assert response == {
            "access_token": "fake-token",
            "token_type": "bearer",
        }

    async with session_maker() as verify_session:
        refreshed = await verify_session.get(User, user.id)
        assert refreshed.last_login is not None
        assert captured["payload"]["uid"] == user.id


@pytest.mark.asyncio
async def test_login_direct_rejects_unknown_user(session_maker):
    async with session_maker() as session:
        with pytest.raises(HTTPException) as exc:
            await auth_service.login(
                form_data=SimpleNamespace(
                    username="missing",
                    password="nope",
                ),
                db=session,
            )
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_direct_without_header(monkeypatch, session_maker):
    user = User(
        name="logout-direct",
        email="logout-direct@example.com",
        is_admin=False,
        is_local=True,
    )
    async with session_maker() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)

    fake_request = SimpleNamespace(headers={})
    calls = []
    monkeypatch.setattr(
        "app.api.services.auth.blacklist_token",
        lambda token: calls.append(token),
    )

    async with session_maker() as session:
        result = await auth_service.logout(
            request=fake_request,
            current_user=UserRoles(user_id=user.id, is_admin=False),
            db=session,
        )
        assert result == {"message": "Successfully logged out"}

    async with session_maker() as session:
        refreshed = await session.get(User, user.id)
        assert refreshed.last_logout is not None
        await session.delete(refreshed)
        await session.commit()

    assert calls == []
