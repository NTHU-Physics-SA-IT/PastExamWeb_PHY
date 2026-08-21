"""Build read-only administrator exports of the effective-public PDF archive."""

import csv
import hashlib
import io
import json
import re
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy import and_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.models import Archive, Course, CourseCategoryConfig
from app.services.archive_visibility import (
    public_archive_conditions,
    public_course_conditions,
)
from app.utils.storage import get_minio_client

BACKUP_FORMAT_VERSION = "1"
_COPY_CHUNK_SIZE = 1024 * 1024
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class ArchiveBackupResult:
    file: BinaryIO
    filename: str
    size: int


class ArchiveBackupStorageError(Exception):
    def __init__(self, archive_id: int):
        super().__init__(f"Archive PDF unavailable: {archive_id}")
        self.archive_id = archive_id


def _safe_segment(value: object, *, fallback: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _INVALID_FILENAME_CHARACTERS.sub("_", normalized)
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip(" ._")
    normalized = normalized[:max_length].rstrip(" ._") or fallback
    if normalized.upper() in _WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized


def _archive_type_value(archive: Archive) -> str:
    return str(getattr(archive.archive_type, "value", archive.archive_type))


def _archive_filename(archive: Archive) -> str:
    answer_status = "answers" if archive.has_answers else "no-answers"
    parts = (
        _safe_segment(archive.academic_year, fallback="unknown-year", max_length=12),
        _safe_segment(_archive_type_value(archive), fallback="other", max_length=24),
        _safe_segment(archive.professor, fallback="unknown-professor", max_length=48),
        answer_status,
    )
    return f"{'_'.join(parts)}__A{archive.id}.pdf"


def _category_folder(category: CourseCategoryConfig) -> str:
    display_name = category.label or category.name or category.key
    return f"{_safe_segment(display_name, fallback='category')}__CAT{category.id}"


def _course_folder(course: Course) -> str:
    return f"{_safe_segment(course.name, fallback='course')}__C{course.id}"


def _iter_spooled_file(file: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := file.read(_COPY_CHUNK_SIZE):
            yield chunk
    finally:
        file.close()


def stream_backup_result(result: ArchiveBackupResult) -> Iterator[bytes]:
    return _iter_spooled_file(result.file)


def _write_archive_pdf(
    zip_file: zipfile.ZipFile,
    *,
    archive: Archive,
    exported_path: str,
) -> str:
    response = None
    digest = hashlib.sha256()
    try:
        response = get_minio_client().get_object(
            settings.MINIO_BUCKET_NAME,
            archive.object_name,
        )
        with zip_file.open(exported_path, "w") as exported_file:
            while chunk := response.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
                exported_file.write(chunk)
    except Exception as exc:
        raise ArchiveBackupStorageError(int(archive.id)) from exc
    finally:
        if response is not None:
            response.close()
            response.release_conn()
    return digest.hexdigest()


def _write_course_csv(zip_file: zipfile.ZipFile, path: str, archives: list[dict]) -> None:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "archive_id",
            "academic_year",
            "archive_type",
            "professor",
            "exam_name",
            "has_answers",
            "exported_filename",
            "sha256",
        ],
    )
    writer.writeheader()
    for archive in archives:
        writer.writerow(
            {
                "archive_id": archive["id"],
                "academic_year": archive["academic_year"],
                "archive_type": archive["archive_type"],
                "professor": archive["professor"],
                "exam_name": archive["name"],
                "has_answers": str(archive["has_answers"]).lower(),
                "exported_filename": PurePosixPath(archive["exported_path"]).name,
                "sha256": archive["sha256"],
            }
        )
    zip_file.writestr(path, output.getvalue().encode("utf-8-sig"))


async def build_archive_backup(db: AsyncSession) -> ArchiveBackupResult:
    exported_at = datetime.now(UTC).replace(microsecond=0)
    timestamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    root_folder = f"PhysArchive_Backup_{timestamp}"
    output = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - closed by stream iterator
        max_size=32 * 1024 * 1024,
        mode="w+b",
    )

    categories: list[dict] = []
    categories_by_id: dict[int, dict] = {}
    courses_by_id: dict[int, dict] = {}
    checksum_lines: list[str] = []

    query = (
        select(Archive, Course, CourseCategoryConfig)
        .join(Course, Course.id == Archive.course_id)
        .join(
            CourseCategoryConfig,
            and_(
                CourseCategoryConfig.key == Course.category,
                CourseCategoryConfig.is_active.is_(True),
                CourseCategoryConfig.deleted_at.is_(None),
            ),
        )
        .where(*public_archive_conditions(), *public_course_conditions())
        .order_by(
            CourseCategoryConfig.order_index.asc(),
            CourseCategoryConfig.id.asc(),
            Course.order_index.asc(),
            Course.id.asc(),
            Archive.academic_year.desc(),
            Archive.archive_type.asc(),
            Archive.id.asc(),
        )
        .execution_options(yield_per=100)
    )

    try:
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as zip_file:
            result = await db.stream(query)
            async for archive, course, category in result:
                category_id = int(category.id)
                category_entry = categories_by_id.get(category_id)
                if category_entry is None:
                    category_entry = {
                        "id": category_id,
                        "key": category.key,
                        "name": category.name,
                        "name_en": category.name_en,
                        "label": category.label,
                        "label_en": category.label_en,
                        "folder": _category_folder(category),
                        "courses": [],
                    }
                    categories_by_id[category_id] = category_entry
                    categories.append(category_entry)

                course_id = int(course.id)
                course_entry = courses_by_id.get(course_id)
                if course_entry is None:
                    course_entry = {
                        "id": course_id,
                        "category_id": category_id,
                        "name": course.name,
                        "name_en": course.name_en,
                        "folder": _course_folder(course),
                        "archives": [],
                    }
                    courses_by_id[course_id] = course_entry
                    category_entry["courses"].append(course_entry)

                exported_filename = _archive_filename(archive)
                relative_path = str(
                    PurePosixPath(
                        category_entry["folder"],
                        course_entry["folder"],
                        exported_filename,
                    )
                )
                exported_path = str(PurePosixPath(root_folder, relative_path))
                sha256 = _write_archive_pdf(
                    zip_file,
                    archive=archive,
                    exported_path=exported_path,
                )
                checksum_lines.append(f"{sha256}  {relative_path}")
                course_entry["archives"].append(
                    {
                        "id": int(archive.id),
                        "course_id": course_id,
                        "category_id": category_id,
                        "name": archive.name,
                        "academic_year": archive.academic_year,
                        "archive_type": _archive_type_value(archive),
                        "professor": archive.professor,
                        "has_answers": archive.has_answers,
                        "exported_path": exported_path,
                        "sha256": sha256,
                    }
                )

            for category in categories:
                for course in category["courses"]:
                    csv_path = str(
                        PurePosixPath(
                            root_folder,
                            category["folder"],
                            course["folder"],
                            "_archives.csv",
                        )
                    )
                    _write_course_csv(zip_file, csv_path, course["archives"])

            manifest = {
                "backup_format_version": BACKUP_FORMAT_VERSION,
                "exported_at_utc": exported_at.isoformat().replace("+00:00", "Z"),
                "archive_count": sum(
                    len(course["archives"])
                    for category in categories
                    for course in category["courses"]
                ),
                "categories": categories,
            }
            zip_file.writestr(
                str(PurePosixPath(root_folder, "manifest.json")),
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            checksums = "\n".join(checksum_lines)
            if checksums:
                checksums += "\n"
            zip_file.writestr(
                str(PurePosixPath(root_folder, "checksums.sha256")),
                checksums.encode("utf-8"),
            )
    except Exception:
        output.close()
        raise

    size = output.tell()
    output.seek(0)
    return ArchiveBackupResult(
        file=output,
        filename=f"{root_folder}.zip",
        size=size,
    )
