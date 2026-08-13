from __future__ import annotations

import logging

NTHU_CALLBACK_PATH = "/auth/nthu/callback"


class OAuthCallbackAccessLogFilter(logging.Filter):
    """Remove the provider code and state from Uvicorn callback access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if not isinstance(arguments, tuple) or len(arguments) < 3:
            return True
        request_target = str(arguments[2])
        path = request_target.partition("?")[0]
        if path.endswith(NTHU_CALLBACK_PATH):
            sanitized = list(arguments)
            sanitized[2] = path
            record.args = tuple(sanitized)
        return True


def install_oauth_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(
        isinstance(item, OAuthCallbackAccessLogFilter) for item in logger.filters
    ):
        logger.addFilter(OAuthCallbackAccessLogFilter())
