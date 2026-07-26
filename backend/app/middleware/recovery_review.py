from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings


RECOVERY_REVIEW_ERROR_CODE = "recovery_review_read_only"
RECOVERY_REVIEW_ALLOWED_MUTATIONS = frozenset(
    {
        "/auth/login",
        "/auth/logout",
        "/auth/heartbeat",
    }
)


async def enforce_recovery_review_read_only(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Block content mutations in the isolated recovery-review environment."""
    if not settings.RECOVERY_REVIEW_MODE:
        return await call_next(request)

    method = request.method.upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)

    normalized_path = str(request.scope.get("path") or request.url.path)
    root_path = str(request.scope.get("root_path") or "").rstrip("/")
    if root_path and normalized_path.startswith(f"{root_path}/"):
        normalized_path = normalized_path[len(root_path) :]
    normalized_path = normalized_path.rstrip("/") or "/"
    if normalized_path in RECOVERY_REVIEW_ALLOWED_MUTATIONS:
        return await call_next(request)

    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "code": RECOVERY_REVIEW_ERROR_CODE,
                "message": "Recovery Review 是只讀環境，不能修改舊資料。",
            }
        },
    )
