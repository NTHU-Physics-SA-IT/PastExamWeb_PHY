from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.maintenance import minio_orphan_cleanup


def test_operator_client_requires_separate_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MINIO_OPERATOR_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_OPERATOR_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="operator credentials"):
        minio_orphan_cleanup.get_operator_minio_client()


def test_operator_client_uses_only_explicit_operator_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}
    sentinel = object()
    monkeypatch.setenv("MINIO_OPERATOR_ACCESS_KEY", "operator-access")
    monkeypatch.setenv("MINIO_OPERATOR_SECRET_KEY", "operator-secret")

    def construct(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(minio_orphan_cleanup, "Minio", construct)

    assert minio_orphan_cleanup.get_operator_minio_client() is sentinel
    assert captured == {
        "endpoint": minio_orphan_cleanup.settings.MINIO_ENDPOINT,
        "access_key": "operator-access",
        "secret_key": "operator-secret",
        "secure": False,
    }


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
