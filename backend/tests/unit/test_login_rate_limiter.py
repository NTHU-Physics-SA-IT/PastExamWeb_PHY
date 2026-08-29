import logging

import pytest
from pydantic import ValidationError
from redis.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    DataError,
    ResponseError,
    TimeoutError,
)

from app.core.config import Settings, settings
from app.services.login_rate_limiter import (
    LoginRateLimitDenialReason,
    LoginRateLimiter,
    LoginRateLimiterProtocolError,
    PrincipalResetToken,
    canonicalize_client_identity,
)


class FakeRedis:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.closed = False

    async def eval(self, *args):
        self.calls.append(args)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def aclose(self):
        self.closed = True


def make_limiter(redis_client, **overrides):
    values = {
        "secret_key": "test-secret-with-sufficient-entropy",
        "principal_limit": 8,
        "ip_limit": 50,
        "window_seconds": 600,
        "cooldown_seconds": 600,
        "key_namespace": "auth:login:test",
    }
    values.update(overrides)
    return LoginRateLimiter(redis_client, **values)


def test_client_identity_is_canonical_and_never_bypasses_limiting():
    assert canonicalize_client_identity("192.0.2.10") == "192.0.2.10"
    assert canonicalize_client_identity("2001:0db8::1") == "2001:db8::1"
    assert canonicalize_client_identity("::ffff:192.0.2.10") == "192.0.2.10"
    assert canonicalize_client_identity(None) == "unknown-client"
    assert canonicalize_client_identity("not-an-ip") == "unknown-client"


def test_limiter_keys_preserve_exact_principal_semantics_without_plaintext():
    limiter = make_limiter(FakeRedis())
    submitted = " Student-ID "
    address = "2001:db8::1"
    keys = limiter._keys(submitted, address)
    changed_case_keys = limiter._keys(submitted.lower(), address)
    assert keys[0] != changed_case_keys[0]
    assert keys[2] == changed_case_keys[2]
    assert all(submitted not in key for key in keys)
    assert all("Student-ID" not in key for key in keys)
    assert all(address not in key for key in keys)
    assert all(key.startswith("auth:login:test:") for key in keys)


@pytest.mark.asyncio
async def test_admission_result_and_retry_after_are_strictly_parsed(caplog):
    redis_client = FakeRedis([0, 1001, 1, 1, 0, b""])
    limiter = make_limiter(redis_client)
    with caplog.at_level(logging.WARNING):
        result = await limiter.admit(
            principal="private-principal", client_identity="192.0.2.10"
        )
    assert result.admitted is False
    assert result.retry_after_seconds == 2
    assert result.denial_reason is LoginRateLimitDenialReason.BOTH
    assert "private-principal" not in caplog.text
    assert "192.0.2.10" not in caplog.text
    assert "reason=both" in caplog.text


@pytest.mark.asyncio
async def test_retry_after_has_a_positive_minimum():
    limiter = make_limiter(FakeRedis([0, 0, 1, 0, 0, b""]))
    result = await limiter.admit(principal="p", client_identity="192.0.2.1")
    assert result.retry_after_seconds == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError()])
async def test_transient_admission_redis_failure_fails_open_without_identifiers(
    error, caplog
):
    limiter = make_limiter(FakeRedis(error))
    with caplog.at_level(logging.WARNING):
        result = await limiter.admit(
            principal="private-principal", client_identity="192.0.2.10"
        )
    assert result.admitted is True
    assert result.principal_reset_token is None
    assert "login_rate_limiter_fail_open" in caplog.text
    assert "private-principal" not in caplog.text
    assert "192.0.2.10" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [AuthenticationError(), AuthorizationError(), ResponseError(), DataError("bad")],
)
async def test_non_transient_admission_redis_failures_are_not_swallowed(error):
    limiter = make_limiter(FakeRedis(error))
    with pytest.raises(type(error)):
        await limiter.admit(principal="p", client_identity="192.0.2.1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        [1, 0, 0, 0, 1],
        [1, 1, 0, 0, 1, b"0" * 32],
        [0, 1000, 0, 0, 0, b""],
        [1, 0, 0, 0, 1, b"not-a-generation"],
    ],
)
async def test_malformed_admission_script_result_is_rejected(result):
    limiter = make_limiter(FakeRedis(result))
    with pytest.raises(LoginRateLimiterProtocolError):
        await limiter.admit(principal="p", client_identity="192.0.2.1")


@pytest.mark.asyncio
async def test_success_reset_uses_only_the_generation_token():
    redis_client = FakeRedis(1)
    limiter = make_limiter(redis_client)
    token = PrincipalResetToken("principal-count", "principal-block", "a" * 32, 4)
    await limiter.reset_principal(token)
    assert redis_client.calls[0][1:] == (
        2,
        "principal-count",
        "principal-block",
        "a" * 32,
        4,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError()])
async def test_transient_reset_redis_failure_does_not_break_success(error, caplog):
    limiter = make_limiter(FakeRedis(error))
    token = PrincipalResetToken("principal-count", "principal-block", "a" * 32, 1)
    with caplog.at_level(logging.WARNING):
        await limiter.reset_principal(token)
    assert "operation=principal_reset" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [AuthenticationError(), AuthorizationError(), ResponseError(), DataError("bad")],
)
async def test_non_transient_reset_redis_failures_are_not_swallowed(error):
    limiter = make_limiter(FakeRedis(error))
    token = PrincipalResetToken("principal-count", "principal-block", "a" * 32, 1)
    with pytest.raises(type(error)):
        await limiter.reset_principal(token)


@pytest.mark.asyncio
async def test_client_is_closed_explicitly():
    redis_client = FakeRedis()
    limiter = make_limiter(redis_client)
    await limiter.aclose()
    assert redis_client.closed is True


@pytest.mark.parametrize(
    "field",
    [
        "LOGIN_RATE_LIMIT_PRINCIPAL_ATTEMPTS",
        "LOGIN_RATE_LIMIT_IP_ATTEMPTS",
        "LOGIN_RATE_LIMIT_WINDOW_SECONDS",
        "LOGIN_RATE_LIMIT_COOLDOWN_SECONDS",
    ],
)
def test_rate_limit_settings_must_be_positive(field):
    values = settings.model_dump()
    values[field] = 0
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.asyncio
async def test_application_lifecycle_reuses_and_closes_one_limiter(monkeypatch):
    from app import main

    limiter = FakeRedis()
    monkeypatch.setattr(main, "validate_nthu_dev_mock_configuration", lambda: None)

    async def no_database_startup():
        return None

    monkeypatch.setattr(main, "init_db", no_database_startup)
    monkeypatch.setattr(main, "create_login_rate_limiter", lambda: limiter)

    await main.on_startup()
    assert main.app.state.login_rate_limiter is limiter
    await main.on_shutdown()
    assert limiter.closed is True
