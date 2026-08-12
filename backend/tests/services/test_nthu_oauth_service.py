from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.config import settings
from app.models.models import SystemSetting, User
from app.services.nthu_access_policy import NTHU_ACCESS_POLICY_SETTING_KEY
from app.services.nthu_oauth import (
    NTHU_APPROVED_SCOPES,
    NthuOAuthBusinessError,
    NthuOAuthProviderError,
    NthuProfile,
    build_nthu_authorize_url,
    fetch_nthu_profile,
    resolve_nthu_user,
)


def _profile(**overrides) -> NthuProfile:
    values = {
        "uuid": f"nthu-{uuid.uuid4().hex}",
        "userid": "student-id",
        "name": f"NTHU User {uuid.uuid4().hex[:8]}",
        "email": f"nthu-{uuid.uuid4().hex[:8]}@example.com",
        "inschool": True,
    }
    values.update(overrides)
    return NthuProfile(**values)


@pytest_asyncio.fixture(autouse=True)
async def _clear_nthu_access_policy(session_maker):
    async with session_maker() as session:
        await session.execute(
            delete(SystemSetting).where(
                SystemSetting.key == NTHU_ACCESS_POLICY_SETTING_KEY
            )
        )
        await session.commit()
    yield
    async with session_maker() as session:
        await session.execute(
            delete(SystemSetting).where(
                SystemSetting.key == NTHU_ACCESS_POLICY_SETTING_KEY
            )
        )
        await session.commit()


def _configure_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings,
        "OAUTH_AUTHORIZE_URL",
        "https://oauth.ccxp.nthu.edu.tw/v1.1/authorize.php",
    )
    monkeypatch.setattr(
        settings,
        "OAUTH_TOKEN_URL",
        "https://oauth.ccxp.nthu.edu.tw/v1.1/token.php",
    )
    monkeypatch.setattr(
        settings,
        "OAUTH_RESOURCE_URL",
        "https://oauth.ccxp.nthu.edu.tw/v1.1/resource.php",
    )
    monkeypatch.setattr(
        settings,
        "OAUTH_REDIRECT_URI",
        "https://physarchive.com/api/auth/nthu/callback",
    )


def test_authorize_redirect_uses_only_the_approved_nthu_contract(monkeypatch):
    _configure_provider(monkeypatch)

    authorize_url = build_nthu_authorize_url("state-value")
    parsed = urlparse(authorize_url)
    query = parse_qs(parsed.query)

    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == settings.OAUTH_AUTHORIZE_URL
    )
    assert query == {
        "client_id": ["client-id"],
        "response_type": ["code"],
        "redirect_uri": ["https://physarchive.com/api/auth/nthu/callback"],
        "scope": [" ".join(NTHU_APPROVED_SCOPES)],
        "state": ["state-value"],
    }
    assert "cid" not in query["scope"][0].split()
    assert "lmsid" not in query["scope"][0].split()


@pytest.mark.asyncio
async def test_fetch_nthu_profile_exchanges_code_and_uses_bearer_resource(monkeypatch):
    _configure_provider(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL(settings.OAUTH_TOKEN_URL):
            form = parse_qs(request.content.decode())
            assert form == {
                "client_id": ["client-id"],
                "client_secret": ["client-secret"],
                "grant_type": ["authorization_code"],
                "code": ["provider-code"],
                "redirect_uri": [settings.OAUTH_REDIRECT_URI],
            }
            return httpx.Response(200, json={"access_token": "provider-access-token"})
        assert request.url == httpx.URL(settings.OAUTH_RESOURCE_URL)
        assert request.headers["Authorization"] == "Bearer provider-access-token"
        return httpx.Response(
            200,
            json={
                "success": True,
                "uuid": "stable-uuid",
                "userid": "student-id",
                "name": "清華學生",
                "email": "student@example.com",
                "inschool": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profile = await fetch_nthu_profile("provider-code", client=client)

    assert profile == NthuProfile(
        uuid="stable-uuid",
        userid="student-id",
        name="清華學生",
        email="student@example.com",
        inschool=True,
    )
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_fetch_nthu_profile_accepts_missing_userid(monkeypatch):
    _configure_provider(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(settings.OAUTH_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "access-token"})
        return httpx.Response(
            200,
            json={
                "success": True,
                "uuid": "stable-uuid-without-userid",
                "name": "NTHU User",
                "email": "student@example.com",
                "inschool": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profile = await fetch_nthu_profile("provider-code", client=client)

    assert profile.userid is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_response",
    [
        httpx.Response(500, json={"error": "server_error"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"access_token": ""}),
        httpx.Response(
            200,
            json={"success": False, "access_token": "must-not-be-used"},
        ),
    ],
)
async def test_fetch_nthu_profile_fails_closed_for_token_errors(
    monkeypatch,
    token_response,
):
    _configure_provider(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: token_response)
    ) as client:
        with pytest.raises(NthuOAuthProviderError, match="oauth_provider_failed"):
            await fetch_nthu_profile("provider-code", client=client)


@pytest.mark.asyncio
async def test_fetch_nthu_profile_fails_closed_for_token_network_error(monkeypatch):
    _configure_provider(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NthuOAuthProviderError, match="oauth_provider_failed"):
            await fetch_nthu_profile("provider-code", client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_payload",
    [
        {"success": False},
        {
            "success": True,
            "userid": "u",
            "name": "N",
            "email": "n@example.com",
            "inschool": True,
        },
        {
            "success": True,
            "uuid": "",
            "userid": "u",
            "name": "N",
            "email": "n@example.com",
            "inschool": True,
        },
        {
            "success": True,
            "uuid": 123,
            "userid": "u",
            "name": "N",
            "email": "n@example.com",
            "inschool": True,
        },
        {
            "success": True,
            "uuid": "id",
            "userid": "u",
            "name": "",
            "email": "n@example.com",
            "inschool": True,
        },
        {
            "success": True,
            "uuid": "id",
            "userid": "u",
            "name": "N",
            "email": "",
            "inschool": True,
        },
        {
            "success": True,
            "uuid": "id",
            "userid": "u",
            "name": "N",
            "email": "n@example.com",
            "inschool": "true",
        },
    ],
)
async def test_fetch_nthu_profile_fails_closed_for_invalid_resource_payloads(
    monkeypatch,
    resource_payload,
):
    _configure_provider(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(settings.OAUTH_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "access-token"})
        return httpx.Response(200, json=resource_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NthuOAuthProviderError, match="oauth_provider_failed"):
            await fetch_nthu_profile("provider-code", client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "malformed", "network"])
async def test_fetch_nthu_profile_fails_closed_for_resource_transport_errors(
    monkeypatch,
    failure,
):
    _configure_provider(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(settings.OAUTH_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "access-token"})
        if failure == "network":
            raise httpx.ConnectError("unavailable", request=request)
        if failure == "malformed":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(503, json={"success": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NthuOAuthProviderError, match="oauth_provider_failed"):
            await fetch_nthu_profile("provider-code", client=client)


@pytest.mark.asyncio
async def test_ineligible_profile_is_denied_without_account_mutation(session_maker):
    profile = _profile(inschool=False)

    async with session_maker() as session:
        before_user_ids = tuple(
            (await session.execute(select(User.id).order_by(User.id))).scalars()
        )
        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, profile)
        assert exc_info.value.code == "oauth_not_in_school"
        after_user_ids = tuple(
            (await session.execute(select(User.id).order_by(User.id))).scalars()
        )
        assert after_user_ids == before_user_ids


@pytest.mark.asyncio
async def test_first_and_repeat_login_use_nthu_uuid_and_preserve_nickname(
    session_maker,
):
    first = _profile()
    async with session_maker() as session:
        user = await resolve_nthu_user(session, first)
        await session.commit()
        user_id = user.id

    assert user.oauth_provider == "nthu"
    assert user.oauth_sub == first.uuid
    assert user.student_id == first.userid
    assert user.email == first.email
    assert user.name == first.name
    assert user.nickname == first.name
    assert user.is_local is False

    async with session_maker() as session:
        stored = await session.get(User, user_id)
        stored.nickname = "自訂暱稱"
        await session.commit()

    updated = _profile(
        uuid=first.uuid,
        userid="112022123",
        name=f"Updated {uuid.uuid4().hex[:8]}",
        email=f"updated-{uuid.uuid4().hex[:8]}@example.com",
    )
    async with session_maker() as session:
        repeated = await resolve_nthu_user(session, updated)
        await session.commit()

    assert repeated.id == user_id
    assert repeated.name == updated.name
    assert repeated.email == updated.email
    assert repeated.nickname == "自訂暱稱"
    assert repeated.student_id == updated.userid


@pytest.mark.asyncio
@pytest.mark.parametrize("userid", ["112023123", "X1106099", None])
async def test_all_nthu_allows_any_in_school_affiliation(session_maker, userid):
    profile = _profile(userid=userid)

    async with session_maker() as session:
        user = await resolve_nthu_user(session, profile)
        await session.commit()

        assert user.oauth_sub == profile.uuid
        assert user.student_id == userid


@pytest.mark.asyncio
@pytest.mark.parametrize("userid", ["112023123", "X1106099", None])
async def test_selected_department_denies_before_user_mutation(
    session_maker,
    userid,
):
    profile = _profile(userid=userid)
    async with session_maker() as session:
        session.add(
            SystemSetting(
                key=NTHU_ACCESS_POLICY_SETTING_KEY,
                value={
                    "mode": "selected_departments",
                    "allowed_department_codes": ["022"],
                },
            )
        )
        await session.commit()
        before_user_ids = tuple(
            (await session.execute(select(User.id).order_by(User.id))).scalars()
        )

        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, profile)

        assert exc_info.value.code == "oauth_department_not_allowed"
        after_user_ids = tuple(
            (await session.execute(select(User.id).order_by(User.id))).scalars()
        )
        assert after_user_ids == before_user_ids


@pytest.mark.asyncio
async def test_existing_user_is_preserved_when_policy_later_denies(session_maker):
    profile = _profile(userid="112023123")
    async with session_maker() as session:
        user = await resolve_nthu_user(session, profile)
        await session.commit()
        user_id = user.id
        original = (
            user.oauth_sub,
            user.student_id,
            user.name,
            user.email,
            user.deleted_at,
        )

    async with session_maker() as session:
        session.add(
            SystemSetting(
                key=NTHU_ACCESS_POLICY_SETTING_KEY,
                value={
                    "mode": "selected_departments",
                    "allowed_department_codes": ["022"],
                },
            )
        )
        await session.commit()

        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, profile)
        assert exc_info.value.code == "oauth_department_not_allowed"
        await session.rollback()

    async with session_maker() as session:
        stored = await session.get(User, user_id)
        assert stored is not None
        assert (
            stored.oauth_sub,
            stored.student_id,
            stored.name,
            stored.email,
            stored.deleted_at,
        ) == original


@pytest.mark.asyncio
async def test_selected_department_allows_and_persists_physics_student(session_maker):
    profile = _profile(userid="112022123")
    async with session_maker() as session:
        session.add(
            SystemSetting(
                key=NTHU_ACCESS_POLICY_SETTING_KEY,
                value={
                    "mode": "selected_departments",
                    "allowed_department_codes": ["022"],
                },
            )
        )
        await session.commit()

        user = await resolve_nthu_user(session, profile)
        await session.commit()

        assert user.student_id == "112022123"
        assert user.oauth_sub == profile.uuid


@pytest.mark.asyncio
async def test_new_identity_email_collision_requires_explicit_linking(
    session_maker,
    make_user,
):
    existing = await make_user()
    profile = _profile(email=existing.email)

    async with session_maker() as session:
        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, profile)
        assert exc_info.value.code == "oauth_account_link_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("collision_field", ["name", "email"])
async def test_repeat_profile_collision_fails_without_overwriting_user(
    session_maker,
    make_user,
    collision_field,
):
    collision = await make_user()
    first = _profile()
    async with session_maker() as session:
        user = await resolve_nthu_user(session, first)
        await session.commit()
        user_id = user.id

    overrides = {
        "uuid": first.uuid,
        collision_field: getattr(collision, collision_field),
    }
    changed = _profile(**overrides)
    async with session_maker() as session:
        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, changed)
        assert exc_info.value.code == "oauth_profile_conflict"
        await session.rollback()

    async with session_maker() as session:
        stored = await session.get(User, user_id)
        assert stored.name == first.name
        assert stored.email == first.email


@pytest.mark.asyncio
async def test_deleted_nthu_identity_is_denied_without_restore(session_maker):
    first = _profile()
    async with session_maker() as session:
        user = await resolve_nthu_user(session, first)
        await session.flush()
        user.deleted_at = datetime.now(timezone.utc)
        await session.commit()
        user_id = user.id

    async with session_maker() as session:
        with pytest.raises(NthuOAuthBusinessError) as exc_info:
            await resolve_nthu_user(session, first)
        assert exc_info.value.code == "oauth_account_deleted"
        await session.rollback()

    async with session_maker() as session:
        stored = await session.get(User, user_id)
        assert stored.deleted_at is not None
