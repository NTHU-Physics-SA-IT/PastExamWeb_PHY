from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import secrets

from app.core.config import settings
from app.services.nthu_affiliation import (
    department_by_code,
    parse_nthu_student_affiliation,
)
from app.services.nthu_oauth import NthuOAuthProviderError, NthuProfile
from app.utils.auth import redis_client


_DEV_CODE_PREFIX = "dev_"
_REDIS_KEY_PREFIX = "auth:nthu-dev-provider-code:"
_DEV_CODE_PATTERN = re.compile(r"dev_[A-Za-z0-9_-]{32,256}\Z")
_ALLOWED_ENVIRONMENTS = {"development", "test"}


@dataclass(frozen=True)
class NthuDevProfileDefinition:
    key: str
    label: str
    uuid: str
    userid: str | None
    name: str
    email: str
    inschool: bool

    def profile(self) -> NthuProfile:
        return NthuProfile(
            uuid=self.uuid,
            userid=self.userid,
            name=self.name,
            email=self.email,
            inschool=self.inschool,
        )

    def public_value(self) -> dict[str, object]:
        affiliation = parse_nthu_student_affiliation(self.userid)
        department = department_by_code(affiliation.department_code)
        return {
            "key": self.key,
            "label": self.label,
            "userid": self.userid,
            "name": self.name,
            "inschool": self.inschool,
            "department_code": department.code if department else None,
            "department_name": department.name if department else None,
        }


NTHU_DEV_PROFILES = (
    NthuDevProfileDefinition(
        "physics",
        "物理系學生",
        "dev-nthu-physics-0001",
        "112022123",
        "[DEV] 清大物理測試生",
        "dev-nthu-physics@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "other_department",
        "其他系所學生",
        "dev-nthu-other-0001",
        "112025123",
        "[DEV] 清大其他系所測試生",
        "dev-nthu-other@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "special_userid",
        "特殊學號",
        "dev-nthu-special-0001",
        "X1106099",
        "[DEV] 清大特殊學號測試生",
        "dev-nthu-special@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "missing_userid",
        "無學號",
        "dev-nthu-missing-0001",
        None,
        "[DEV] 清大無學號測試生",
        "dev-nthu-missing@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "staff_allowed",
        "允許的教職員",
        "dev-nthu-staff-allowed-0001",
        "W90001",
        "[DEV] 清大教職員測試帳號",
        "dev-nthu-staff-allowed@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "staff_unlisted",
        "未列入的教職員",
        "dev-nthu-staff-unlisted-0001",
        "W90002",
        "[DEV] 清大未允許教職員",
        "dev-nthu-staff-unlisted@example.invalid",
        True,
    ),
    NthuDevProfileDefinition(
        "not_inschool",
        "非在校成員",
        "dev-nthu-inactive-0001",
        "112022124",
        "[DEV] 清大非在校測試生",
        "dev-nthu-inactive@example.invalid",
        False,
    ),
)
_PROFILES_BY_KEY = {profile.key: profile for profile in NTHU_DEV_PROFILES}


def nthu_dev_mock_is_available() -> bool:
    return (
        settings.NTHU_DEV_MOCK_ENABLED
        and settings.APP_ENVIRONMENT.strip().lower() in _ALLOWED_ENVIRONMENTS
    )


def validate_nthu_dev_mock_configuration() -> None:
    if settings.NTHU_DEV_MOCK_ENABLED and not nthu_dev_mock_is_available():
        raise RuntimeError(
            "NTHU development mock cannot be enabled in this environment"
        )
    if settings.NTHU_DEV_MOCK_ENABLED and not (
        60 <= settings.NTHU_DEV_MOCK_TTL_SECONDS <= 90
    ):
        raise RuntimeError(
            "NTHU development mock TTL must be between 60 and 90 seconds"
        )


def _key(code: str) -> str:
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return f"{_REDIS_KEY_PREFIX}{digest}"


def create_nthu_dev_code(profile_key: str) -> str:
    if not nthu_dev_mock_is_available():
        raise NthuOAuthProviderError()
    if profile_key not in _PROFILES_BY_KEY:
        raise KeyError(profile_key)
    for _ in range(3):
        code = f"{_DEV_CODE_PREFIX}{secrets.token_urlsafe(32)}"
        if redis_client.set(
            _key(code),
            profile_key,
            ex=settings.NTHU_DEV_MOCK_TTL_SECONDS,
            nx=True,
        ):
            return code
    raise NthuOAuthProviderError()


def consume_nthu_dev_profile(code: str) -> NthuProfile:
    if not nthu_dev_mock_is_available() or _DEV_CODE_PATTERN.fullmatch(code) is None:
        raise NthuOAuthProviderError()
    raw_key = redis_client.getdel(_key(code))
    if isinstance(raw_key, bytes):
        raw_key = raw_key.decode("utf-8", errors="strict")
    definition = _PROFILES_BY_KEY.get(raw_key) if isinstance(raw_key, str) else None
    if definition is None:
        raise NthuOAuthProviderError()
    return definition.profile()


def is_nthu_dev_code(code: str) -> bool:
    return isinstance(code, str) and code.startswith(_DEV_CODE_PREFIX)


def public_nthu_dev_profiles() -> list[dict[str, object]]:
    if not nthu_dev_mock_is_available():
        raise NthuOAuthProviderError()
    return [profile.public_value() for profile in NTHU_DEV_PROFILES]
