from __future__ import annotations

import asyncio
import os

from app.core.config import settings
from app.db.init_db import validate_database_ready
from app.db.session import AsyncSessionLocal
from app.services.dev_local_admin import ensure_dev_local_admin


async def main() -> None:
    password = os.getenv("DEV_QA_ADMIN_PASSWORD", "")
    if settings.APP_ENVIRONMENT.strip().lower() not in {"development", "test"}:
        raise RuntimeError(
            "The local admin QA fixture is available only in development or test"
        )
    if not password:
        raise RuntimeError("DEV_QA_ADMIN_PASSWORD must be set")

    await asyncio.to_thread(validate_database_ready)
    async with AsyncSessionLocal() as session:
        result = await ensure_dev_local_admin(
            session,
            environment=settings.APP_ENVIRONMENT,
            password=password,
        )
        await session.commit()
        print(
            "Local admin QA fixture "
            + ("created" if result.created else "updated")
            + ": dev-local-admin"
        )


if __name__ == "__main__":
    asyncio.run(main())
