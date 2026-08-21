import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategoryConfig,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_backup
from app.utils.auth import get_current_user


class _FakeObjectResponse:
    def __init__(self, payload: bytes, *, unreadable: bool = False):
        self._stream = io.BytesIO(payload)
        self._unreadable = unreadable

    def read(self, size: int = -1) -> bytes:
        if self._unreadable:
            raise OSError("simulated unreadable object")
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()

    def release_conn(self) -> None:
        return None


class _FakeMinio:
    def __init__(self, objects: dict[str, bytes], *, unreadable: set[str] | None = None):
        self.objects = objects
        self.unreadable = unreadable or set()
        self.requested: list[str] = []

    def get_object(self, bucket: str, object_name: str) -> _FakeObjectResponse:
        del bucket
        self.requested.append(object_name)
        if object_name not in self.objects:
            raise FileNotFoundError(object_name)
        return _FakeObjectResponse(
            self.objects[object_name],
            unreadable=object_name in self.unreadable,
        )


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


async def _create_archive(
    session,
    *,
    course: Course,
    uploader_id: int,
    marker: str,
    deleted: bool = False,
) -> Archive:
    archive = Archive(
        name="重複/期末考:*?",
        academic_year=2026,
        archive_type=ArchiveType.FINAL,
        professor="王/教授:*?",
        has_answers=True,
        object_name=f"private/{marker}.pdf",
        course_id=course.id,
        uploader_id=uploader_id,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(archive)
    await session.flush()
    return archive


async def _link_submission(
    session,
    *,
    archive: Archive,
    requester_id: int,
    status: SubmissionStatus,
    deleted: bool = False,
) -> ArchiveSubmission:
    submission = ArchiveSubmission(
        subject="備份測試課程",
        category="backup-active",
        name=archive.name,
        academic_year=archive.academic_year,
        archive_type=archive.archive_type,
        professor=archive.professor,
        has_answers=archive.has_answers,
        object_name=f"submissions/{uuid.uuid4().hex}.pdf",
        status=status,
        requester_id=requester_id,
        created_archive_id=archive.id,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(submission)
    await session.flush()
    return submission


@pytest.mark.asyncio
async def test_admin_archive_backup_exports_only_effective_public_content(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
):
    marker = uuid.uuid4().hex
    uploader = await make_user(
        name=f"private-user-{marker}",
        email=f"private-{marker}@example.com",
        student_id=f"student-{marker}",
    )
    category_ids: list[int] = []
    course_ids: list[int] = []
    archive_ids: list[int] = []
    submission_ids: list[int] = []

    async with session_maker() as session:
        active_category = CourseCategoryConfig(
            key=f"backup-active-{marker}",
            name=f"公開/分類:*? {marker}",
            label="公開/分類:*?",
            is_active=True,
            order_index=10,
        )
        inactive_category = CourseCategoryConfig(
            key=f"backup-inactive-{marker}",
            name=f"停用分類 {marker}",
            label="停用分類",
            is_active=False,
            order_index=11,
        )
        deleted_category = CourseCategoryConfig(
            key=f"backup-deleted-{marker}",
            name=f"刪除分類 {marker}",
            label="刪除分類",
            is_active=False,
            deleted_at=datetime.now(UTC),
            pre_delete_is_active=True,
            order_index=12,
        )
        session.add_all([active_category, inactive_category, deleted_category])
        await session.flush()
        category_ids.extend(
            [active_category.id, inactive_category.id, deleted_category.id]
        )

        active_course = Course(
            name="量子/力學:*?",
            name_en="Quantum Mechanics",
            category=active_category.key,
            order_index=4,
        )
        deleted_course = Course(
            name=f"刪除課程 {marker}",
            category=active_category.key,
            deleted_at=datetime.now(UTC),
        )
        inactive_category_course = Course(
            name=f"停用分類課程 {marker}",
            category=inactive_category.key,
        )
        deleted_category_course = Course(
            name=f"刪除分類課程 {marker}",
            category=deleted_category.key,
        )
        session.add_all(
            [
                active_course,
                deleted_course,
                inactive_category_course,
                deleted_category_course,
            ]
        )
        await session.flush()
        course_ids.extend(
            [
                active_course.id,
                deleted_course.id,
                inactive_category_course.id,
                deleted_category_course.id,
            ]
        )

        public_archives = [
            await _create_archive(
                session,
                course=active_course,
                uploader_id=uploader.id,
                marker=f"{marker}-public-{index}",
            )
            for index in range(2)
        ]
        for archive in public_archives:
            submission = await _link_submission(
                session,
                archive=archive,
                requester_id=uploader.id,
                status=SubmissionStatus.APPROVED,
            )
            submission_ids.append(submission.id)

        for label, status, deleted in (
            ("pending", SubmissionStatus.PENDING, False),
            ("rejected", SubmissionStatus.REJECTED, False),
            ("takedown", SubmissionStatus.TAKEDOWN, False),
            ("trash", SubmissionStatus.APPROVED, True),
        ):
            archive = await _create_archive(
                session,
                course=active_course,
                uploader_id=uploader.id,
                marker=f"{marker}-{label}",
            )
            submission = await _link_submission(
                session,
                archive=archive,
                requester_id=uploader.id,
                status=status,
                deleted=deleted,
            )
            archive_ids.append(archive.id)
            submission_ids.append(submission.id)

        excluded_archives = [
            await _create_archive(
                session,
                course=active_course,
                uploader_id=uploader.id,
                marker=f"{marker}-archive-trash",
                deleted=True,
            ),
            await _create_archive(
                session,
                course=deleted_course,
                uploader_id=uploader.id,
                marker=f"{marker}-deleted-course",
            ),
            await _create_archive(
                session,
                course=inactive_category_course,
                uploader_id=uploader.id,
                marker=f"{marker}-inactive-category",
            ),
            await _create_archive(
                session,
                course=deleted_category_course,
                uploader_id=uploader.id,
                marker=f"{marker}-deleted-category",
            ),
        ]
        archive_ids.extend([archive.id for archive in public_archives + excluded_archives])
        await session.commit()

    payloads = {
        archive.object_name: f"pdf-{archive.id}".encode()
        for archive in public_archives
    }
    fake_minio = _FakeMinio(payloads)
    monkeypatch.setattr(archive_backup, "get_minio_client", lambda: fake_minio)

    app.dependency_overrides.pop(get_current_user, None)
    anonymous = await client.get("/backups/admin/archive")
    assert anonymous.status_code in {401, 403}
    assert fake_minio.requested == []

    app.dependency_overrides[get_current_user] = _override_user(
        uploader.id, is_admin=False
    )
    try:
        forbidden = await client.get("/backups/admin/archive")
        assert forbidden.status_code == 403
        assert fake_minio.requested == []

        app.dependency_overrides[get_current_user] = _override_user(
            uploader.id, is_admin=True
        )
        response = await client.get("/backups/admin/archive")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["cache-control"] == "no-store"

        with zipfile.ZipFile(io.BytesIO(response.content)) as exported_zip:
            names = exported_zip.namelist()
            roots = {name.split("/", 1)[0] for name in names}
            assert len(roots) == 1
            root = roots.pop()
            manifest_path = f"{root}/manifest.json"
            checksums_path = f"{root}/checksums.sha256"
            assert manifest_path in names
            assert checksums_path in names

            manifest_bytes = exported_zip.read(manifest_path)
            manifest = json.loads(manifest_bytes)
            assert manifest["backup_format_version"] == "1"
            assert manifest["archive_count"] == 2
            assert manifest["exported_at_utc"].endswith("Z")
            assert len(manifest["categories"]) == 1
            category = manifest["categories"][0]
            assert category["id"] == active_category.id
            assert category["folder"].endswith(f"__CAT{active_category.id}")
            assert "/" not in category["folder"]
            assert len(category["courses"]) == 1
            course = category["courses"][0]
            assert course["id"] == active_course.id
            assert course["folder"].endswith(f"__C{active_course.id}")
            assert "/" not in course["folder"]

            exported_archives = course["archives"]
            assert [item["id"] for item in exported_archives] == sorted(
                archive.id for archive in public_archives
            )
            exported_paths = [item["exported_path"] for item in exported_archives]
            assert len(exported_paths) == len(set(exported_paths)) == 2
            for item in exported_archives:
                exported_name = item["exported_path"].rsplit("/", 1)[-1]
                assert exported_name.endswith(f"__A{item['id']}.pdf")
                assert not any(character in exported_name for character in '<>:"/\\|?*')
                assert item["sha256"] == hashlib.sha256(
                    payloads[next(
                        archive.object_name
                        for archive in public_archives
                        if archive.id == item["id"]
                    )]
                ).hexdigest()

            csv_path = f"{root}/{category['folder']}/{course['folder']}/_archives.csv"
            assert csv_path in names
            csv_text = exported_zip.read(csv_path).decode("utf-8-sig")
            assert "archive_id,academic_year,archive_type,professor" in csv_text
            assert all(str(archive.id) in csv_text for archive in public_archives)

            checksum_lines = exported_zip.read(checksums_path).decode().splitlines()
            assert len(checksum_lines) == 2
            for item in exported_archives:
                relative_path = item["exported_path"].split("/", 1)[1]
                assert f"{item['sha256']}  {relative_path}" in checksum_lines
                assert exported_zip.read(item["exported_path"]) == payloads[
                    next(
                        archive.object_name
                        for archive in public_archives
                        if archive.id == item["id"]
                    )
                ]

            all_metadata = manifest_bytes.decode() + csv_text
            assert uploader.email not in all_metadata
            assert uploader.student_id not in all_metadata
            assert "requester_id" not in all_metadata
            assert "uploader_id" not in all_metadata
            assert "object_name" not in all_metadata
            assert all(archive.object_name not in all_metadata for archive in public_archives)

        assert fake_minio.requested == [
            archive.object_name for archive in sorted(public_archives, key=lambda row: row.id)
        ]
        async with session_maker() as session:
            persisted = list(
                (
                    await session.execute(
                        select(Archive).where(
                            Archive.id.in_([archive.id for archive in public_archives])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {archive.object_name for archive in persisted} == set(payloads)
            assert all(archive.download_count == 0 for archive in persisted)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id.in_(submission_ids))
            )
            await session.execute(delete(Archive).where(Archive.id.in_(archive_ids)))
            await session.execute(delete(Course).where(Course.id.in_(course_ids)))
            await session.execute(
                delete(CourseCategoryConfig).where(
                    CourseCategoryConfig.id.in_(category_ids)
                )
            )
            await session.commit()


@pytest.mark.parametrize("storage_mode", ["missing", "unreadable"])
@pytest.mark.asyncio
async def test_admin_archive_backup_fails_closed_for_unavailable_public_pdf(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
    storage_mode: str,
):
    marker = uuid.uuid4().hex
    admin = await make_user(is_admin=True)
    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=f"backup-failure-{marker}",
            name=f"備份失敗分類 {marker}",
            label="備份失敗",
            is_active=True,
        )
        session.add(category)
        await session.flush()
        course = Course(name=f"備份失敗課程 {marker}", category=category.key)
        session.add(course)
        await session.flush()
        archive = await _create_archive(
            session,
            course=course,
            uploader_id=admin.id,
            marker=f"{marker}-unreadable",
        )
        submission = await _link_submission(
            session,
            archive=archive,
            requester_id=admin.id,
            status=SubmissionStatus.APPROVED,
        )
        await session.commit()

    objects = {} if storage_mode == "missing" else {archive.object_name: b"unreadable"}
    unreadable = {archive.object_name} if storage_mode == "unreadable" else set()
    fake_minio = _FakeMinio(objects, unreadable=unreadable)
    monkeypatch.setattr(archive_backup, "get_minio_client", lambda: fake_minio)
    app.dependency_overrides[get_current_user] = _override_user(
        admin.id, is_admin=True
    )
    try:
        response = await client.get("/backups/admin/archive")
        assert response.status_code == 502
        assert response.json()["detail"] == {
            "code": "archive_backup_file_unavailable",
            "message": "備份失敗：有公開考古題的 PDF 無法讀取，未產生不完整備份。",
            "archive_id": archive.id,
        }
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.id == submission.id)
            )
            await session.execute(delete(Archive).where(Archive.id == archive.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.execute(
                delete(CourseCategoryConfig).where(CourseCategoryConfig.id == category.id)
            )
            await session.commit()
