import asyncio
import os
import uuid
from urllib.parse import urlparse

import pytest
import redis.asyncio as redis_asyncio

from app.core.config import settings
from app.services.login_rate_limiter import LoginRateLimiter

pytestmark = pytest.mark.asyncio


def isolated_redis_url() -> str:
    url = os.getenv("SEC02B_TEST_REDIS_URL", settings.REDIS_URL)
    host = urlparse(url).hostname
    if os.getenv("PASTEXAM_TEST_DATABASE_ISOLATED") != "true":
        pytest.fail("SEC-02B Redis tests require explicit isolated-test confirmation")
    if host not in {"127.0.0.1", "localhost", "redis"}:
        pytest.fail("SEC-02B Redis tests refuse a non-local Redis target")
    return url


def make_limiter(client, *, principal_limit=8, ip_limit=50, ttl=10):
    return LoginRateLimiter(
        client,
        secret_key="isolated-integration-test-secret",
        principal_limit=principal_limit,
        ip_limit=ip_limit,
        window_seconds=ttl,
        cooldown_seconds=ttl,
        key_namespace=f"auth:login:test:{uuid.uuid4().hex}",
    )


async def delete_exact_limiter_keys(client, limiter, identities):
    keys = []
    for principal, client_identity in identities:
        keys.extend(limiter._keys(principal, client_identity))
    if keys:
        await client.delete(*set(keys))


async def principal_count(client, key):
    raw = await client.get(key)
    if raw is None:
        return None
    return int(raw.rsplit(b":", 1)[1])


async def test_real_redis_enforces_exact_principal_and_ip_thresholds():
    client = redis_asyncio.from_url(isolated_redis_url())
    principal_limiter = make_limiter(client)
    ip_limiter = make_limiter(client)
    principal_identity = ("principal", "192.0.2.10")
    ip_identities = [(f"principal-{index}", "192.0.2.20") for index in range(51)]
    try:
        principal_results = [
            await principal_limiter.admit(
                principal=principal_identity[0], client_identity=principal_identity[1]
            )
            for _ in range(9)
        ]
        assert [result.admitted for result in principal_results] == [True] * 8 + [False]
        ip_results = [
            await ip_limiter.admit(principal=principal, client_identity=client_ip)
            for principal, client_ip in ip_identities
        ]
        assert [result.admitted for result in ip_results] == [True] * 50 + [False]
        principal_keys = principal_limiter._keys(*principal_identity)
        assert await principal_count(client, principal_keys[0]) == 8
        assert await client.pttl(principal_keys[0]) > 0
        assert await client.pttl(principal_keys[1]) > 0
        ip_keys = ip_limiter._keys(*ip_identities[0])
        denied_ip_keys = ip_limiter._keys(*ip_identities[-1])
        assert await client.get(ip_keys[2]) == b"50"
        assert await client.pttl(ip_keys[2]) > 0
        assert await client.pttl(ip_keys[3]) > 0
        assert await client.get(denied_ip_keys[0]) is None
    finally:
        await delete_exact_limiter_keys(client, principal_limiter, [principal_identity])
        await delete_exact_limiter_keys(client, ip_limiter, ip_identities)
        await client.aclose()


async def test_denial_does_not_increment_or_extend_the_fixed_cooldown():
    client = redis_asyncio.from_url(isolated_redis_url())
    limiter = make_limiter(client, principal_limit=1, ip_limit=10)
    identity = ("principal", "192.0.2.30")
    try:
        assert (
            await limiter.admit(principal=identity[0], client_identity=identity[1])
        ).admitted
        denied = await limiter.admit(principal=identity[0], client_identity=identity[1])
        keys = limiter._keys(*identity)
        first_ttl = await client.pttl(keys[1])
        await asyncio.sleep(0.05)
        denied_again = await limiter.admit(
            principal=identity[0], client_identity=identity[1]
        )
        second_ttl = await client.pttl(keys[1])
        assert denied.admitted is False
        assert denied_again.admitted is False
        assert await principal_count(client, keys[0]) == 1
        assert second_ttl < first_ttl
    finally:
        await delete_exact_limiter_keys(client, limiter, [identity])
        await client.aclose()


async def test_concurrent_admission_never_exceeds_allowance():
    client = redis_asyncio.from_url(isolated_redis_url())
    limiter = make_limiter(client, principal_limit=5, ip_limit=100)
    identity = ("principal", "192.0.2.40")
    try:
        results = await asyncio.gather(
            *[
                limiter.admit(principal=identity[0], client_identity=identity[1])
                for _ in range(20)
            ]
        )
        keys = limiter._keys(*identity)
        assert sum(result.admitted for result in results) == 5
        assert await principal_count(client, keys[0]) == 5
        assert await client.pttl(keys[0]) > 0
        assert await client.pttl(keys[1]) > 0
    finally:
        await delete_exact_limiter_keys(client, limiter, [identity])
        await client.aclose()


async def test_generation_safe_reset_preserves_newer_attempt_and_ip_state():
    client = redis_asyncio.from_url(isolated_redis_url())
    limiter = make_limiter(client)
    identity = ("principal", "192.0.2.50")
    try:
        first = await limiter.admit(principal=identity[0], client_identity=identity[1])
        second = await limiter.admit(principal=identity[0], client_identity=identity[1])
        keys = limiter._keys(*identity)
        await limiter.reset_principal(first.principal_reset_token)
        assert await principal_count(client, keys[0]) == 2
        assert await client.get(keys[2]) == b"2"
        await limiter.reset_principal(second.principal_reset_token)
        assert await client.get(keys[0]) is None
        assert await client.get(keys[2]) == b"2"
    finally:
        await delete_exact_limiter_keys(client, limiter, [identity])
        await client.aclose()


async def test_generation_safe_reset_cannot_erase_a_later_block():
    client = redis_asyncio.from_url(isolated_redis_url())
    limiter = make_limiter(client, principal_limit=2, ip_limit=10)
    identity = ("principal", "192.0.2.55")
    try:
        first = await limiter.admit(principal=identity[0], client_identity=identity[1])
        second = await limiter.admit(principal=identity[0], client_identity=identity[1])
        denied = await limiter.admit(principal=identity[0], client_identity=identity[1])
        keys = limiter._keys(*identity)
        assert denied.admitted is False
        await limiter.reset_principal(first.principal_reset_token)
        await limiter.reset_principal(second.principal_reset_token)
        assert await principal_count(client, keys[0]) == 2
        assert await client.pttl(keys[1]) > 0
    finally:
        await delete_exact_limiter_keys(client, limiter, [identity])
        await client.aclose()


async def test_short_expiry_allows_admission_again():
    client = redis_asyncio.from_url(isolated_redis_url())
    limiter = make_limiter(client, principal_limit=1, ip_limit=10, ttl=1)
    identity = ("principal", "192.0.2.60")
    try:
        first = await limiter.admit(principal=identity[0], client_identity=identity[1])
        assert first.admitted
        assert not (
            await limiter.admit(principal=identity[0], client_identity=identity[1])
        ).admitted
        await asyncio.sleep(1.1)
        next_window = await limiter.admit(
            principal=identity[0], client_identity=identity[1]
        )
        assert next_window.admitted
        assert (
            first.principal_reset_token.generation
            != next_window.principal_reset_token.generation
        )
        await limiter.reset_principal(first.principal_reset_token)
        assert await principal_count(client, limiter._keys(*identity)[0]) == 1
    finally:
        await delete_exact_limiter_keys(client, limiter, [identity])
        await client.aclose()
