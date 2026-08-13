import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)
from app.main import app
from app.models.models import Archive, User
from app.utils.auth import get_password_hash

RUNTIME_DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=settings.DB_USER,
    password=settings.DB_PASSWORD,
    host=settings.DB_HOST,
    port=settings.DB_PORT,
    database=settings.DB_NAME,
).render_as_string(hide_password=False)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_ALLOWED_HOSTS = os.getenv(
    "TEST_DATABASE_ALLOWED_HOSTS",
    "127.0.0.1,localhost,db",
)


try:
    TEST_DATABASE_TARGET = validate_test_database_target(
        test_database_url=TEST_DATABASE_URL,
        runtime_database_url=RUNTIME_DATABASE_URL,
        isolation_confirmed=os.getenv("PASTEXAM_TEST_DATABASE_ISOLATED"),
        allowed_hosts=TEST_DATABASE_ALLOWED_HOSTS.split(","),
    )
except (TypeError, ValueError):
    pytest.exit(
        "Refusing to run backend tests without an explicit, isolated TEST_DATABASE_URL. "
        "The database and role names must start with 'pastexam_test_', "
        "the host must be explicitly allowed, and "
        "PASTEXAM_TEST_DATABASE_ISOLATED=true is required.",
        returncode=2,
    )

DATABASE_URL = TEST_DATABASE_URL


@pytest.fixture(scope="session")
def event_loop() -> AsyncIterator[asyncio.AbstractEventLoop]:
    """Provide a single event loop for all async tests."""
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest_asyncio.fixture(autouse=True)
async def override_db_session(monkeypatch):
    """Swap engine per run to dodge asyncpg loop clashes."""
    engine = create_async_engine(
        DATABASE_URL,
        poolclass=NullPool,
        future=True,
    )
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    async with engine.connect() as connection:
        (
            actual_database_name,
            actual_user_name,
            actual_database_owner,
            is_superuser,
            can_create_database,
            can_create_role,
        ) = (
            await connection.execute(
                text(
                    "SELECT current_database(), current_user, "
                    "pg_get_userbyid(database.datdba), "
                    "role.rolsuper, role.rolcreatedb, role.rolcreaterole "
                    "FROM pg_database AS database "
                    "JOIN pg_roles AS role ON role.rolname = current_user "
                    "WHERE database.datname = current_database()"
                )
            )
        ).one()
    try:
        validate_connected_test_database(
            actual_database_name=actual_database_name,
            actual_user_name=actual_user_name,
            actual_database_owner=actual_database_owner,
            is_superuser=is_superuser,
            can_create_database=can_create_database,
            can_create_role=can_create_role,
            target=TEST_DATABASE_TARGET,
        )
    except ValueError:
        await engine.dispose()
        pytest.fail("Connected database is not an isolated test database", pytrace=False)

    monkeypatch.setattr("app.db.session.engine", engine)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", session_maker)

    yield

    await engine.dispose()


@pytest.fixture()
def session_maker():
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


@pytest_asyncio.fixture
async def make_user(session_maker):
    """Factory fixture to create and cleanup test users."""
    created_ids: list[int] = []

    async def _make_user(**overrides):
        password = overrides.pop("password", "StrongPass123!")
        base = {
            "name": f"user-{uuid.uuid4().hex[:8]}",
            "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
            "password_hash": get_password_hash(password),
            "is_local": True,
            "is_admin": False,
        }

        if "password_hash" in overrides:
            base["password_hash"] = overrides.pop("password_hash")

        base.update(overrides)

        async with session_maker() as session:
            user = User(**base)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        created_ids.append(user.id)

        class _TestUser:
            __slots__ = ("_model", "password")

            def __init__(self, model: User, password_plain: str):
                self._model = model
                self.password = password_plain

            def __getattr__(self, item):
                return getattr(self._model, item)

            @property
            def model(self) -> User:
                return self._model

        return _TestUser(user, password)

    yield _make_user

    if created_ids:
        async with session_maker() as session:
            await session.execute(
                delete(Archive).where(Archive.uploader_id.in_(created_ids))
            )
            await session.execute(delete(User).where(User.id.in_(created_ids)))
            await session.commit()


@pytest_asyncio.fixture()
async def client(monkeypatch) -> AsyncIterator[AsyncClient]:
    """Return an AsyncClient backed by the FastAPI app."""
    monkeypatch.setattr("app.main.init_db", AsyncMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client
