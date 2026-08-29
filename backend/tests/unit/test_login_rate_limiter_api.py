from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.services import auth as auth_service
from app.db.session import get_session
from app.services.login_rate_limiter import (
    LoginAdmission,
    LoginRateLimitDenialReason,
    PrincipalResetToken,
)


class FakeLimiter:
    def __init__(self, admission):
        self.admission = admission
        self.admit_calls = []
        self.reset_calls = []

    async def admit(self, **kwargs):
        self.admit_calls.append(kwargs)
        return self.admission

    async def reset_principal(self, token):
        self.reset_calls.append(token)


class FakeSession:
    def __init__(self):
        self.commit = AsyncMock()


@pytest.fixture
def test_app():
    application = FastAPI()
    application.include_router(auth_service.router, prefix="/auth")
    return application


async def post_login(application, limiter, *, username="submitted", password="pw"):
    session = FakeSession()

    async def session_dependency():
        yield session

    application.dependency_overrides[get_session] = session_dependency
    application.dependency_overrides[auth_service.get_login_rate_limiter] = lambda: (
        limiter
    )
    transport = ASGITransport(app=application, client=("2001:db8::10", 43123))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/login", data={"username": username, "password": password}
        )
    return response, session


@pytest.mark.asyncio
@pytest.mark.parametrize("submitted", ["missing-user", "local-user", "oauth-user"])
@pytest.mark.parametrize(
    "reason",
    [
        LoginRateLimitDenialReason.PRINCIPAL,
        LoginRateLimitDenialReason.IP,
        LoginRateLimitDenialReason.BOTH,
    ],
)
async def test_denial_is_account_neutral_and_precedes_authentication(
    test_app, monkeypatch, submitted, reason
):
    limiter = FakeLimiter(
        LoginAdmission(
            admitted=False,
            retry_after_seconds=37,
            denial_reason=reason,
        )
    )
    authenticate = AsyncMock()
    monkeypatch.setattr(auth_service, "authenticate_user", authenticate)
    response, session = await post_login(test_app, limiter, username=submitted)
    assert response.status_code == 429
    assert response.json() == {
        "detail": "Too many login attempts. Please try again later."
    }
    assert response.headers["retry-after"] == "37"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["content-type"].startswith("application/json")
    assert "www-authenticate" not in response.headers
    authenticate.assert_not_awaited()
    session.commit.assert_not_awaited()
    assert limiter.reset_calls == []
    assert limiter.admit_calls == [
        {"principal": submitted, "client_identity": "2001:db8::10"}
    ]


@pytest.mark.asyncio
async def test_admitted_invalid_credentials_keep_existing_401_contract(
    test_app, monkeypatch
):
    limiter = FakeLimiter(LoginAdmission(admitted=True))
    authenticate = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_service, "authenticate_user", authenticate)
    response, _ = await post_login(test_app, limiter)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    authenticate.assert_awaited_once()
    assert limiter.reset_calls == []


@pytest.mark.asyncio
async def test_success_resets_only_the_principal_generation(test_app, monkeypatch):
    token = PrincipalResetToken("principal-count", "principal-block", "a" * 32, 3)
    limiter = FakeLimiter(LoginAdmission(admitted=True, principal_reset_token=token))
    user = SimpleNamespace(
        id=7,
        email="local@example.invalid",
        name="local-user",
        is_admin=False,
        last_login=None,
        last_seen_at=None,
    )
    monkeypatch.setattr(auth_service, "authenticate_user", AsyncMock(return_value=user))
    monkeypatch.setattr(auth_service, "_issue_access_token", lambda *_a, **_k: "jwt")
    touch_presence = AsyncMock()
    monkeypatch.setattr(auth_service, "touch_presence_session", touch_presence)
    response, session = await post_login(test_app, limiter, username="local-user")
    assert response.status_code == 200
    assert response.json() == {"access_token": "jwt", "token_type": "bearer"}
    assert limiter.reset_calls == [token]
    touch_presence.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_form_remains_422_and_consumes_no_budget(test_app):
    limiter = FakeLimiter(LoginAdmission(admitted=True))
    test_app.dependency_overrides[auth_service.get_login_rate_limiter] = lambda: limiter
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/login", data={"username": "missing-password"}
        )
    assert response.status_code == 422
    assert limiter.admit_calls == []
