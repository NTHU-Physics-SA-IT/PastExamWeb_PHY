from __future__ import annotations

import json

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware import recovery_review


def make_request(method: str, path: str, *, root_path: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": root_path,
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


async def allowed_response(_request: Request) -> JSONResponse:
    return JSONResponse({"allowed": True})


@pytest.mark.asyncio
async def test_normal_mode_does_not_block_mutations(monkeypatch) -> None:
    monkeypatch.setattr(recovery_review.settings, "RECOVERY_REVIEW_MODE", False)

    response = await recovery_review.enforce_recovery_review_read_only(
        make_request("DELETE", "/courses/1"),
        allowed_response,
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recovery_review_allows_reads_and_login(monkeypatch) -> None:
    monkeypatch.setattr(recovery_review.settings, "RECOVERY_REVIEW_MODE", True)

    get_response = await recovery_review.enforce_recovery_review_read_only(
        make_request("GET", "/courses"),
        allowed_response,
    )
    login_response = await recovery_review.enforce_recovery_review_read_only(
        make_request("POST", "/api/auth/login", root_path="/api"),
        allowed_response,
    )

    assert get_response.status_code == 200
    assert login_response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_recovery_review_blocks_content_mutations(monkeypatch, method) -> None:
    monkeypatch.setattr(recovery_review.settings, "RECOVERY_REVIEW_MODE", True)

    response = await recovery_review.enforce_recovery_review_read_only(
        make_request(method, "/courses/1"),
        allowed_response,
    )

    assert response.status_code == 403
    payload = json.loads(response.body)
    assert payload["detail"]["code"] == "recovery_review_read_only"
    assert "只讀" in payload["detail"]["message"]
