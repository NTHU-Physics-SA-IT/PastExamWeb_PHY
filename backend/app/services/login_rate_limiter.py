from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import redis.asyncio as redis_asyncio
from redis.asyncio import Redis
from redis.exceptions import (
    AuthenticationError,
    AuthorizationError,
)
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

UNKNOWN_CLIENT_IDENTITY = "unknown-client"
_KEY_NAMESPACE = "auth:login"
_SUBKEY_CONTEXT = b"pastexam/auth-login-limiter/v1"

_ADMISSION_SCRIPT = """
local principal_count_key = KEYS[1]
local principal_block_key = KEYS[2]
local ip_count_key = KEYS[3]
local ip_block_key = KEYS[4]

local principal_limit = tonumber(ARGV[1])
local ip_limit = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local cooldown_ms = tonumber(ARGV[4])
local principal_generation_candidate = ARGV[5]

local function block_ttl(key)
    local ttl = redis.call("PTTL", key)
    if ttl == -1 then
        redis.call("PEXPIRE", key, cooldown_ms)
        return cooldown_ms
    end
    return ttl
end

local principal_block_ttl = block_ttl(principal_block_key)
local ip_block_ttl = block_ttl(ip_block_key)
local principal_blocked = principal_block_ttl >= 0
local ip_blocked = ip_block_ttl >= 0

if principal_blocked or ip_blocked then
    return {
        0,
        math.max(principal_block_ttl, ip_block_ttl, 0),
        principal_blocked and 1 or 0,
        ip_blocked and 1 or 0,
        0,
        "",
    }
end

local function repair_ttl(key)
    if redis.call("PTTL", key) == -1 then
        redis.call("PEXPIRE", key, window_ms)
    end
end

local function read_principal_count(key)
    local raw = redis.call("GET", key)
    if not raw then
        return 0, principal_generation_candidate, true
    end
    local generation, count_raw = string.match(raw, "^([0-9a-f]+):(%d+)$")
    local count = tonumber(count_raw)
    if not generation or not count then
        error("login rate limiter count is not numeric")
    end
    repair_ttl(key)
    return count, generation, false
end

local function read_ip_count(key)
    local raw = redis.call("GET", key)
    if not raw then
        return 0
    end
    local count = tonumber(raw)
    if not count then
        error("login rate limiter count is not numeric")
    end
    repair_ttl(key)
    return count
end

local principal_count, principal_generation, principal_is_new =
    read_principal_count(principal_count_key)
local ip_count = read_ip_count(ip_count_key)
local principal_exceeded = principal_count + 1 > principal_limit
local ip_exceeded = ip_count + 1 > ip_limit

if principal_exceeded or ip_exceeded then
    if principal_exceeded then
        redis.call("SET", principal_block_key, "1", "PX", cooldown_ms, "NX")
    end
    if ip_exceeded then
        redis.call("SET", ip_block_key, "1", "PX", cooldown_ms, "NX")
    end
    return {
        0,
        cooldown_ms,
        principal_exceeded and 1 or 0,
        ip_exceeded and 1 or 0,
        0,
        "",
    }
end

local new_principal_count = principal_count + 1
local new_principal_value = principal_generation .. ":" .. new_principal_count
if principal_is_new then
    redis.call("SET", principal_count_key, new_principal_value, "PX", window_ms)
else
    redis.call("SET", principal_count_key, new_principal_value, "KEEPTTL")
end

local new_ip_count = redis.call("INCR", ip_count_key)
if new_ip_count == 1 then
    redis.call("PEXPIRE", ip_count_key, window_ms)
end

return {1, 0, 0, 0, new_principal_count, principal_generation}
"""

_RESET_PRINCIPAL_SCRIPT = """
if redis.call("EXISTS", KEYS[2]) == 1 then
    return 0
end

local raw = redis.call("GET", KEYS[1])
if not raw then
    return 0
end

local expected = ARGV[1] .. ":" .. ARGV[2]
if raw == expected then
    return redis.call("DEL", KEYS[1])
end

return 0
"""


class LoginRateLimitDenialReason(StrEnum):
    PRINCIPAL = "principal"
    IP = "ip"
    BOTH = "both"


class LoginRateLimiterProtocolError(RuntimeError):
    """Raised when Redis returns an unexpected limiter script result."""


@dataclass(frozen=True)
class PrincipalResetToken:
    count_key: str
    block_key: str
    generation: str
    count: int


@dataclass(frozen=True)
class LoginAdmission:
    admitted: bool
    retry_after_seconds: int | None = None
    denial_reason: LoginRateLimitDenialReason | None = None
    principal_reset_token: PrincipalResetToken | None = None


def canonicalize_client_identity(host: str | None) -> str:
    try:
        address = ipaddress.ip_address(host)
    except (TypeError, ValueError):
        return UNKNOWN_CLIENT_IDENTITY
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.compressed


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise LoginRateLimiterProtocolError(f"invalid {field} in limiter result")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise LoginRateLimiterProtocolError(
            f"invalid {field} in limiter result"
        ) from error


def _retry_after_seconds(pttl_ms: int) -> int:
    return max(1, (pttl_ms + 999) // 1000)


class LoginRateLimiter:
    def __init__(
        self,
        redis_client: Redis,
        *,
        secret_key: str,
        principal_limit: int,
        ip_limit: int,
        window_seconds: int,
        cooldown_seconds: int,
        key_namespace: str = _KEY_NAMESPACE,
    ) -> None:
        self._redis = redis_client
        self._principal_limit = principal_limit
        self._ip_limit = ip_limit
        self._window_ms = window_seconds * 1000
        self._cooldown_ms = cooldown_seconds * 1000
        self._key_namespace = key_namespace
        self._limiter_subkey = hmac.new(
            secret_key.encode("utf-8"),
            _SUBKEY_CONTEXT,
            hashlib.sha256,
        ).digest()

    def _identity_digest(self, domain: bytes, value: str) -> str:
        return hmac.new(
            self._limiter_subkey,
            domain + b"\0" + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _keys(self, principal: str, client_identity: str) -> tuple[str, ...]:
        principal_digest = self._identity_digest(b"principal", principal)
        ip_digest = self._identity_digest(b"ip", client_identity)
        return (
            f"{self._key_namespace}:principal:{principal_digest}:count",
            f"{self._key_namespace}:principal:{principal_digest}:block",
            f"{self._key_namespace}:ip:{ip_digest}:count",
            f"{self._key_namespace}:ip:{ip_digest}:block",
        )

    async def admit(self, *, principal: str, client_identity: str) -> LoginAdmission:
        keys = self._keys(principal, client_identity)
        generation_candidate = secrets.token_hex(16)
        try:
            raw_result = await self._redis.eval(
                _ADMISSION_SCRIPT,
                len(keys),
                *keys,
                self._principal_limit,
                self._ip_limit,
                self._window_ms,
                self._cooldown_ms,
                generation_candidate,
            )
        except (AuthenticationError, AuthorizationError):
            raise
        except (RedisTimeoutError, RedisConnectionError) as error:
            logger.warning(
                "security_event=login_rate_limiter_fail_open "
                "operation=admission error_type=%s",
                type(error).__name__,
            )
            return LoginAdmission(admitted=True)

        if not isinstance(raw_result, (list, tuple)) or len(raw_result) != 6:
            raise LoginRateLimiterProtocolError("malformed limiter admission result")
        admitted = _integer(raw_result[0], field="admitted")
        pttl_ms = _integer(raw_result[1], field="pttl")
        principal_blocked = _integer(raw_result[2], field="principal block flag")
        ip_blocked = _integer(raw_result[3], field="IP block flag")
        principal_count = _integer(raw_result[4], field="principal count")
        raw_generation = raw_result[5]
        if isinstance(raw_generation, bytes):
            try:
                generation = raw_generation.decode("ascii")
            except UnicodeDecodeError as error:
                raise LoginRateLimiterProtocolError(
                    "invalid principal generation in limiter result"
                ) from error
        elif isinstance(raw_generation, str):
            generation = raw_generation
        else:
            raise LoginRateLimiterProtocolError(
                "invalid principal generation in limiter result"
            )

        if admitted == 1:
            if (
                pttl_ms != 0
                or principal_blocked != 0
                or ip_blocked != 0
                or principal_count < 1
                or len(generation) != 32
                or any(character not in "0123456789abcdef" for character in generation)
            ):
                raise LoginRateLimiterProtocolError(
                    "inconsistent admitted limiter result"
                )
            return LoginAdmission(
                admitted=True,
                principal_reset_token=PrincipalResetToken(
                    count_key=keys[0],
                    block_key=keys[1],
                    generation=generation,
                    count=principal_count,
                ),
            )

        if admitted != 0 or pttl_ms < 0:
            raise LoginRateLimiterProtocolError("inconsistent denied limiter result")
        if principal_count != 0 or generation != "":
            raise LoginRateLimiterProtocolError("inconsistent denied limiter result")
        if principal_blocked == 1 and ip_blocked == 1:
            reason = LoginRateLimitDenialReason.BOTH
        elif principal_blocked == 1 and ip_blocked == 0:
            reason = LoginRateLimitDenialReason.PRINCIPAL
        elif principal_blocked == 0 and ip_blocked == 1:
            reason = LoginRateLimitDenialReason.IP
        else:
            raise LoginRateLimiterProtocolError("denial has no limiter bucket")

        retry_after = _retry_after_seconds(pttl_ms)
        logger.warning(
            "security_event=login_rate_limiter_denied reason=%s retry_after_seconds=%d",
            reason.value,
            retry_after,
        )
        return LoginAdmission(
            admitted=False,
            retry_after_seconds=retry_after,
            denial_reason=reason,
        )

    async def reset_principal(self, token: PrincipalResetToken | None) -> None:
        if token is None:
            return
        try:
            raw_result = await self._redis.eval(
                _RESET_PRINCIPAL_SCRIPT,
                2,
                token.count_key,
                token.block_key,
                token.generation,
                token.count,
            )
        except (AuthenticationError, AuthorizationError):
            raise
        except (RedisTimeoutError, RedisConnectionError) as error:
            logger.warning(
                "security_event=login_rate_limiter_fail_open "
                "operation=principal_reset error_type=%s",
                type(error).__name__,
            )
            return
        if _integer(raw_result, field="principal reset") not in (0, 1):
            raise LoginRateLimiterProtocolError(
                "malformed limiter principal reset result"
            )

    async def aclose(self) -> None:
        await self._redis.aclose()


def create_login_rate_limiter() -> LoginRateLimiter:
    redis_client = redis_asyncio.from_url(settings.REDIS_URL)
    return LoginRateLimiter(
        redis_client,
        secret_key=settings.SECRET_KEY,
        principal_limit=settings.LOGIN_RATE_LIMIT_PRINCIPAL_ATTEMPTS,
        ip_limit=settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        cooldown_seconds=settings.LOGIN_RATE_LIMIT_COOLDOWN_SECONDS,
    )
