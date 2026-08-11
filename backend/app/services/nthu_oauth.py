from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.models import User
from app.services.nthu_access_policy import (
    NthuAccessPolicyValidationError,
    ensure_profile_matches_access_policy,
    load_nthu_access_policy,
)


NTHU_PROVIDER = "nthu"
NTHU_APPROVED_SCOPES = ("uuid", "inschool", "userid", "name", "email")
_MAX_IDENTITY_LENGTH = 255


class NthuOAuthProviderError(Exception):
    code = "oauth_provider_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


class NthuOAuthBusinessError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NthuProfile:
    uuid: str
    userid: str | None
    name: str
    email: str
    inschool: bool


def validate_nthu_oauth_configuration() -> None:
    required = (
        settings.OAUTH_CLIENT_ID,
        settings.OAUTH_CLIENT_SECRET,
        settings.OAUTH_AUTHORIZE_URL,
        settings.OAUTH_TOKEN_URL,
        settings.OAUTH_RESOURCE_URL,
        settings.OAUTH_REDIRECT_URI,
    )
    if any(not isinstance(value, str) or not value.strip() for value in required):
        raise NthuOAuthProviderError()


def build_nthu_authorize_url(state: str) -> str:
    validate_nthu_oauth_configuration()
    query = urlencode(
        {
            "client_id": settings.OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "scope": " ".join(NTHU_APPROVED_SCOPES),
            "state": state,
        }
    )
    return f"{settings.OAUTH_AUTHORIZE_URL}?{query}"


def _required_opaque(value: object) -> str:
    if not isinstance(value, str):
        raise NthuOAuthProviderError()
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_IDENTITY_LENGTH
        or any(character.isspace() or ord(character) < 32 for character in normalized)
    ):
        raise NthuOAuthProviderError()
    return normalized


def _optional_opaque(value: object) -> str | None:
    if value is None:
        return None
    return _required_opaque(value)


def _required_text(value: object) -> str:
    if not isinstance(value, str):
        raise NthuOAuthProviderError()
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_IDENTITY_LENGTH:
        raise NthuOAuthProviderError()
    return normalized


def _profile_from_resource(payload: object) -> NthuProfile:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise NthuOAuthProviderError()
    inschool = payload.get("inschool")
    if not isinstance(inschool, bool):
        raise NthuOAuthProviderError()

    uuid_value = _required_opaque(payload.get("uuid"))
    userid = _optional_opaque(payload.get("userid"))
    name = _required_text(payload.get("name"))
    email = _required_opaque(payload.get("email"))
    if "@" not in email:
        raise NthuOAuthProviderError()
    return NthuProfile(
        uuid=uuid_value,
        userid=userid,
        name=name,
        email=email,
        inschool=inschool,
    )


async def fetch_nthu_profile(
    code: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> NthuProfile:
    validate_nthu_oauth_configuration()
    if not isinstance(code, str) or not code.strip() or len(code) > 2048:
        raise NthuOAuthProviderError()

    owned_client = client is None
    if client is None:
        total_timeout = settings.OAUTH_HTTP_TIMEOUT_SECONDS
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(total_timeout, connect=min(5.0, total_timeout))
        )

    try:
        try:
            token_response = await client.post(
                settings.OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.OAUTH_CLIENT_ID,
                    "client_secret": settings.OAUTH_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.OAUTH_REDIRECT_URI,
                },
            )
        except httpx.RequestError as error:
            raise NthuOAuthProviderError() from error
        if token_response.status_code != 200:
            raise NthuOAuthProviderError()
        try:
            token_payload = token_response.json()
        except ValueError as error:
            raise NthuOAuthProviderError() from error
        if not isinstance(token_payload, dict):
            raise NthuOAuthProviderError()
        if token_payload.get("success") is False:
            raise NthuOAuthProviderError()
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise NthuOAuthProviderError()

        try:
            resource_response = await client.get(
                settings.OAUTH_RESOURCE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.RequestError as error:
            raise NthuOAuthProviderError() from error
        if resource_response.status_code != 200:
            raise NthuOAuthProviderError()
        try:
            resource_payload = resource_response.json()
        except ValueError as error:
            raise NthuOAuthProviderError() from error
        return _profile_from_resource(resource_payload)
    finally:
        if owned_client:
            await client.aclose()


async def _find_collision(
    db: AsyncSession,
    *,
    field,
    value: str,
    excluding_user_id: int | None = None,
) -> User | None:
    statement = select(User).where(field == value)
    if excluding_user_id is not None:
        statement = statement.where(User.id != excluding_user_id)
    return (await db.execute(statement.limit(1))).scalar_one_or_none()


async def resolve_nthu_user(db: AsyncSession, profile: NthuProfile) -> User:
    """Resolve and synchronize the NTHU identity without committing."""
    try:
        policy = await load_nthu_access_policy(db)
    except NthuAccessPolicyValidationError as error:
        raise NthuOAuthBusinessError("oauth_login_failed") from error
    ensure_profile_matches_access_policy(profile, policy)
    identity_rows = list(
        (
            await db.execute(
                select(User)
                .where(
                    User.oauth_provider == NTHU_PROVIDER,
                    User.oauth_sub == profile.uuid,
                )
                .limit(2)
            )
        ).scalars()
    )
    if len(identity_rows) > 1:
        raise NthuOAuthBusinessError("oauth_identity_conflict")

    if identity_rows:
        user = identity_rows[0]
        if user.deleted_at is not None:
            raise NthuOAuthBusinessError("oauth_account_deleted")
        email_collision = await _find_collision(
            db,
            field=User.email,
            value=profile.email,
            excluding_user_id=user.id,
        )
        name_collision = await _find_collision(
            db,
            field=User.name,
            value=profile.name,
            excluding_user_id=user.id,
        )
        if email_collision is not None or name_collision is not None:
            raise NthuOAuthBusinessError("oauth_profile_conflict")
        user.email = profile.email
        user.name = profile.name
        user.student_id = profile.userid
        await db.flush()
        return user

    if await _find_collision(db, field=User.email, value=profile.email):
        raise NthuOAuthBusinessError("oauth_account_link_required")
    if await _find_collision(db, field=User.name, value=profile.name):
        raise NthuOAuthBusinessError("oauth_profile_conflict")

    user = User(
        oauth_provider=NTHU_PROVIDER,
        oauth_sub=profile.uuid,
        student_id=profile.userid,
        email=profile.email,
        name=profile.name,
        nickname=profile.name,
        is_local=False,
    )
    db.add(user)
    await db.flush()
    return user
