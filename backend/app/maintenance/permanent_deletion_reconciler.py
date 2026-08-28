"""Run bounded automatic reconciliation for existing permanent-deletion operations."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable, Sequence

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.permanent_deletion_reconciler import (
    DEFAULT_OPERATION_BATCH_LIMIT,
    DEFAULT_PURGE_BATCH_LIMIT,
    MAX_BATCH_LIMIT,
    ReconciliationSummary,
    reconcile_due_once,
)
from app.services.permanent_deletion_storage import ExactVersionMinioAdapter
from app.utils.storage import get_minio_client

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 30.0
MAX_POLL_INTERVAL_SECONDS = 3600.0


def _bounded_float(value: str) -> float:
    parsed = float(value)
    if not 1.0 <= parsed <= MAX_POLL_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"value must be between 1 and {MAX_POLL_INTERVAL_SECONDS:g}"
        )
    return parsed


def _bounded_batch(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_BATCH_LIMIT:
        raise argparse.ArgumentTypeError(
            f"value must be between 1 and {MAX_BATCH_LIMIT}"
        )
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one pass and exit")
    parser.add_argument(
        "--poll-interval-seconds",
        type=_bounded_float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--operation-batch-limit",
        type=_bounded_batch,
        default=DEFAULT_OPERATION_BATCH_LIMIT,
    )
    parser.add_argument(
        "--purge-batch-limit",
        type=_bounded_batch,
        default=DEFAULT_PURGE_BATCH_LIMIT,
    )
    return parser.parse_args(argv)


def _storage_factory() -> ExactVersionMinioAdapter:
    return ExactVersionMinioAdapter(
        get_minio_client(),
        bucket_name=settings.MINIO_BUCKET_NAME,
    )


async def _default_reconcile(**kwargs) -> ReconciliationSummary:
    return await reconcile_due_once(
        session_maker=AsyncSessionLocal,
        storage_factory=_storage_factory,
        **kwargs,
    )


async def run_worker(
    *,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
    operation_batch_limit: int,
    purge_batch_limit: int,
    reconcile: Callable[..., Awaitable[ReconciliationSummary | None]] = _default_reconcile,
) -> None:
    """Run passes serially and stop before starting another pass after a signal."""

    while not stop_event.is_set():
        try:
            summary = await reconcile(
                operation_limit=operation_batch_limit,
                purge_limit=purge_batch_limit,
            )
            if summary is not None:
                logger.info(
                    "Permanent-deletion reconciliation pass: candidates=%s "
                    "processed=%s completed=%s pending=%s manual_review=%s "
                    "skipped=%s errors=%s purged=%s purge_errors=%s",
                    summary.candidates,
                    summary.processed,
                    summary.completed,
                    summary.pending,
                    summary.manual_review,
                    summary.skipped,
                    summary.errors,
                    summary.purged,
                    summary.purge_errors,
                )
        except Exception as exc:  # noqa: BLE001 - outages must still use the wait
            logger.error(
                "Permanent-deletion reconciliation pass failed (%s)",
                type(exc).__name__,
            )
        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=poll_interval_seconds,
            )
        except TimeoutError:
            pass


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            signal.signal(signum, lambda *_args: stop_event.set())


async def _run(args: argparse.Namespace) -> None:
    if args.once:
        await _default_reconcile(
            operation_limit=args.operation_batch_limit,
            purge_limit=args.purge_batch_limit,
        )
        return
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await run_worker(
        stop_event=stop_event,
        poll_interval_seconds=args.poll_interval_seconds,
        operation_batch_limit=args.operation_batch_limit,
        purge_batch_limit=args.purge_batch_limit,
    )


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run(parse_args(argv)))


if __name__ == "__main__":
    main()
