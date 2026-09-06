"""Public active-theme read and administrator theme-management contracts."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import (
    ActiveThemeRead,
    FestivalThemeUpdateRequest,
    ThemeActivationRequest,
    ThemeManagementRead,
    UserRoles,
)
from app.services.theme_management import (
    ActiveThemeDeletionError,
    InvalidThemeMetadataError,
    ThemeNotFoundError,
    activate_theme,
    delete_festival_theme,
    read_active_theme,
    read_theme_management_capabilities,
    update_festival_theme,
)
from app.utils.auth import get_current_user

router = APIRouter()


def _require_admin(current_user: UserRoles) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


@router.get("/theme-management/active-theme", response_model=ActiveThemeRead)
async def get_active_theme(db: AsyncSession = Depends(get_session)):
    return await read_active_theme(db)


@router.get("/admin/theme-management", response_model=ThemeManagementRead)
async def get_theme_management_capabilities(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    return await read_theme_management_capabilities(db)


@router.patch(
    "/admin/theme-management/active-theme",
    response_model=ThemeManagementRead,
)
async def set_active_theme(
    payload: ThemeActivationRequest,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    try:
        return await activate_theme(
            db,
            theme_id=payload.theme_id,
            updated_by_id=current_user.user_id,
        )
    except ThemeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        ) from exc


@router.patch(
    "/admin/theme-management/themes/{theme_id}",
    response_model=ThemeManagementRead,
)
async def update_theme(
    theme_id: str,
    payload: FestivalThemeUpdateRequest,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    try:
        return await update_festival_theme(
            db,
            theme_id=theme_id,
            payload=payload,
            updated_by_id=current_user.user_id,
        )
    except ThemeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        ) from exc
    except InvalidThemeMetadataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid theme metadata",
        ) from exc


@router.delete(
    "/admin/theme-management/themes/{theme_id}",
    response_model=ThemeManagementRead,
)
async def delete_theme(
    theme_id: str,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    try:
        return await delete_festival_theme(
            db,
            theme_id=theme_id,
            updated_by_id=current_user.user_id,
        )
    except ThemeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        ) from exc
    except ActiveThemeDeletionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deactivate theme before deletion",
        ) from exc
