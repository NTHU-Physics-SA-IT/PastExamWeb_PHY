"""Theme catalog and single-active site-theme persistence."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    ActiveThemeRead,
    FestivalThemeCapabilityRead,
    FestivalThemeRead,
    FestivalThemeUpdateRequest,
    GeneralThemeCapabilityRead,
    GeneralThemeMode,
    SystemSetting,
    ThemeManagementRead,
)

GENERAL_THEME_ID = "general"
CHRISTMAS_THEME_ID = "christmas"
ACTIVE_THEME_SETTING_KEY = "active_theme_id"
FESTIVAL_THEME_CATALOG_SETTING_KEY = "festival_theme_catalog"

SUPPORTED_GENERAL_THEME_MODES = (
    GeneralThemeMode.LIGHT,
    GeneralThemeMode.DARK,
)

# Festival presentation packages remain code-owned. The JSONB catalog setting is
# written only after an administrator edits or removes one of these defaults.
REGISTERED_FESTIVAL_THEMES: tuple[FestivalThemeRead, ...] = (
    FestivalThemeRead(
        id=CHRISTMAS_THEME_ID,
        name="聖誕模式",
        name_en="Christmas Theme",
        description="這是專門為聖誕節準備的主題，只會在聖誕節使用。",
        description_en=(
            "A theme prepared especially for Christmas and used only during Christmas."
        ),
        supports_color_modes=False,
        starts_at=None,
        ends_at=None,
    ),
)


class ThemeNotFoundError(ValueError):
    """Raised when an administrator targets an unavailable theme."""


class ActiveThemeDeletionError(ValueError):
    """Raised when an administrator attempts to delete the active theme."""


class InvalidThemeMetadataError(ValueError):
    """Raised when merged theme metadata violates the catalog contract."""


def _registered_theme_ids(themes: tuple[FestivalThemeRead, ...]) -> set[str]:
    return {GENERAL_THEME_ID} | {theme.id for theme in themes}


def _resolved_active_theme_id(
    active_theme_id: str | None,
    themes: tuple[FestivalThemeRead, ...],
) -> str:
    return (
        active_theme_id
        if active_theme_id in _registered_theme_ids(themes)
        else GENERAL_THEME_ID
    )


def _capabilities(
    active_theme_id: str | None,
    themes: tuple[FestivalThemeRead, ...],
) -> ThemeManagementRead:
    active = _resolved_active_theme_id(active_theme_id, themes)
    return ThemeManagementRead(
        general_theme=GeneralThemeCapabilityRead(
            active=active == GENERAL_THEME_ID,
            user_selectable=True,
            supported_modes=list(SUPPORTED_GENERAL_THEME_MODES),
        ),
        festival_theme=FestivalThemeCapabilityRead(
            active=active if active != GENERAL_THEME_ID else None,
            themes=list(themes),
        ),
    )


async def _read_setting(db: AsyncSession, key: str) -> SystemSetting | None:
    return await db.scalar(select(SystemSetting).where(SystemSetting.key == key))


async def _read_active_theme_id(db: AsyncSession) -> str | None:
    setting = await _read_setting(db, ACTIVE_THEME_SETTING_KEY)
    return (
        setting.value
        if setting is not None and isinstance(setting.value, str)
        else None
    )


async def _read_festival_themes(db: AsyncSession) -> tuple[FestivalThemeRead, ...]:
    setting = await _read_setting(db, FESTIVAL_THEME_CATALOG_SETTING_KEY)
    if setting is None:
        return REGISTERED_FESTIVAL_THEMES
    if not isinstance(setting.value, list):
        return REGISTERED_FESTIVAL_THEMES
    try:
        themes = tuple(FestivalThemeRead.model_validate(value) for value in setting.value)
    except (TypeError, ValueError):
        return REGISTERED_FESTIVAL_THEMES
    if len({theme.id for theme in themes}) != len(themes):
        return REGISTERED_FESTIVAL_THEMES
    return themes


def _setting_upsert(*, key: str, value: object, updated_by_id: int):
    now = datetime.now(UTC)
    return (
        postgresql_insert(SystemSetting)
        .values(
            key=key,
            value=value,
            created_at=now,
            updated_at=now,
            updated_by_id=updated_by_id,
        )
        .on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={
                "value": value,
                "updated_at": now,
                "updated_by_id": updated_by_id,
            },
        )
    )


async def read_theme_management_capabilities(db: AsyncSession) -> ThemeManagementRead:
    """Describe supported themes without owning the user's base preference."""
    themes = await _read_festival_themes(db)
    return _capabilities(await _read_active_theme_id(db), themes)


async def read_active_theme(db: AsyncSession) -> ActiveThemeRead:
    """Expose only the resolved site-wide active theme to public clients."""
    themes = await _read_festival_themes(db)
    return ActiveThemeRead(
        active_theme=_resolved_active_theme_id(await _read_active_theme_id(db), themes)
    )


async def activate_theme(
    db: AsyncSession,
    *,
    theme_id: str,
    updated_by_id: int,
) -> ThemeManagementRead:
    """Persist one available active theme; selecting the same theme is a no-op."""
    themes = await _read_festival_themes(db)
    if theme_id not in _registered_theme_ids(themes):
        raise ThemeNotFoundError(theme_id)

    current_theme_id = _resolved_active_theme_id(await _read_active_theme_id(db), themes)
    if current_theme_id == theme_id:
        return _capabilities(theme_id, themes)

    try:
        await db.execute(
            _setting_upsert(
                key=ACTIVE_THEME_SETTING_KEY,
                value=theme_id,
                updated_by_id=updated_by_id,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _capabilities(theme_id, themes)


async def update_festival_theme(
    db: AsyncSession,
    *,
    theme_id: str,
    payload: FestivalThemeUpdateRequest,
    updated_by_id: int,
) -> ThemeManagementRead:
    """Persist editable festival metadata without changing presentation support."""
    themes = await _read_festival_themes(db)
    index = next(
        (index for index, theme in enumerate(themes) if theme.id == theme_id),
        None,
    )
    if index is None:
        raise ThemeNotFoundError(theme_id)

    changes = payload.model_dump(exclude_unset=True)
    current = themes[index]
    try:
        updated = FestivalThemeRead.model_validate(
            {**current.model_dump(), **changes}
        )
    except ValueError as exc:
        raise InvalidThemeMetadataError(theme_id) from exc
    if updated == current:
        return _capabilities(await _read_active_theme_id(db), themes)

    next_themes = list(themes)
    next_themes[index] = updated
    stored_catalog = [theme.model_dump(mode="json") for theme in next_themes]
    try:
        await db.execute(
            _setting_upsert(
                key=FESTIVAL_THEME_CATALOG_SETTING_KEY,
                value=stored_catalog,
                updated_by_id=updated_by_id,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _capabilities(await _read_active_theme_id(db), tuple(next_themes))


async def delete_festival_theme(
    db: AsyncSession,
    *,
    theme_id: str,
    updated_by_id: int,
) -> ThemeManagementRead:
    """Delete inactive catalog metadata; the active presentation fails closed."""
    themes = await _read_festival_themes(db)
    if theme_id not in {theme.id for theme in themes}:
        raise ThemeNotFoundError(theme_id)
    active_theme_id = _resolved_active_theme_id(await _read_active_theme_id(db), themes)
    if active_theme_id == theme_id:
        raise ActiveThemeDeletionError(theme_id)

    next_themes = tuple(theme for theme in themes if theme.id != theme_id)
    stored_catalog = [theme.model_dump(mode="json") for theme in next_themes]
    try:
        await db.execute(
            _setting_upsert(
                key=FESTIVAL_THEME_CATALOG_SETTING_KEY,
                value=stored_catalog,
                updated_by_id=updated_by_id,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _capabilities(active_theme_id, next_themes)
