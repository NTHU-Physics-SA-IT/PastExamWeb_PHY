"""Helpers for traceback observability without exposing exception messages."""

from types import TracebackType

ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


def redacted_exc_info(exc: BaseException) -> ExcInfo:
    """Return logging exc_info that keeps frames but redacts exception details."""

    return (
        RuntimeError,
        RuntimeError("exception details redacted"),
        exc.__traceback__,
    )
