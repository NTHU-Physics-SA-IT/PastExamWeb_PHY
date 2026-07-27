from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.models import User
from app.api.services.presence import (
    HEARTBEAT_INTERVAL_SECONDS,
    end_presence_session,
    touch_presence_session,
)
from app.utils.auth import authenticate_user, blacklist_token, get_current_user
from app.utils.jwt import jwt

router = APIRouter()


def _ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
    now_utc = datetime.now(timezone.utc)
    user.last_login = now_utc
    user.last_seen_at = now_utc

    payload = {
        "uid": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "jti": uuid.uuid4().hex,
        "exp": int(
            datetime.now(timezone.utc).timestamp()
            + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        ),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    await touch_presence_session(db, user_id=user.id, token=token, now=now_utc)
    await db.commit()

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
        now_utc = datetime.now(timezone.utc)
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

    now_utc = datetime.now(timezone.utc)
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

    now_utc = datetime.now(timezone.utc)
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
