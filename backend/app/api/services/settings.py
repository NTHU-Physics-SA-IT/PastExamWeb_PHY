from datetime import datetime, timezone
from typing import Any, List
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import SystemSetting, UserRoles
from app.services.nthu_access_policy import (
    NthuAccessPolicy,
    NthuAccessPolicyValidationError,
    load_nthu_access_policy,
    save_nthu_access_policy,
)
from app.services.nthu_affiliation import NTHU_DEPARTMENTS
from app.utils.auth import get_current_user

router = APIRouter()

CONTRIBUTOR_LEVEL_SETTINGS_KEY = "contributor_level_settings"
CONTRIBUTOR_LEVEL_COUNT = 10
CONTRIBUTOR_LEVEL_NAME_MAX_LENGTH = 30

DEFAULT_CONTRIBUTOR_LEVEL_SETTINGS = [
    {"level": 1, "name": "新手投稿者", "name_en": "Novice Contributor", "min_exp": 0},
    {"level": 2, "name": "初階整理者", "name_en": "Junior Curator", "min_exp": 2},
    {"level": 3, "name": "穩定投稿者", "name_en": "Regular Contributor", "min_exp": 5},
    {"level": 4, "name": "認真貢獻者", "name_en": "Dedicated Contributor", "min_exp": 9},
    {"level": 5, "name": "經典整理師", "name_en": "Archive Curator", "min_exp": 14},
    {"level": 6, "name": "題庫建設者", "name_en": "Archive Builder", "min_exp": 20},
    {"level": 7, "name": "資源探索者", "name_en": "Resource Explorer", "min_exp": 27},
    {"level": 8, "name": "校園收藏家", "name_en": "Campus Collector", "min_exp": 35},
    {"level": 9, "name": "傳奇貢獻者", "name_en": "Legendary Contributor", "min_exp": 44},
    {"level": 10, "name": "題庫宗師", "name_en": "Archive Grandmaster", "min_exp": 54},
]

DEFAULT_CONTRIBUTOR_LEVEL_ENGLISH_NAMES = {
    (item["level"], item["name"]): item["name_en"]
    for item in DEFAULT_CONTRIBUTOR_LEVEL_SETTINGS
}


class ContributorLevelSettingRead(BaseModel):
    level: int
    name: str
    name_en: str | None = None
    min_exp: int

    class Config:
        extra = "forbid"


class NthuDepartmentRead(BaseModel):
    code: str
    name: str
    college_code: str
    college_name: str


class NthuAccessPolicyRead(BaseModel):
    mode: str
    allowed_department_codes: list[str]
    staff_access: str
    allowed_staff_userids: list[str]
    departments: list[NthuDepartmentRead]


def _require_admin(current_user: UserRoles) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )


def _nthu_access_policy_response(policy: NthuAccessPolicy) -> NthuAccessPolicyRead:
    return NthuAccessPolicyRead(
        mode=policy.mode.value,
        allowed_department_codes=list(policy.allowed_department_codes),
        staff_access=policy.staff_access.value,
        allowed_staff_userids=list(policy.allowed_staff_userids),
        departments=[
            NthuDepartmentRead(**department.__dict__) for department in NTHU_DEPARTMENTS
        ],
    )


def _contains_visible_character(value: str) -> bool:
    return any(
        not char.isspace() and unicodedata.category(char) != "Cf" for char in value
    )


def validate_contributor_level_settings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("投稿等級設定必須是陣列")
    if len(value) != CONTRIBUTOR_LEVEL_COUNT:
        raise ValueError("投稿等級設定必須正好包含 10 個等級")

    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    previous_min_exp: int | None = None
    required_keys = {"level", "name", "min_exp"}
    expected_keys = required_keys | {"name_en"}

    for expected_level, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Lv.{expected_level} 設定格式錯誤")
        item_keys = set(item)
        if not required_keys.issubset(item_keys) or not item_keys.issubset(expected_keys):
            raise ValueError(
                f"Lv.{expected_level} 只能包含 level、name、name_en、min_exp"
            )

        level = item["level"]
        if type(level) is not int or level != expected_level:
            raise ValueError("投稿等級 level 必須依序為 1 到 10")

        raw_name = item["name"]
        if not isinstance(raw_name, str):
            raise ValueError(f"Lv.{level} 名稱必須是文字")
        name = raw_name.strip()
        if not name or not _contains_visible_character(name):
            raise ValueError(f"Lv.{level} 名稱不可為空白")
        if len(name) > CONTRIBUTOR_LEVEL_NAME_MAX_LENGTH:
            raise ValueError(
                f"Lv.{level} 名稱不可超過 {CONTRIBUTOR_LEVEL_NAME_MAX_LENGTH} 個字元"
            )
        if name in names:
            raise ValueError("投稿等級名稱不可重複")

        raw_name_en = item.get("name_en")
        if raw_name_en is not None and not isinstance(raw_name_en, str):
            raise ValueError(f"Lv.{level} 英文名稱必須是文字或 null")
        name_en = raw_name_en.strip() if isinstance(raw_name_en, str) else None
        if name_en == "":
            name_en = None
        if name_en is not None:
            if not _contains_visible_character(name_en):
                name_en = None
            elif len(name_en) > CONTRIBUTOR_LEVEL_NAME_MAX_LENGTH:
                raise ValueError(
                    f"Lv.{level} 英文名稱不可超過 "
                    f"{CONTRIBUTOR_LEVEL_NAME_MAX_LENGTH} 個字元"
                )
        if name_en is None:
            name_en = DEFAULT_CONTRIBUTOR_LEVEL_ENGLISH_NAMES.get((level, name))

        min_exp = item["min_exp"]
        if type(min_exp) is not int:
            raise ValueError(f"Lv.{level} 累積 EXP 必須是整數")
        if min_exp < 0:
            raise ValueError(f"Lv.{level} 累積 EXP 不可為負數")
        if level == 1 and min_exp != 0:
            raise ValueError("Lv.1 累積 EXP 必須為 0")
        if previous_min_exp is not None and min_exp <= previous_min_exp:
            raise ValueError("Lv.2 至 Lv.10 累積 EXP 門檻必須嚴格遞增")

        names.add(name)
        previous_min_exp = min_exp
        normalized.append(
            {"level": level, "name": name, "name_en": name_en, "min_exp": min_exp}
        )

    return normalized


def _is_undefined_table_error(exc: ProgrammingError) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current, "pgcode", None
        )
        if sqlstate == "42P01":
            return True
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
    return False


def _default_settings() -> list[dict[str, Any]]:
    return [dict(level) for level in DEFAULT_CONTRIBUTOR_LEVEL_SETTINGS]


@router.get("/contributor-levels", response_model=List[ContributorLevelSettingRead])
async def get_contributor_level_settings(
    db: AsyncSession = Depends(get_session),
):
    try:
        result = await db.execute(
            select(SystemSetting).where(
                SystemSetting.key == CONTRIBUTOR_LEVEL_SETTINGS_KEY
            )
        )
    except ProgrammingError as exc:
        if not _is_undefined_table_error(exc):
            raise
        await db.rollback()
        return _default_settings()

    setting = result.scalar_one_or_none()
    if setting is None:
        return _default_settings()
    return validate_contributor_level_settings(setting.value)


@router.put("/contributor-levels", response_model=List[ContributorLevelSettingRead])
async def update_contributor_level_settings(
    payload: List[dict[str, Any]],
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    try:
        normalized = validate_contributor_level_settings(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    now = datetime.now(timezone.utc)
    statement = (
        postgresql_insert(SystemSetting)
        .values(
            key=CONTRIBUTOR_LEVEL_SETTINGS_KEY,
            value=normalized,
            created_at=now,
            updated_at=now,
            updated_by_id=current_user.user_id,
        )
        .on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={
                "value": normalized,
                "updated_at": now,
                "updated_by_id": current_user.user_id,
            },
        )
    )
    try:
        await db.execute(statement)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return normalized


@router.get("/nthu-access-policy", response_model=NthuAccessPolicyRead)
async def get_nthu_access_policy(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    try:
        policy = await load_nthu_access_policy(db)
    except NthuAccessPolicyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NTHU access policy is invalid",
        ) from exc
    return _nthu_access_policy_response(policy)


@router.put("/nthu-access-policy", response_model=NthuAccessPolicyRead)
async def update_nthu_access_policy(
    payload: dict[str, Any],
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    try:
        policy = await save_nthu_access_policy(
            db,
            payload,
            updated_by_id=current_user.user_id,
        )
        await db.commit()
    except NthuAccessPolicyValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception:
        await db.rollback()
        raise
    return _nthu_access_policy_response(policy)
