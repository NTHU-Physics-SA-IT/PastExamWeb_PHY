from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import nthu_dev_mock
from app.services.nthu_oauth import NthuOAuthProviderError


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: list[int] = []

    def set(self, key, value, *, ex, nx):
        assert nx is True
        if key in self.values:
            return False
        self.values[key] = value
        self.expirations.append(ex)
        return True

    def getdel(self, key):
        return self.values.pop(key, None)


@pytest.fixture()
def enabled_mock(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(settings, "APP_ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_ENABLED", True)
    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_TTL_SECONDS", 75)
    monkeypatch.setattr(nthu_dev_mock, "redis_client", fake_redis)
    return fake_redis


def test_fixed_catalog_has_exactly_seven_safe_unique_profiles(enabled_mock) -> None:
    profiles = nthu_dev_mock.NTHU_DEV_PROFILES

    assert [profile.key for profile in profiles] == [
        "physics",
        "other_department",
        "special_userid",
        "missing_userid",
        "staff_allowed",
        "staff_unlisted",
        "not_inschool",
    ]
    assert len({profile.uuid for profile in profiles}) == 7
    assert len({profile.email for profile in profiles}) == 7
    assert all(profile.email.endswith(".invalid") for profile in profiles)
    assert all(profile.name.startswith("[DEV]") for profile in profiles)


def test_dev_code_is_opaque_ttl_bound_and_one_time(enabled_mock) -> None:
    code = nthu_dev_mock.create_nthu_dev_code("physics")

    assert code.startswith("dev_")
    assert "physics" not in code
    assert enabled_mock.expirations == [75]
    assert nthu_dev_mock.consume_nthu_dev_profile(code).uuid == "dev-nthu-physics-0001"
    with pytest.raises(NthuOAuthProviderError):
        nthu_dev_mock.consume_nthu_dev_profile(code)


def test_unknown_profile_key_is_rejected(enabled_mock) -> None:
    with pytest.raises(KeyError):
        nthu_dev_mock.create_nthu_dev_code("custom-profile")


def test_mock_is_disabled_by_default_and_production_enablement_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_ENABLED", False)
    assert nthu_dev_mock.nthu_dev_mock_is_available() is False

    monkeypatch.setattr(settings, "NTHU_DEV_MOCK_ENABLED", True)
    with pytest.raises(RuntimeError):
        nthu_dev_mock.validate_nthu_dev_mock_configuration()
    with pytest.raises(NthuOAuthProviderError):
        nthu_dev_mock.consume_nthu_dev_profile("dev_" + "a" * 43)
