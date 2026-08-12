from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import User
from app.utils.auth import get_password_hash


DEV_LOCAL_ADMIN_NAME = "dev-local-admin"
DEV_LOCAL_ADMIN_EMAIL = "dev-local-admin@example.invalid"
DEV_LOCAL_ADMIN_NICKNAME = "[DEV] Local Admin QA"
DEV_LOCAL_ADMIN_ENVIRONMENTS = frozenset({"development", "test"})


@dataclass(frozen=True)
class DevLocalAdminResult:
    user: User
    created: bool


def validate_dev_local_admin_request(*, environment: str, password: str) -> None:
    if environment.strip().lower() not in DEV_LOCAL_ADMIN_ENVIRONMENTS:
        raise RuntimeError(
            "The local admin QA fixture is available only in development or test"
        )
    if not isinstance(password, str) or not password:
        raise RuntimeError("DEV_QA_ADMIN_PASSWORD must be set")


async def ensure_dev_local_admin(
    session: AsyncSession,
    *,
    environment: str,
    password: str,
) -> DevLocalAdminResult:
    validate_dev_local_admin_request(environment=environment, password=password)

    matches = (
        (
            await session.execute(
                select(User).where(
                    or_(
                        User.name == DEV_LOCAL_ADMIN_NAME,
                        User.email == DEV_LOCAL_ADMIN_EMAIL,
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    if not matches:
        user = User(
            name=DEV_LOCAL_ADMIN_NAME,
            nickname=DEV_LOCAL_ADMIN_NICKNAME,
            email=DEV_LOCAL_ADMIN_EMAIL,
            password_hash=get_password_hash(password),
            is_local=True,
            is_admin=True,
        )
        session.add(user)
        await session.flush()
        return DevLocalAdminResult(user=user, created=True)

    if len(matches) != 1:
        raise RuntimeError(
            "The local admin QA fixture identity conflicts with multiple users"
        )

    user = matches[0]
    if (
        user.name != DEV_LOCAL_ADMIN_NAME
        or user.email != DEV_LOCAL_ADMIN_EMAIL
        or user.nickname != DEV_LOCAL_ADMIN_NICKNAME
        or user.oauth_provider is not None
        or user.oauth_sub is not None
    ):
        raise RuntimeError(
            "The local admin QA fixture identity conflicts with an existing user"
        )

    user.password_hash = get_password_hash(password)
    user.is_local = True
    user.is_admin = True
    user.student_id = None
    user.deleted_at = None
    await session.flush()
    return DevLocalAdminResult(user=user, created=False)
