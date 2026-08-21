from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.models.models import UserRoles
from app.services.archive_backup import (
    ArchiveBackupStorageError,
    build_archive_backup,
    stream_backup_result,
)
from app.utils.auth import get_current_user

router = APIRouter()


@router.get("/admin/archive")
async def download_archive_backup(
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    try:
        result = await build_archive_backup(db)
    except ArchiveBackupStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "archive_backup_file_unavailable",
                "message": "備份失敗：有公開考古題的 PDF 無法讀取，未產生不完整備份。",
                "archive_id": exc.archive_id,
            },
        ) from exc

    return StreamingResponse(
        stream_backup_result(result),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "Content-Length": str(result.size),
            "Cache-Control": "no-store",
        },
    )
