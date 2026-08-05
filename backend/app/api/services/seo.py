from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.courses import _public_archive_conditions
from app.core.config import settings
from app.db.session import get_session
from app.models.models import Archive, Course

router = APIRouter()


def _normalize_last_modified(value: datetime | None) -> str | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).date().isoformat()


def _append_url(
    urlset: Element,
    location: str,
    last_modified: datetime | None = None,
) -> None:
    url = SubElement(urlset, "url")
    SubElement(url, "loc").text = location

    normalized_last_modified = _normalize_last_modified(last_modified)
    if normalized_last_modified:
        SubElement(url, "lastmod").text = normalized_last_modified


@router.get(
    "/sitemap.xml",
    include_in_schema=False,
)
async def get_sitemap(
    db: AsyncSession = Depends(get_session),
):
    site_url = settings.FRONTEND_URL.rstrip("/")

    result = await db.execute(
        select(
            Archive.course_id,
            Archive.updated_at,
        )
        .join(
            Course,
            Course.id == Archive.course_id,
        )
        .where(
            Course.deleted_at.is_(None),
            *_public_archive_conditions(),
        )
    )
    rows = result.all()

    course_last_modified: dict[int, datetime] = {}

    for course_id, updated_at in rows:
        previous = course_last_modified.get(course_id)

        if previous is None or (
            updated_at is not None and updated_at > previous
        ):
            course_last_modified[course_id] = updated_at

    urlset = Element(
        "urlset",
        xmlns="http://www.sitemaps.org/schemas/sitemap/0.9",
    )

    _append_url(urlset, f"{site_url}/")

    latest_catalog_update = (
        max(course_last_modified.values())
        if course_last_modified
        else None
    )
    _append_url(
        urlset,
        f"{site_url}/courses",
        latest_catalog_update,
    )

    for course_id in sorted(course_last_modified):
        _append_url(
            urlset,
            f"{site_url}/courses/{course_id}",
            course_last_modified[course_id],
        )

    xml_body = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + tostring(urlset, encoding="utf-8")
    )

    return Response(
        content=xml_body,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )