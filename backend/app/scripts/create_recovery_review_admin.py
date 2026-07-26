import argparse
import asyncio

from sqlmodel import select

from app.core.config import settings
from app.db.init_db import validate_database_ready
from app.db.session import AsyncSessionLocal
from app.models.models import User
from app.utils.auth import get_password_hash


async def create_review_admin(*, confirmed_database_name: str) -> None:
    if not settings.RECOVERY_REVIEW_MODE:
        raise RuntimeError("RECOVERY_REVIEW_MODE=true is required")
    if confirmed_database_name != settings.DB_NAME:
        raise RuntimeError("Database confirmation does not match DB_NAME")
    if not settings.DB_NAME.startswith("archive_db_recovery_review_"):
        raise RuntimeError("Recovery Review database name is not isolated")
    if not settings.RECOVERY_REVIEW_ADMIN_NAME:
        raise RuntimeError("RECOVERY_REVIEW_ADMIN_NAME is required")
    if settings.DEFAULT_ADMIN_NAME != settings.RECOVERY_REVIEW_ADMIN_NAME:
        raise RuntimeError("Review admin identity settings do not match")

    await asyncio.to_thread(validate_database_ready)

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(User).where(User.name == settings.RECOVERY_REVIEW_ADMIN_NAME)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.email != settings.DEFAULT_ADMIN_EMAIL:
                raise RuntimeError(
                    "Review admin username already belongs to recovered data"
                )
            existing.password_hash = get_password_hash(
                settings.DEFAULT_ADMIN_PASSWORD
            )
            existing.is_local = True
            existing.is_admin = True
            existing.deleted_at = None
        else:
            email_conflict = (
                await session.execute(
                    select(User).where(User.email == settings.DEFAULT_ADMIN_EMAIL)
                )
            ).scalar_one_or_none()
            if email_conflict is not None:
                raise RuntimeError(
                    "Review admin email already belongs to recovered data"
                )
            session.add(
                User(
                    name=settings.RECOVERY_REVIEW_ADMIN_NAME,
                    email=settings.DEFAULT_ADMIN_EMAIL,
                    password_hash=get_password_hash(
                        settings.DEFAULT_ADMIN_PASSWORD
                    ),
                    is_local=True,
                    is_admin=True,
                )
            )
        await session.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the isolated local Recovery Review administrator."
    )
    parser.add_argument("--confirm-database-name", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        create_review_admin(
            confirmed_database_name=args.confirm_database_name
        )
    )
