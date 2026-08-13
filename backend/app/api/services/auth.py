import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.presence import (
    HEARTBEAT_INTERVAL_SECONDS,
    end_presence_session,
    touch_presence_session,
)
from app.core.config import settings
from app.db.session import get_session
from app.models.models import User
from app.services.login_handoff import (
    consume_login_handoff,
    create_login_handoff,
)
from app.services.nthu_dev_mock import (
    consume_nthu_dev_profile,
    create_nthu_dev_code,
    is_nthu_dev_code,
    nthu_dev_mock_is_available,
    public_nthu_dev_profiles,
)
from app.services.nthu_oauth import (
    NthuOAuthBusinessError,
    NthuOAuthProviderError,
    build_nthu_authorize_url,
    fetch_nthu_profile,
    resolve_nthu_user,
)
from app.utils.auth import authenticate_user, blacklist_token, get_current_user
from app.utils.exception_logging import redacted_exc_info
from app.utils.jwt import jwt

router = APIRouter()
logger = logging.getLogger(__name__)
NTHU_OAUTH_STATE_SESSION_KEY = "nthu_oauth_state"


class NthuExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


def _ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _issue_access_token(user: User, *, now: datetime) -> str:
    payload = {
        "uid": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "jti": uuid.uuid4().hex,
        "exp": int(now.timestamp() + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _frontend_callback_url(**query: str) -> str:
    base_url = settings.FRONTEND_URL.rstrip("/")
    return f"{base_url}/login/callback?{urlencode(query)}"


def _no_store_redirect(url: str) -> RedirectResponse:
    return RedirectResponse(
        url=url,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _frontend_oauth_error(code: str) -> RedirectResponse:
    return _no_store_redirect(_frontend_callback_url(error=code))


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_session),
):
    """
    Local login endpoint for users with password authentication
    """
    user = await authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login and heartbeat timestamps
    now_utc = datetime.now(UTC)
    user.last_login = now_utc
    user.last_seen_at = now_utc

    token = _issue_access_token(user, now=now_utc)
    await touch_presence_session(db, user_id=user.id, token=token, now=now_utc)
    await db.commit()

    return {"access_token": token, "token_type": "bearer"}


@router.get("/nthu/login")
async def nthu_login(request: Request):
    state_value = secrets.token_urlsafe(32)
    try:
        authorize_url = build_nthu_authorize_url(state_value)
    except NthuOAuthProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="oauth_provider_unavailable",
        ) from error
    request.session[NTHU_OAUTH_STATE_SESSION_KEY] = state_value
    return _no_store_redirect(authorize_url)


@router.get("/dev/nthu/profiles")
async def nthu_dev_profiles():
    if not nthu_dev_mock_is_available():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {"profiles": public_nthu_dev_profiles()}


@router.get("/dev/nthu/login/{profile_key}")
async def nthu_dev_login(profile_key: str, request: Request):
    if not nthu_dev_mock_is_available():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    state_value = secrets.token_urlsafe(32)
    request.session[NTHU_OAUTH_STATE_SESSION_KEY] = state_value
    try:
        code = create_nthu_dev_code(profile_key)
    except KeyError as error:
        request.session.pop(NTHU_OAUTH_STATE_SESSION_KEY, None)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except NthuOAuthProviderError as error:
        request.session.pop(NTHU_OAUTH_STATE_SESSION_KEY, None)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
    return _no_store_redirect(
        f"/api/auth/nthu/callback?{urlencode({'code': code, 'state': state_value})}"
    )


@router.get("/nthu/callback")
async def nthu_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    stored_state = request.session.pop(NTHU_OAUTH_STATE_SESSION_KEY, None)
    if (
        not state
        or not isinstance(stored_state, str)
        or not hmac.compare_digest(state, stored_state)
    ):
        return _frontend_oauth_error("oauth_state_invalid")
    if not code:
        return _frontend_oauth_error("oauth_login_failed")

    try:
        profile = (
            consume_nthu_dev_profile(code)
            if is_nthu_dev_code(code)
            else await fetch_nthu_profile(code)
        )
        user = await resolve_nthu_user(db, profile)
        await db.commit()
    except NthuOAuthBusinessError as error:
        await db.rollback()
        return _frontend_oauth_error(error.code)
    except NthuOAuthProviderError:
        await db.rollback()
        return _frontend_oauth_error("oauth_login_failed")
    except IntegrityError:
        await db.rollback()
        return _frontend_oauth_error("oauth_identity_conflict")
    except Exception as exc:
        await db.rollback()
        logger.error(
            "Unexpected OAuth callback failure",
            exc_info=redacted_exc_info(exc),
        )
        return _frontend_oauth_error("oauth_login_failed")

    try:
        handoff_code = create_login_handoff(user.id)
    except Exception as exc:
        logger.error(
            "Unexpected login handoff creation failure",
            exc_info=redacted_exc_info(exc),
        )
        return _frontend_oauth_error("oauth_login_failed")
    return _no_store_redirect(_frontend_callback_url(code=handoff_code))


@router.post("/nthu/exchange")
async def exchange_nthu_login(
    payload: NthuExchangeRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    try:
        user_id = consume_login_handoff(payload.code)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="oauth_exchange_unavailable",
        ) from error
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth_exchange_invalid",
        )

    user = await db.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth_exchange_invalid",
        )

    now_utc = datetime.now(UTC)
    token = _issue_access_token(user, now=now_utc)
    user.last_login = now_utc
    user.last_seen_at = now_utc
    await touch_presence_session(db, user_id=user.id, token=token, now=now_utc)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Logout endpoint that blacklists the current token and updates logout time
    """
    # Update user's last logout time
    result = await db.execute(
        select(User).where(User.id == current_user.user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user:
        now_utc = datetime.now(UTC)
        user.last_logout = now_utc
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            await end_presence_session(
                db,
                user_id=user.id,
                token=auth_header.split(" ", 1)[1],
                now=now_utc,
            )
        await db.commit()

    # Blacklist the token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        blacklist_token(token)
    return {"message": "Successfully logged out"}


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Update current user's last_seen_at as a lightweight heartbeat endpoint.
    """
    result = await db.execute(
        select(User).where(User.id == current_user.user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    now_utc = datetime.now(UTC)
    should_update = True
    normalized_last_seen = _ensure_timezone_aware(user.last_seen_at)
    if normalized_last_seen is not None:
        delta_seconds = (now_utc - normalized_last_seen).total_seconds()
        should_update = delta_seconds >= HEARTBEAT_INTERVAL_SECONDS
        if should_update:
            user.last_seen_at = now_utc
        else:
            user.last_seen_at = normalized_last_seen
    else:
        user.last_seen_at = now_utc
        should_update = True

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    await touch_presence_session(
        db,
        user_id=user.id,
        token=auth_header.split(" ", 1)[1],
        now=now_utc,
    )
    await db.commit()

    return {
        "message": "ok",
        "last_seen_at": user.last_seen_at,
        "is_online": True,
    }


@router.post("/record-login")
async def record_login(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Record a successful login completed by the external auth callback."""
    result = await db.execute(
        select(User).where(User.id == current_user.user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    now_utc = datetime.now(UTC)
    user.last_login = now_utc
    user.last_seen_at = now_utc
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token"
        )
    await touch_presence_session(
        db,
        user_id=user.id,
        token=auth_header.split(" ", 1)[1],
        now=now_utc,
    )
    await db.commit()

    return {"last_login": now_utc}
