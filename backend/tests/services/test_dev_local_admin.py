from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlmodel import select

from app.core.config import settings
from app.models.models import User, UserPresenceSession
from app.scripts import ensure_local_admin_qa
from app.services.dev_local_admin import (
    DEV_LOCAL_ADMIN_EMAIL,
    DEV_LOCAL_ADMIN_NAME,
    DEV_LOCAL_ADMIN_NICKNAME,
    ensure_dev_local_admin,
)


@pytest.fixture(autouse=True)
async def clean_dev_local_admin(session_maker):
    async with session_maker() as session:
        fixture_user = await session.scalar(
            select(User).where(User.email == DEV_LOCAL_ADMIN_EMAIL)
        )
        if fixture_user is not None:
            await session.execute(
                delete(UserPresenceSession).where(
                    UserPresenceSession.user_id == fixture_user.id
                )
            )
            await session.delete(fixture_user)
            await session.commit()
    yield
    async with session_maker() as session:
        fixture_user = await session.scalar(
            select(User).where(User.email == DEV_LOCAL_ADMIN_EMAIL)
        )
        if fixture_user is not None:
            await session.execute(
                delete(UserPresenceSession).where(
                    UserPresenceSession.user_id == fixture_user.id
                )
            )
            await session.delete(fixture_user)
            await session.commit()


@pytest.mark.asyncio
async def test_fixture_is_idempotent_and_uses_normal_local_login(
    client,
    session_maker,
) -> None:
    async with session_maker() as session:
        first = await ensure_dev_local_admin(
            session,
            environment="test",
            password="First-QA-Password-123!",
        )
        await session.commit()
        assert first.created is True

    async with session_maker() as session:
        second = await ensure_dev_local_admin(
            session,
            environment="test",
            password="Second-QA-Password-456!",
        )
        await session.commit()
        assert second.created is False
        assert second.user.is_local is True
        assert second.user.is_admin is True

    old_password = await client.post(
        "/auth/login",
        data={"username": DEV_LOCAL_ADMIN_NAME, "password": "First-QA-Password-123!"},
    )
    assert old_password.status_code == 401

    response = await client.post(
        "/auth/login",
        data={"username": DEV_LOCAL_ADMIN_NAME, "password": "Second-QA-Password-456!"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.asyncio
async def test_fixture_refuses_production_before_database_access() -> None:
    class FailOnAccess:
        async def execute(self, statement):
            raise AssertionError("production guard must run before database access")

    with pytest.raises(RuntimeError, match="development or test"):
        await ensure_dev_local_admin(
            FailOnAccess(),
            environment="production",
            password="Never-Used-Password-123!",
        )


@pytest.mark.asyncio
async def test_fixture_requires_an_explicit_password_before_database_access() -> None:
    class FailOnAccess:
        async def execute(self, statement):
            raise AssertionError("password guard must run before database access")

    with pytest.raises(RuntimeError, match="DEV_QA_ADMIN_PASSWORD must be set"):
        await ensure_dev_local_admin(
            FailOnAccess(),
            environment="development",
            password="",
        )


@pytest.mark.asyncio
async def test_fixture_refuses_identity_collision_without_modifying_user(
    session_maker,
) -> None:
    async with session_maker() as session:
        unrelated = User(
            name=DEV_LOCAL_ADMIN_NAME,
            nickname="Existing administrator",
            email="existing-admin@example.invalid",
            password_hash="unchanged-hash",
            is_local=True,
            is_admin=False,
        )
        session.add(unrelated)
        await session.commit()
        unrelated_id = unrelated.id

    async with session_maker() as session:
        with pytest.raises(RuntimeError, match="conflicts with an existing user"):
            await ensure_dev_local_admin(
                session,
                environment="development",
                password="Never-Applied-Password-123!",
            )
        await session.rollback()

    async with session_maker() as session:
        unchanged = await session.get(User, unrelated_id)
        assert unchanged is not None
        assert unchanged.email == "existing-admin@example.invalid"
        assert unchanged.nickname == "Existing administrator"
        assert unchanged.password_hash == "unchanged-hash"
        assert unchanged.is_admin is False
        await session.delete(unchanged)
        await session.commit()


def test_fixture_identity_is_explicitly_development_only() -> None:
    assert DEV_LOCAL_ADMIN_NAME == "dev-local-admin"
    assert DEV_LOCAL_ADMIN_EMAIL == "dev-local-admin@example.invalid"
    assert DEV_LOCAL_ADMIN_NICKNAME == "[DEV] Local Admin QA"


@pytest.mark.asyncio
async def test_cli_refuses_production_before_schema_or_database_access(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_QA_ADMIN_PASSWORD", "Never-Used-Password-123!")
    monkeypatch.setattr(
        ensure_local_admin_qa,
        "validate_database_ready",
        lambda: pytest.fail("production guard must run before schema access"),
    )

    with pytest.raises(RuntimeError, match="development or test"):
        await ensure_local_admin_qa.main()
