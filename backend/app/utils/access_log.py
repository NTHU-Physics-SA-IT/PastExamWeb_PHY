from __future__ import annotations

import logging
import re

NTHU_CALLBACK_PATH = "/auth/nthu/callback"
_ARCHIVE_DISCUSSION_WS_PATH = re.compile(
    r"^/(?:api/)?courses/[0-9]+/archives/[0-9]+/discussion/ws$"
)


class SensitiveRequestTargetLogFilter(logging.Filter):
    """Strip queries from repository-defined sensitive request targets."""

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if not isinstance(arguments, tuple):
            return True

        target_index = None
        if record.name == "uvicorn.access" and len(arguments) >= 3:
            target_index = 2
        elif (
            record.name == "uvicorn.error"
            and len(arguments) >= 2
            and isinstance(record.msg, str)
            and '"WebSocket %s"' in record.msg
        ):
            target_index = 1
        if target_index is None:
            return True

        request_target = str(arguments[target_index])
        path = request_target.partition("?")[0]
        if path.endswith(NTHU_CALLBACK_PATH) or _ARCHIVE_DISCUSSION_WS_PATH.fullmatch(
            path
        ):
            sanitized = list(arguments)
            sanitized[target_index] = path
            record.args = tuple(sanitized)
        return True


OAuthCallbackAccessLogFilter = SensitiveRequestTargetLogFilter


def install_oauth_access_log_filter() -> None:
    for logger_name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        if not any(
            isinstance(item, SensitiveRequestTargetLogFilter) for item in logger.filters
        ):
            logger.addFilter(SensitiveRequestTargetLogFilter())
