"""Bounded operational reconciliation for existing permanent-deletion ledgers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import case, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.models.models import (
    PermanentDeletionOperation,
    PermanentDeletionStatus,
)
from app.services.permanent_deletion import (
    permanent_deletion_claimable_predicate,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_storage import ExactVersionMinioAdapter

logger = logging.getLogger(__name__)

DEFAULT_OPERATION_BATCH_LIMIT = 25
DEFAULT_PURGE_BATCH_LIMIT = 25
MAX_BATCH_LIMIT = 1000


class SessionFactory(Protocol):
    def __call__(self): ...


Processor = Callable[..., object]
StorageFactory = Callable[[], ExactVersionMinioAdapter]


@dataclass(frozen=True)
class ReconciliationSummary:
    candidates: int = 0
    processed: int = 0
    completed: int = 0
    pending: int = 0
    manual_review: int = 0
    skipped: int = 0
    errors: int = 0
    purged: int = 0
    purge_errors: int = 0


def _validate_limit(value: int, *, field: str) -> int:
    if not 1 <= value <= MAX_BATCH_LIMIT:
        raise ValueError(f"{field} must be between 1 and {MAX_BATCH_LIMIT}")
    return value


def _effective_due_time():
    return case(
        (
            PermanentDeletionOperation.status
            == PermanentDeletionStatus.VERIFICATION_REQUIRED,
            PermanentDeletionOperation.accepted_at,
        ),
        (
            PermanentDeletionOperation.status == PermanentDeletionStatus.PROCESSING,
            PermanentDeletionOperation.lease_expires_at,
        ),
        (
            PermanentDeletionOperation.status
            == PermanentDeletionStatus.RETRYABLE_FAILED,
            PermanentDeletionOperation.next_attempt_at,
        ),
        else_=func.coalesce(
            PermanentDeletionOperation.next_attempt_at,
            PermanentDeletionOperation.accepted_at,
        ),
    )


async def select_due_operation_ids(
    db: SQLModelAsyncSession,
    *,
    now: datetime,
    limit: int = DEFAULT_OPERATION_BATCH_LIMIT,
) -> list[int]:
    """Select a bounded deterministic candidate list without claiming rows."""

    _validate_limit(limit, field="operation limit")
    statement = (
        select(PermanentDeletionOperation.id)
        .where(permanent_deletion_claimable_predicate(now))
        .order_by(
            _effective_due_time().asc().nullsfirst(),
            PermanentDeletionOperation.id.asc(),
        )
        .limit(limit)
    )
    return [int(value) for value in (await db.execute(statement)).scalars().all()]


async def purge_completed_audits(
    session_maker: SessionFactory,
    *,
    now: datetime,
    limit: int = DEFAULT_PURGE_BATCH_LIMIT,
) -> int:
    """Purge only bounded, already-completed ledger rows at their stored deadline."""

    _validate_limit(limit, field="purge limit")
    async with session_maker() as db:
        try:
            due_ids = [
                int(value)
                for value in (
                    await db.execute(
                        select(PermanentDeletionOperation.id)
                        .where(
                            PermanentDeletionOperation.status
                            == PermanentDeletionStatus.COMPLETED,
                            PermanentDeletionOperation.audit_purge_after.is_not(None),
                            PermanentDeletionOperation.audit_purge_after <= now,
                        )
                        .order_by(
                            PermanentDeletionOperation.audit_purge_after.asc(),
                            PermanentDeletionOperation.id.asc(),
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            ]
            if not due_ids:
                await db.rollback()
                return 0
            result = await db.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id.in_(due_ids),
                    PermanentDeletionOperation.status
                    == PermanentDeletionStatus.COMPLETED,
                    PermanentDeletionOperation.audit_purge_after.is_not(None),
                    PermanentDeletionOperation.audit_purge_after <= now,
                )
            )
            await db.commit()
            return int(result.rowcount or 0)
        except Exception:
            await db.rollback()
            raise


async def reconcile_due_once(
    *,
    session_maker: SessionFactory,
    storage_factory: StorageFactory,
    now: datetime | None = None,
    event_clock: Callable[[], datetime] | None = None,
    operation_limit: int = DEFAULT_OPERATION_BATCH_LIMIT,
    purge_limit: int = DEFAULT_PURGE_BATCH_LIMIT,
    processor: Processor = process_one_permanent_deletion,
) -> ReconciliationSummary:
    """Process one bounded candidate batch, then independently purge due audits."""

    timestamp = now or datetime.now(UTC)
    clock = event_clock or (lambda: datetime.now(UTC))
    _validate_limit(operation_limit, field="operation limit")
    _validate_limit(purge_limit, field="purge limit")
    async with session_maker() as db:
        operation_ids = await select_due_operation_ids(
            db,
            now=timestamp,
            limit=operation_limit,
        )

    processed = completed = pending = manual_review = skipped = errors = 0
    for operation_id in operation_ids:
        async with session_maker() as db:
            try:
                status = await processor(
                    db,
                    operation_id=operation_id,
                    storage_factory=storage_factory,
                    event_clock=clock,
                )
                processed += 1
                if status == PermanentDeletionStatus.COMPLETED:
                    completed += 1
                elif status == PermanentDeletionStatus.MANUAL_REVIEW:
                    manual_review += 1
                elif status == PermanentDeletionStatus.PROCESSING:
                    skipped += 1
                else:
                    pending += 1
            except Exception as exc:  # noqa: BLE001 - isolate each durable operation
                await db.rollback()
                errors += 1
                logger.error(
                    "Permanent-deletion reconciliation item failed (%s)",
                    type(exc).__name__,
                )

    purged = purge_errors = 0
    try:
        purged = await purge_completed_audits(
            session_maker,
            now=timestamp,
            limit=purge_limit,
        )
    except Exception as exc:  # noqa: BLE001 - purge is independent from reconciliation
        purge_errors = 1
        logger.error(
            "Permanent-deletion audit purge failed (%s)",
            type(exc).__name__,
        )

    return ReconciliationSummary(
        candidates=len(operation_ids),
        processed=processed,
        completed=completed,
        pending=pending,
        manual_review=manual_review,
        skipped=skipped,
        errors=errors,
        purged=purged,
        purge_errors=purge_errors,
    )
