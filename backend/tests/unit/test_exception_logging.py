from __future__ import annotations

import io
import logging

from app.utils.exception_logging import redacted_exc_info


def test_redacted_exc_info_preserves_traceback_without_exception_text():
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("test.redacted-exception")
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

    rendered = output.getvalue()
    assert "OAuth callback failed" in rendered
    assert "exception details redacted" in rendered
    assert secret not in rendered
    assert "test_redacted_exc_info_preserves_traceback" in rendered
