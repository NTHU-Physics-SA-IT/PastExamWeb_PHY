from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import SystemSetting
from app.services.nthu_affiliation import (
    department_by_code,
    parse_nthu_student_affiliation,
)

if TYPE_CHECKING:
    from app.services.nthu_oauth import NthuProfile


NTHU_ACCESS_POLICY_SETTING_KEY = "nthu_access_policy"


class NthuAccessMode(str, Enum):
    ALL_NTHU = "all_nthu"
    SELECTED_DEPARTMENTS = "selected_departments"


class NthuAccessPolicyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NthuAccessPolicy:
    mode: NthuAccessMode
    allowed_department_codes: tuple[str, ...] = ()

    def as_storage_value(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allowed_department_codes": list(self.allowed_department_codes),
        }


DEFAULT_NTHU_ACCESS_POLICY = NthuAccessPolicy(mode=NthuAccessMode.ALL_NTHU)


def normalize_nthu_access_policy(value: object) -> NthuAccessPolicy:
    if not isinstance(value, dict):
        raise NthuAccessPolicyValidationError("登入範圍格式不正確")
    if set(value) != {"mode", "allowed_department_codes"}:
        raise NthuAccessPolicyValidationError("登入範圍欄位不正確")

    try:
        mode = NthuAccessMode(value.get("mode"))
    except (TypeError, ValueError) as error:
        raise NthuAccessPolicyValidationError("登入範圍模式不正確") from error

    raw_codes = value.get("allowed_department_codes")
    if not isinstance(raw_codes, list) or any(
        not isinstance(code, str) for code in raw_codes
    ):
        raise NthuAccessPolicyValidationError("系所代碼格式不正確")

    codes = tuple(sorted(set(raw_codes)))
    if any(department_by_code(code) is None for code in codes):
        raise NthuAccessPolicyValidationError("登入範圍包含未知系所")
    if mode is NthuAccessMode.SELECTED_DEPARTMENTS and not codes:
        raise NthuAccessPolicyValidationError("指定系所模式至少需要選擇一個系所")
    if mode is NthuAccessMode.ALL_NTHU:
        codes = ()

    return NthuAccessPolicy(mode=mode, allowed_department_codes=codes)


async def load_nthu_access_policy(db: AsyncSession) -> NthuAccessPolicy:
    setting = await db.scalar(
        select(SystemSetting).where(SystemSetting.key == NTHU_ACCESS_POLICY_SETTING_KEY)
    )
    if setting is None:
        return DEFAULT_NTHU_ACCESS_POLICY
    return normalize_nthu_access_policy(setting.value)


async def save_nthu_access_policy(
    db: AsyncSession,
    value: object,
    *,
    updated_by_id: int,
) -> NthuAccessPolicy:
    policy = normalize_nthu_access_policy(value)
    now = datetime.now(timezone.utc)
    storage_value = policy.as_storage_value()
    statement = (
        postgresql_insert(SystemSetting)
        .values(
            key=NTHU_ACCESS_POLICY_SETTING_KEY,
            value=storage_value,
            created_at=now,
            updated_at=now,
            updated_by_id=updated_by_id,
        )
        .on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={
                "value": storage_value,
                "updated_at": now,
                "updated_by_id": updated_by_id,
            },
        )
    )
    await db.execute(statement)
    return policy


def ensure_profile_matches_access_policy(
    profile: NthuProfile,
    policy: NthuAccessPolicy,
) -> None:
    # Import lazily to keep the OAuth transport/profile module independent from
    # the persistence-backed policy service it invokes during identity resolution.
    from app.services.nthu_oauth import NthuOAuthBusinessError

    if profile.inschool is not True:
        raise NthuOAuthBusinessError("oauth_not_in_school")
    if policy.mode is NthuAccessMode.ALL_NTHU:
        return

    affiliation = parse_nthu_student_affiliation(profile.userid)
    if affiliation.department_code not in policy.allowed_department_codes:
        raise NthuOAuthBusinessError("oauth_department_not_allowed")
