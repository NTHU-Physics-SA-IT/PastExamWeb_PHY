from fastapi import APIRouter

from app.api.services import (
    archives,
    auth,
    courses,
    meme,
    notifications,
    reports,
    settings,
    seo,
    statistics,
    trash,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(archives.router, prefix="/archives", tags=["archives"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(meme.router, tags=["meme"])
api_router.include_router(statistics.router, tags=["statistics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(seo.router, prefix="/seo", tags=["seo"])
api_router.include_router(trash.router, prefix="/trash", tags=["trash"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
