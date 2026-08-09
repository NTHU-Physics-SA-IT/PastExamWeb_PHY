from __future__ import annotations

import hashlib
import re
import secrets

from app.core.config import settings
from app.utils.auth import redis_client


LOGIN_HANDOFF_TTL_SECONDS = settings.OAUTH_HANDOFF_TTL_SECONDS
_KEY_PREFIX = "auth:login-handoff:"
_MAX_CODE_LENGTH = 256
_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,256}\Z")


def _handoff_key(code: str) -> str:
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def create_login_handoff(user_id: int) -> str:
    """Store one short-lived user handoff and return its opaque one-time code."""
    for _ in range(3):
        code = secrets.token_urlsafe(32)
        created = redis_client.set(
            _handoff_key(code),
            user_id,
            ex=LOGIN_HANDOFF_TTL_SECONDS,
            nx=True,
        )
        if created:
            return code
    raise RuntimeError("oauth_handoff_unavailable")


def consume_login_handoff(code: str) -> int | None:
    """Atomically consume a one-time handoff code, returning its user id."""
    if not isinstance(code, str) or not code or len(code) > _MAX_CODE_LENGTH:
        return None
    if _CODE_PATTERN.fullmatch(code) is None:
        return None

    value = redis_client.getdel(_handoff_key(code))
    if value is None:
        return None
    try:
        user_id = int(value)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None
