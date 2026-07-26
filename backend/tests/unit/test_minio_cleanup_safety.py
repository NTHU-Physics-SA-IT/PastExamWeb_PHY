from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.maintenance import minio_orphan_cleanup


@pytest.mark.asyncio
async def test_cleanup_apply_is_blocked_in_recovery_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AsyncMock()
    monkeypatch.setattr(minio_orphan_cleanup, "run_audit", audit)
    monkeypatch.setattr(
        minio_orphan_cleanup.settings,
        "RECOVERY_REVIEW_MODE",
        True,
    )

    with pytest.raises(RuntimeError, match="Recovery Review"):
        await minio_orphan_cleanup.run_cleanup(
            apply=True,
            confirmed_database_name=minio_orphan_cleanup.settings.DB_NAME,
            confirmed_bucket_name=minio_orphan_cleanup.settings.MINIO_BUCKET_NAME,
        )

    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_apply_requires_exact_database_and_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AsyncMock()
    monkeypatch.setattr(minio_orphan_cleanup, "run_audit", audit)

    with pytest.raises(RuntimeError, match="database confirmation"):
        await minio_orphan_cleanup.run_cleanup(apply=True)
    with pytest.raises(RuntimeError, match="bucket confirmation"):
        await minio_orphan_cleanup.run_cleanup(
            apply=True,
            confirmed_database_name=minio_orphan_cleanup.settings.DB_NAME,
        )

    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_apply_checks_schema_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = AsyncMock()
    monkeypatch.setattr(minio_orphan_cleanup, "run_audit", audit)
    monkeypatch.setattr(
        minio_orphan_cleanup,
        "validate_database_ready",
        lambda: (_ for _ in ()).throw(RuntimeError("schema invalid")),
    )

    with pytest.raises(RuntimeError, match="schema invalid"):
        await minio_orphan_cleanup.run_cleanup(
            apply=True,
            confirmed_database_name=minio_orphan_cleanup.settings.DB_NAME,
            confirmed_bucket_name=minio_orphan_cleanup.settings.MINIO_BUCKET_NAME,
        )

    audit.assert_not_awaited()
