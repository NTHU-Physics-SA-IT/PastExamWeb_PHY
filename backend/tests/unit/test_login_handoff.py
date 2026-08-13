from __future__ import annotations

from app.services import login_handoff


class FakeRedis:
    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key, value, *, ex, nx):
        if nx and key in self.values:
            return False
        self.values[key] = str(value).encode()
        self.ttls[key] = ex
        return True

    def getdel(self, key):
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


def test_login_handoff_is_opaque_short_lived_and_single_use(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(login_handoff, "redis_client", redis)

    code = login_handoff.create_login_handoff(42)

    assert code
    assert all(code not in key for key in redis.values)
    assert list(redis.ttls.values()) == [login_handoff.LOGIN_HANDOFF_TTL_SECONDS]
    assert login_handoff.consume_login_handoff(code) == 42
    assert login_handoff.consume_login_handoff(code) is None


def test_login_handoff_rejects_unknown_expired_and_malformed_codes(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(login_handoff, "redis_client", redis)

    code = login_handoff.create_login_handoff(9)
    redis.values.clear()
    redis.ttls.clear()

    assert login_handoff.consume_login_handoff(code) is None
    assert login_handoff.consume_login_handoff("") is None
    assert login_handoff.consume_login_handoff("contains whitespace" * 3) is None
    assert login_handoff.consume_login_handoff("!" * 43) is None
    assert login_handoff.consume_login_handoff("x" * 300) is None
