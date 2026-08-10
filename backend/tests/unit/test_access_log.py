import logging

from app.utils.access_log import OAuthCallbackAccessLogFilter


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
