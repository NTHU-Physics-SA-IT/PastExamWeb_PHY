from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.main import app
from app.maintenance import permanent_deletion_reconciler as worker
from app.models.models import (
    Notification,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
)
from app.services import permanent_deletion_reconciler as reconciler_service
from app.services.permanent_deletion import accept_permanent_deletion
from app.services.permanent_deletion_reconciler import (
    purge_completed_audits,
    reconcile_due_once,
    select_due_operation_ids,
)

NOW = datetime(2026, 8, 28, 4, 0, tzinfo=UTC)


def _operation(
    marker: str,
    *,
    status: PermanentDeletionStatus,
    accepted_at: datetime,
    next_attempt_at: datetime | None = None,
    lease_token: str | None = None,
    lease_expires_at: datetime | None = None,
    completed_at: datetime | None = None,
    audit_purge_after: datetime | None = None,
) -> PermanentDeletionOperation:
    return PermanentDeletionOperation(
        root_entity_type="notification",
        root_entity_id=abs(hash(marker)) % 1_000_000 + 1,
        idempotency_key=f"stage5fe:{marker}",
        status=status,
        accepted_at=accepted_at,
        completed_at=completed_at,
        retry_deadline_at=accepted_at + timedelta(hours=24),
        next_attempt_at=next_attempt_at,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        audit_purge_after=audit_purge_after,
        created_at=accepted_at,
        updated_at=accepted_at,
    )


@pytest.mark.asyncio
async def test_due_selector_enforces_state_time_lease_order_and_limit(
    session_maker,
) -> None:
    rows = {
        "accepted_old": _operation(
            "accepted-old",
            status=PermanentDeletionStatus.ACCEPTED,
            accepted_at=NOW - timedelta(hours=4),
            next_attempt_at=NOW - timedelta(hours=3),
        ),
        "verification": _operation(
            "verification",
            status=PermanentDeletionStatus.VERIFICATION_REQUIRED,
            accepted_at=NOW - timedelta(hours=3),
            next_attempt_at=NOW + timedelta(hours=1),
        ),
        "retry_early": _operation(
            "retry-early",
            status=PermanentDeletionStatus.RETRYABLE_FAILED,
            accepted_at=NOW - timedelta(hours=2),
            next_attempt_at=NOW + timedelta(seconds=1),
        ),
        "retry_due": _operation(
            "retry-due",
            status=PermanentDeletionStatus.RETRYABLE_FAILED,
            accepted_at=NOW - timedelta(hours=2),
            next_attempt_at=NOW,
        ),
        "processing_fresh": _operation(
            "processing-fresh",
            status=PermanentDeletionStatus.PROCESSING,
            accepted_at=NOW - timedelta(hours=1),
            lease_token="fresh",
            lease_expires_at=NOW + timedelta(seconds=1),
        ),
        "processing_expired": _operation(
            "processing-expired",
            status=PermanentDeletionStatus.PROCESSING,
            accepted_at=NOW - timedelta(hours=1),
            lease_token="expired",
            lease_expires_at=NOW - timedelta(minutes=30),
        ),
        "manual": _operation(
            "manual",
            status=PermanentDeletionStatus.MANUAL_REVIEW,
            accepted_at=NOW - timedelta(days=2),
        ),
        "completed": _operation(
            "completed",
            status=PermanentDeletionStatus.COMPLETED,
            accepted_at=NOW - timedelta(days=200),
            completed_at=NOW - timedelta(days=181),
            audit_purge_after=NOW - timedelta(days=1),
        ),
    }
    async with session_maker() as session:
        session.add_all(rows.values())
        await session.commit()
        for row in rows.values():
            await session.refresh(row)

    async with session_maker() as session:
        selected = await select_due_operation_ids(session, now=NOW, limit=3)
        all_due = await select_due_operation_ids(session, now=NOW, limit=20)

    assert selected == [
        rows["accepted_old"].id,
        rows["verification"].id,
        rows["processing_expired"].id,
    ]
    assert all_due == selected + [rows["retry_due"].id]
    async with session_maker() as session:
        await session.execute(
            delete(PermanentDeletionOperation).where(
                PermanentDeletionOperation.id.in_(
                    [int(row.id) for row in rows.values()]
                )
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_reconcile_due_once_is_item_independent_and_storage_lazy(
    session_maker,
) -> None:
    first = _operation(
        "independent-first",
        status=PermanentDeletionStatus.ACCEPTED,
        accepted_at=NOW - timedelta(minutes=2),
        next_attempt_at=NOW - timedelta(minutes=2),
    )
    second = _operation(
        "independent-second",
        status=PermanentDeletionStatus.ACCEPTED,
        accepted_at=NOW - timedelta(minutes=1),
        next_attempt_at=NOW - timedelta(minutes=1),
    )
    async with session_maker() as session:
        session.add_all([first, second])
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)

    called: list[int] = []

    async def processor(db, *, operation_id, storage_factory, event_clock):
        called.append(operation_id)
        assert storage_factory is forbidden_storage_factory
        assert event_clock() > NOW
        if operation_id == first.id:
            raise RuntimeError("sanitized by reconciler")
        return PermanentDeletionStatus.COMPLETED

    def forbidden_storage_factory():
        raise AssertionError("DB-only operation initialized MinIO")

    summary = await reconcile_due_once(
        session_maker=session_maker,
        storage_factory=forbidden_storage_factory,
        now=NOW,
        event_clock=iter(
            [NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)]
        ).__next__,
        operation_limit=10,
        purge_limit=10,
        processor=processor,
    )

    assert called == [first.id, second.id]
    assert summary.candidates == 2
    assert summary.processed == 1
    assert summary.completed == 1
    assert summary.errors == 1
    async with session_maker() as session:
        await session.execute(
            delete(PermanentDeletionOperation).where(
                PermanentDeletionOperation.id.in_([int(first.id), int(second.id)])
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_completed_audit_purge_is_due_only_bounded_and_idempotent(
    session_maker,
) -> None:
    due_first = _operation(
        "purge-first",
        status=PermanentDeletionStatus.COMPLETED,
        accepted_at=NOW - timedelta(days=220),
        completed_at=NOW - timedelta(days=190),
        audit_purge_after=NOW - timedelta(days=10),
    )
    due_second = _operation(
        "purge-second",
        status=PermanentDeletionStatus.COMPLETED,
        accepted_at=NOW - timedelta(days=210),
        completed_at=NOW - timedelta(days=181),
        audit_purge_after=NOW,
    )
    retained_completed = _operation(
        "purge-future",
        status=PermanentDeletionStatus.COMPLETED,
        accepted_at=NOW - timedelta(days=30),
        completed_at=NOW - timedelta(days=1),
        audit_purge_after=NOW + timedelta(days=179),
    )
    unfinished_old = _operation(
        "purge-unfinished",
        status=PermanentDeletionStatus.MANUAL_REVIEW,
        accepted_at=NOW - timedelta(days=400),
    )
    async with session_maker() as session:
        session.add_all([due_first, due_second, retained_completed, unfinished_old])
        await session.flush()
        session.add(
            PermanentDeletionTarget(
                operation_id=int(due_first.id),
                entity_type="notification",
                entity_id=due_first.root_entity_id,
                target_role="delete",
                reservation_released_at=due_first.completed_at,
                created_at=due_first.accepted_at,
            )
        )
        await session.commit()
        ids = [int(row.id) for row in [due_first, due_second, retained_completed, unfinished_old]]

    assert await purge_completed_audits(session_maker, now=NOW, limit=1) == 1
    assert await purge_completed_audits(session_maker, now=NOW, limit=10) == 1
    assert await purge_completed_audits(session_maker, now=NOW, limit=10) == 0

    async with session_maker() as session:
        remaining = set(
            (await session.execute(select(PermanentDeletionOperation.id).where(PermanentDeletionOperation.id.in_(ids)))).scalars()
        )
    assert remaining == {retained_completed.id, unfinished_old.id}
    async with session_maker() as session:
        await session.execute(
            delete(PermanentDeletionOperation).where(
                PermanentDeletionOperation.id.in_(list(remaining))
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_worker_shutdown_prevents_another_pass() -> None:
    stop = asyncio.Event()
    calls = 0

    async def one_pass(**_kwargs):
        nonlocal calls
        calls += 1
        stop.set()

    await worker.run_worker(
        stop_event=stop,
        poll_interval_seconds=30.0,
        operation_batch_limit=10,
        purge_batch_limit=10,
        reconcile=one_pass,
    )

    assert calls == 1


@pytest.mark.asyncio
async def test_worker_waits_after_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    waits: list[float] = []

    async def failed_pass(**_kwargs):
        raise ConnectionError("database unavailable")

    async def fake_wait_for(awaitable, *, timeout):
        waits.append(timeout)
        awaitable.close()
        stop.set()

    monkeypatch.setattr(worker.asyncio, "wait_for", fake_wait_for)
    await worker.run_worker(
        stop_event=stop,
        poll_interval_seconds=30.0,
        operation_batch_limit=10,
        purge_batch_limit=10,
        reconcile=failed_pass,
    )

    assert waits == [30.0]


def test_fastapi_startup_does_not_register_reconciler() -> None:
    assert all(
        callback.__module__ != worker.__name__ for callback in app.router.on_startup
    )


def test_worker_configuration_rejects_non_positive_or_unbounded_values() -> None:
    with pytest.raises(SystemExit):
        worker.parse_args(["--poll-interval-seconds", "0"])
    with pytest.raises(SystemExit):
        worker.parse_args(["--operation-batch-limit", "1001"])
    with pytest.raises(SystemExit):
        worker.parse_args(["--purge-batch-limit", "-1"])


@pytest.mark.asyncio
async def test_purge_failure_does_not_undo_processed_candidate(
    session_maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation(
        "purge-independent",
        status=PermanentDeletionStatus.ACCEPTED,
        accepted_at=NOW - timedelta(minutes=1),
        next_attempt_at=NOW - timedelta(minutes=1),
    )
    async with session_maker() as session:
        session.add(operation)
        await session.commit()
        await session.refresh(operation)

    async def processor(_db, **_kwargs):
        return PermanentDeletionStatus.COMPLETED

    async def failed_purge(*_args, **_kwargs):
        raise RuntimeError("purge unavailable")

    monkeypatch.setattr(reconciler_service, "purge_completed_audits", failed_purge)
    summary = await reconcile_due_once(
        session_maker=session_maker,
        storage_factory=lambda: None,
        now=NOW,
        processor=processor,
    )

    assert summary.processed == 1
    assert summary.completed == 1
    assert summary.purge_errors == 1
    async with session_maker() as session:
        await session.execute(
            delete(PermanentDeletionOperation).where(
                PermanentDeletionOperation.id == operation.id
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_db_only_reconciler_completes_without_minio(
    session_maker,
    make_user,
) -> None:
    admin = await make_user(is_admin=True)
    async with session_maker() as session:
        bulletin = Notification(
            title="Stage 5F-E DB-only reconciliation",
            body="No storage dependency",
            deleted_at=NOW - timedelta(minutes=5),
            deleted_by_id=admin.id,
        )
        session.add(bulletin)
        await session.commit()
        await session.refresh(bulletin)
        operation = await accept_permanent_deletion(
            session,
            root_entity_type="notification",
            root_entity_id=int(bulletin.id),
            idempotency_key=f"stage5fe:db-only:{bulletin.id}",
            requested_by_user_id=admin.id,
            storage=None,
            now=NOW,
        )
        operation_id = int(operation.id)

    def forbidden_storage_factory():
        raise AssertionError("DB-only operation initialized MinIO")

    summary = await reconcile_due_once(
        session_maker=session_maker,
        storage_factory=forbidden_storage_factory,
        now=NOW,
    )

    assert summary.completed == 1
    assert summary.errors == 0
    async with session_maker() as session:
        assert await session.get(Notification, bulletin.id) is None
        stored = await session.get(PermanentDeletionOperation, operation_id)
        assert stored.status == PermanentDeletionStatus.COMPLETED
        await session.delete(stored)
        await session.commit()
