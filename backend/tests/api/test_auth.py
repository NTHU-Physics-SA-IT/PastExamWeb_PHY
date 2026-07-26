from types import SimpleNamespace

import pytest

from fastapi import HTTPException

from app.main import app
from app.models.models import User, UserRoles
from app.utils.auth import get_current_user
from app.api.services import auth as auth_service

LEGACY_BCRYPT_HASH = (
    "$2b$04$abcdefghijklmnopqrstuOFeWHo6yW/rrUEe9j8D8ueOhu.9wpWwO"
)


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
async def test_recovery_review_login_only_accepts_review_admin(
    client,
    make_user,
    monkeypatch,
):
    original_user = await make_user(name="recovered-user")
    review_admin = await make_user(name="recovery-review-admin", is_admin=True)
    monkeypatch.setattr(auth_service.settings, "RECOVERY_REVIEW_MODE", True)
    monkeypatch.setattr(
        auth_service.settings,
        "RECOVERY_REVIEW_ADMIN_NAME",
        review_admin.name,
    )

    original_response = await client.post(
        "/auth/login",
        data={"username": original_user.name, "password": original_user.password},
    )
    review_response = await client.post(
        "/auth/login",
        data={"username": review_admin.name, "password": review_admin.password},
    )

    assert original_response.status_code == 401
    assert review_response.status_code == 200


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
async def test_oauth_endpoints_are_not_available(client):
    login_response = await client.get(
        "/auth/oauth/login",
        follow_redirects=False,
    )
    assert login_response.status_code == 404

    callback_response = await client.get(
        "/auth/oauth/callback",
        params={"code": "dummy-code", "state": "dummy-state"},
        follow_redirects=False,
    )
    assert callback_response.status_code == 404


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
