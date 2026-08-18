from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.models import Archive, Course, CourseCategoryConfig
from app.services.archive_visibility import public_archive_conditions

router = APIRouter()


def _site_url() -> str:
    return settings.FRONTEND_URL.rstrip("/")


def _append_url(urlset: Element, location: str, last_modified=None) -> None:
    url = SubElement(urlset, "url")
    SubElement(url, "loc").text = location
    if last_modified is not None:
        SubElement(url, "lastmod").text = last_modified.date().isoformat()


@router.get("/sitemap.xml", include_in_schema=False)
async def get_sitemap(
    db: AsyncSession = Depends(get_session),
):
    rows = (
        await db.execute(
            select(
                Archive.course_id,
                func.max(Archive.updated_at).label("last_modified"),
            )
            .join(Course, Course.id == Archive.course_id)
            .join(
                CourseCategoryConfig,
                CourseCategoryConfig.key == Course.category,
            )
            .where(
                Course.deleted_at.is_(None),
                CourseCategoryConfig.is_active.is_(True),
                CourseCategoryConfig.deleted_at.is_(None),
                *public_archive_conditions(),
            )
            .group_by(Archive.course_id)
            .order_by(Archive.course_id)
        )
    ).all()

    site_url = _site_url()
    urlset = Element(
        "urlset",
        xmlns="http://www.sitemaps.org/schemas/sitemap/0.9",
    )
    _append_url(urlset, f"{site_url}/")
    _append_url(urlset, f"{site_url}/courses")
    for course_id, last_modified in rows:
        _append_url(
            urlset,
            f"{site_url}/courses/{course_id}",
            last_modified,
        )

    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
        urlset, encoding="utf-8"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/robots.txt", include_in_schema=False)
async def get_robots():
    site_url = _site_url()
    hostname = (urlsplit(site_url).hostname or "").lower()
    is_local = hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(
        ".local"
    )
    crawl_rule = "Disallow: /" if is_local else "Allow: /"
    body = f"User-agent: *\n{crawl_rule}\n\nSitemap: {site_url}/sitemap.xml\n"
    return PlainTextResponse(
        content=body,
        headers={"Cache-Control": "public, max-age=3600"},
    )
