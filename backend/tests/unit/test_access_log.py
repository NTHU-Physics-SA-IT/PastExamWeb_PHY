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


def _websocket_record(
    target: str, message: str = '%s - "WebSocket %s" [accepted]'
) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        message,
        ("127.0.0.1:1234", target),
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


def test_websocket_log_removes_ticket_query_from_uvicorn_error() -> None:
    record = _websocket_record(
        "/courses/1/archives/2/discussion/ws?ticket=opaque-ticket-sentinel"
    )

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[1] == "/courses/1/archives/2/discussion/ws"
    assert "opaque-ticket-sentinel" not in record.getMessage()


def test_websocket_rejected_log_removes_legacy_token_query() -> None:
    record = _websocket_record(
        "/courses/1/archives/2/discussion/ws?token=legacy-bearer-sentinel",
        '%s - "WebSocket %s" 403',
    )

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[1] == "/courses/1/archives/2/discussion/ws"
    assert "legacy-bearer-sentinel" not in record.getMessage()


def test_websocket_http_response_log_keeps_format_after_sanitizing() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" %d',
        (
            "127.0.0.1:1234",
            "/courses/1/archives/2/discussion/ws?ticket=opaque-ticket-sentinel",
            503,
        ),
        None,
    )

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[1] == "/courses/1/archives/2/discussion/ws"
    assert "opaque-ticket-sentinel" not in record.getMessage()
    assert "503" in record.getMessage()


def test_websocket_route_is_sanitized_in_uvicorn_access_shape() -> None:
    record = _record(
        "/courses/1/archives/2/discussion/ws?ticket=opaque-ticket-sentinel"
    )

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[2] == "/courses/1/archives/2/discussion/ws"


def test_websocket_log_filter_preserves_other_websocket_targets() -> None:
    record = _websocket_record("/unrelated/ws?mode=debug")

    assert OAuthCallbackAccessLogFilter().filter(record) is True
    assert record.args[1] == "/unrelated/ws?mode=debug"


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
