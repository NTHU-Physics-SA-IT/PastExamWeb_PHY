from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.utils.auth import redis_client

WS_TICKET_TTL_SECONDS = 30
WS_TICKET_PURPOSE = "archive-discussion-ws"
_KEY_PREFIX = "auth:ws-ticket:"
_MAX_TICKET_LENGTH = 256
_TICKET_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,256}\Z")


class WsTicketUnavailable(RuntimeError):
    """Raised when Redis cannot safely issue or consume a ticket."""


@dataclass(frozen=True)
class ArchiveDiscussionTicketAuthority:
    user_id: int
    session_expires_at: int


def _ticket_key(ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def create_archive_discussion_ticket(
    *, user_id: int, course_id: int, archive_id: int, session_expires_at: int
) -> str:
    """Store bounded target authority and return an opaque one-time ticket."""
    authority = json.dumps(
        {
            "user_id": user_id,
            "purpose": WS_TICKET_PURPOSE,
            "course_id": course_id,
            "archive_id": archive_id,
            "session_expires_at": session_expires_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        for _ in range(3):
            ticket = secrets.token_urlsafe(32)
            if redis_client.set(
                _ticket_key(ticket),
                authority,
                ex=WS_TICKET_TTL_SECONDS,
                nx=True,
            ):
                return ticket
    except RedisError as exc:
        raise WsTicketUnavailable("ws_ticket_store_unavailable") from exc
    raise WsTicketUnavailable("ws_ticket_collision_budget_exhausted")


def consume_archive_discussion_ticket(
    ticket: str, *, course_id: int, archive_id: int
) -> ArchiveDiscussionTicketAuthority | None:
    """Atomically consume and validate authority for one exact discussion target."""
    if (
        not isinstance(ticket, str)
        or not ticket
        or len(ticket) > _MAX_TICKET_LENGTH
        or _TICKET_PATTERN.fullmatch(ticket) is None
    ):
        return None

    try:
        stored = redis_client.getdel(_ticket_key(ticket))
    except RedisError as exc:
        raise WsTicketUnavailable("ws_ticket_store_unavailable") from exc
    if stored is None:
        return None

    try:
        payload = json.loads(stored)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if set(payload) != {
        "user_id",
        "purpose",
        "course_id",
        "archive_id",
        "session_expires_at",
    }:
        return None

    user_id = payload.get("user_id")
    stored_course_id = payload.get("course_id")
    stored_archive_id = payload.get("archive_id")
    session_expires_at = payload.get("session_expires_at")
    if (
        payload.get("purpose") != WS_TICKET_PURPOSE
        or type(user_id) is not int
        or user_id <= 0
        or type(stored_course_id) is not int
        or stored_course_id != course_id
        or type(stored_archive_id) is not int
        or stored_archive_id != archive_id
        or type(session_expires_at) is not int
        or session_expires_at <= 0
    ):
        return None
    return ArchiveDiscussionTicketAuthority(
        user_id=user_id,
        session_expires_at=session_expires_at,
    )
