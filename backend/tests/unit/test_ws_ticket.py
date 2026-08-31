from __future__ import annotations

import json

import pytest
from jose import JWTError, jwt
from redis.exceptions import ConnectionError

from app.services import ws_ticket


class FakeRedis:
    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.set_options: list[tuple[int, bool]] = []

    def set(self, key, value, *, ex, nx):
        self.set_options.append((ex, nx))
        if nx and key in self.values:
            return False
        self.values[key] = value.encode()
        self.ttls[key] = ex
        return True

    def getdel(self, key):
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


def test_ticket_is_opaque_target_bound_short_lived_and_single_use(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ws_ticket, "redis_client", redis)

    ticket = ws_ticket.create_archive_discussion_ticket(
        user_id=42,
        course_id=7,
        archive_id=9,
        session_expires_at=4102444800,
    )

    assert ticket
    assert len(ticket) >= 43
    assert ticket.replace("-", "").replace("_", "").isalnum()
    assert all(ticket not in key for key in redis.values)
    assert all(ticket not in value.decode() for value in redis.values.values())
    assert list(redis.ttls.values()) == [ws_ticket.WS_TICKET_TTL_SECONDS]
    assert redis.set_options == [(ws_ticket.WS_TICKET_TTL_SECONDS, True)]
    with pytest.raises(JWTError):
        jwt.decode(ticket, "unit-test-secret", algorithms=["HS256"])
    authority = ws_ticket.consume_archive_discussion_ticket(
        ticket,
        course_id=7,
        archive_id=9,
    )
    assert authority is not None
    assert authority.user_id == 42
    assert authority.session_expires_at == 4102444800
    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=7, archive_id=9)
        is None
    )


def test_ticket_target_mismatch_consumes_authority(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ws_ticket, "redis_client", redis)
    ticket = ws_ticket.create_archive_discussion_ticket(
        user_id=4,
        course_id=1,
        archive_id=2,
        session_expires_at=4102444800,
    )

    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=1, archive_id=3)
        is None
    )
    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=1, archive_id=2)
        is None
    )


def test_ticket_rejects_malformed_or_corrupt_authority(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ws_ticket, "redis_client", redis)

    assert (
        ws_ticket.consume_archive_discussion_ticket("", course_id=1, archive_id=2)
        is None
    )
    assert (
        ws_ticket.consume_archive_discussion_ticket(
            "contains whitespace", course_id=1, archive_id=2
        )
        is None
    )
    assert (
        ws_ticket.consume_archive_discussion_ticket(
            "x" * 300, course_id=1, archive_id=2
        )
        is None
    )

    ticket = ws_ticket.create_archive_discussion_ticket(
        user_id=4,
        course_id=1,
        archive_id=2,
        session_expires_at=4102444800,
    )
    redis.values[next(iter(redis.values))] = b"not-json"
    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=1, archive_id=2)
        is None
    )


def test_ticket_purpose_mismatch_is_consumed(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ws_ticket, "redis_client", redis)
    ticket = ws_ticket.create_archive_discussion_ticket(
        user_id=4,
        course_id=1,
        archive_id=2,
        session_expires_at=4102444800,
    )
    key = next(iter(redis.values))
    authority = json.loads(redis.values[key])
    authority["purpose"] = "different-purpose"
    redis.values[key] = json.dumps(authority).encode()

    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=1, archive_id=2)
        is None
    )
    assert key not in redis.values


def test_ticket_rejects_unbounded_stored_authority(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ws_ticket, "redis_client", redis)
    ticket = ws_ticket.create_archive_discussion_ticket(
        user_id=4,
        course_id=1,
        archive_id=2,
        session_expires_at=4102444800,
    )
    key = next(iter(redis.values))
    authority = json.loads(redis.values[key])
    authority["unexpected"] = "value"
    redis.values[key] = json.dumps(authority).encode()

    assert (
        ws_ticket.consume_archive_discussion_ticket(ticket, course_id=1, archive_id=2)
        is None
    )
    assert key not in redis.values


def test_ticket_redis_failures_fail_closed(monkeypatch):
    class FailingRedis:
        def set(self, *args, **kwargs):
            raise ConnectionError("unavailable")

        def getdel(self, *args, **kwargs):
            raise ConnectionError("unavailable")

    monkeypatch.setattr(ws_ticket, "redis_client", FailingRedis())

    with pytest.raises(ws_ticket.WsTicketUnavailable):
        ws_ticket.create_archive_discussion_ticket(
            user_id=4,
            course_id=1,
            archive_id=2,
            session_expires_at=4102444800,
        )
    with pytest.raises(ws_ticket.WsTicketUnavailable):
        ws_ticket.consume_archive_discussion_ticket("x" * 43, course_id=1, archive_id=2)
