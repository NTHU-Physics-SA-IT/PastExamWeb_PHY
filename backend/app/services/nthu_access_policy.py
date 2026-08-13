from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import SystemSetting
from app.services.nthu_affiliation import (
    NthuAffiliationKind,
    classify_nthu_affiliation,
    department_by_code,
)

if TYPE_CHECKING:
    from app.services.nthu_oauth import NthuProfile


NTHU_ACCESS_POLICY_SETTING_KEY = "nthu_access_policy"
NTHU_STAFF_USERID_MAX_LENGTH = 255
LEGACY_SPECIAL_AFFILIATIONS_KEY = "".join(("allowed_special_", "affiliations"))


class NthuAccessMode(str, Enum):
    ALL_NTHU = "all_nthu"
    SELECTED_DEPARTMENTS = "selected_departments"


class NthuStaffAccess(str, Enum):
    NONE = "none"
    ALLOWLIST = "allowlist"


class NthuAccessPolicyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NthuAccessPolicy:
    mode: NthuAccessMode
    allowed_department_codes: tuple[str, ...] = ()
    staff_access: NthuStaffAccess = NthuStaffAccess.NONE
    allowed_staff_userids: tuple[str, ...] = ()

    def as_storage_value(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allowed_department_codes": list(self.allowed_department_codes),
            "staff_access": self.staff_access.value,
            "allowed_staff_userids": list(self.allowed_staff_userids),
        }


DEFAULT_NTHU_ACCESS_POLICY = NthuAccessPolicy(mode=NthuAccessMode.ALL_NTHU)


def normalize_nthu_access_policy(value: object) -> NthuAccessPolicy:
    if not isinstance(value, dict):
        raise NthuAccessPolicyValidationError("登入範圍格式不正確")
    required_keys = {"mode", "allowed_department_codes"}
    optional_keys = {
        LEGACY_SPECIAL_AFFILIATIONS_KEY,
        "staff_access",
        "allowed_staff_userids",
    }
    if not required_keys.issubset(value) or not set(value).issubset(
        required_keys | optional_keys
    ):
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

    try:
        staff_access = NthuStaffAccess(value.get("staff_access", "none"))
    except (TypeError, ValueError) as error:
        raise NthuAccessPolicyValidationError("教職員開放方式無效") from error

    raw_staff_userids = value.get("allowed_staff_userids", [])
    if not isinstance(raw_staff_userids, list) or any(
        not isinstance(userid, str) for userid in raw_staff_userids
    ):
        raise NthuAccessPolicyValidationError("員工編號清單格式無效")

    staff_userids: list[str] = []
    for raw_userid in raw_staff_userids:
        userid = raw_userid.strip()
        if (
            not userid
            or len(userid) > NTHU_STAFF_USERID_MAX_LENGTH
            or any(
                unicodedata.category(character).startswith("C") for character in userid
            )
            or any(character.isspace() for character in userid)
        ):
            raise NthuAccessPolicyValidationError("員工編號格式無效")
        if userid in staff_userids:
            raise NthuAccessPolicyValidationError("員工編號不可重複")
        staff_userids.append(userid)

    if mode is NthuAccessMode.SELECTED_DEPARTMENTS:
        if staff_access is NthuStaffAccess.NONE and staff_userids:
            raise NthuAccessPolicyValidationError("未啟用教職員清單時不可包含員工編號")
        if staff_access is NthuStaffAccess.ALLOWLIST and not staff_userids:
            raise NthuAccessPolicyValidationError("教職員個別允許至少需要一個員工編號")
        if not codes and not staff_userids:
            raise NthuAccessPolicyValidationError("自訂範圍至少需要一個系所或員工編號")

    return NthuAccessPolicy(
        mode=mode,
        allowed_department_codes=codes,
        staff_access=staff_access,
        allowed_staff_userids=tuple(staff_userids),
    )


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
    now = datetime.now(UTC)
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

    if (
        policy.staff_access is NthuStaffAccess.ALLOWLIST
        and profile.userid is not None
        and profile.userid in policy.allowed_staff_userids
    ):
        return

    affiliation = classify_nthu_affiliation(profile.userid)
    if (
        affiliation.kind is NthuAffiliationKind.STANDARD_STUDENT
        and affiliation.department_code in policy.allowed_department_codes
    ):
        return
    raise NthuOAuthBusinessError("oauth_department_not_allowed")
