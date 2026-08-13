import io
import logging

from app.utils.access_log import OAuthCallbackAccessLogFilter
from app.utils.exception_logging import redacted_exc_info


def _record(target: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", target, "1.1", 307),
        None,
    )


def test_oauth_callback_access_log_removes_sensitive_query() -> None:
    record = _record("/api/auth/nthu/callback?code=provider-code&state=oauth-state")

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[2] == "/api/auth/nthu/callback"
    assert "provider-code" not in record.getMessage()
    assert "oauth-state" not in record.getMessage()


def test_access_log_filter_preserves_other_requests() -> None:
    record = _record("/api/courses?category=graduate")

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[2] == "/api/courses?category=graduate"


def test_redacted_exc_info_preserves_traceback_without_exception_text() -> None:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("test.redacted-exception")
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    secret_prefix = "oauth-token-"
    secret = f"{secret_prefix}must-not-be-logged"

    try:
        try:
            raise RuntimeError(secret)
        except RuntimeError as exc:
            logger.error("OAuth callback failed", exc_info=redacted_exc_info(exc))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    rendered = output.getvalue()
    assert "OAuth callback failed" in rendered
    assert "exception details redacted" in rendered
    assert secret not in rendered
    assert "test_redacted_exc_info_preserves_traceback" in rendered
