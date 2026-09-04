from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pikepdf
import pytest
from httpx import AsyncClient
from minio.error import S3Error
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.services import archives as archives_service
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    ArchiveWish,
    Course,
    CourseCategory,
    PermanentDeletionObject,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    SubmissionStatus,
    UserRoles,
)
from app.services.archive_submission_review_revision import (
    compute_archive_submission_review_revision,
)
from app.utils.auth import get_current_user


def _pdf_bytes() -> bytes:
    payload = io.BytesIO()
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(payload)
    return payload.getvalue()


VALID_PDF_BYTES = _pdf_bytes()


class _ObjectResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _VersionedMinio:
    def __init__(self, old_key: str, *, old_version: str = "v-old") -> None:
        self.versions: dict[str, str] = {old_key: old_version}
        self.payloads: dict[str, bytes] = {old_key: VALID_PDF_BYTES}
        self.put_names: list[str] = []
        self.get_names: list[str] = []
        self.removals: list[tuple[str, str | None]] = []
        self.retry_delete = False
        self.versioning_enabled = True
        self.fail_put = False

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status="Enabled" if self.versioning_enabled else "Off")

    def list_objects(self, _bucket: str, *, prefix: str, **_kwargs):
        return [
            SimpleNamespace(
                object_name=key,
                version_id=version,
                is_delete_marker=False,
            )
            for key, version in self.versions.items()
            if key == prefix
        ]

    def stat_object(self, _bucket: str, key: str, version_id: str | None = None):
        current = self.versions.get(key)
        if current is None or (version_id is not None and version_id != current):
            raise S3Error(None, "NoSuchVersion", "missing", key, "request", "host")
        return SimpleNamespace(object_name=key, version_id=current)

    def put_object(self, *, object_name: str, data, **_kwargs):
        if self.fail_put:
            raise S3Error(
                None,
                "ServiceUnavailable",
                "failed",
                object_name,
                "request",
                "host",
            )
        self.put_names.append(object_name)
        self.payloads[object_name] = data.read()
        self.versions[object_name] = f"v-new-{len(self.put_names)}"

    def get_object(self, _bucket: str, key: str):
        self.get_names.append(key)
        if key not in self.payloads:
            raise S3Error(None, "NoSuchKey", "missing", key, "request", "host")
        return _ObjectResponse(self.payloads[key])

    def remove_object(
        self,
        _bucket: str,
        key: str,
        version_id: str | None = None,
    ) -> None:
        self.removals.append((key, version_id))
        if self.retry_delete and version_id is not None:
            raise S3Error(
                None,
                "ServiceUnavailable",
                "retry",
                key,
                "request",
                "host",
            )
        if version_id is None or self.versions.get(key) == version_id:
            self.versions.pop(key, None)
            self.payloads.pop(key, None)


def _override_user(user_id: int, *, is_admin: bool = False):
    async def _current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _current_user


async def _create_context(
    session_maker,
    *,
    requester_id: int,
    requested_course_name: str | None = None,
    requested_category_key: str | None = None,
    source_wish_id: int | None = None,
    status: SubmissionStatus = SubmissionStatus.PENDING,
):
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        course = Course(
            name=f"Owner Pending Course {marker}",
            name_en=f"Owner Pending Course EN {marker}",
            category=CourseCategory.FRESHMAN.value,
        )
        session.add(course)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=course.category,
            name="midterm1",
            academic_year=1151,
            archive_type=ArchiveType.MIDTERM,
            professor="Owner Pending Professor",
            has_answers=False,
            object_name=f"archive-submissions/{requester_id}/{marker}.pdf",
            requester_id=requester_id,
            requested_course_name=requested_course_name,
            requested_category_key=requested_category_key,
            source_wish_id=source_wish_id,
            status=status,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)
        return course, submission


async def _cleanup(
    session_maker,
    *,
    course_ids: list[int],
    submission_ids: list[int],
    wish_ids: list[int] | None = None,
) -> None:
    async with session_maker() as session:
        operation_ids = list(
            (
                await session.execute(
                    select(PermanentDeletionOperation.id).where(
                        PermanentDeletionOperation.root_entity_id.in_(submission_ids)
                    )
                )
            ).scalars()
        )
        if operation_ids:
            await session.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id.in_(operation_ids)
                )
            )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id.in_(submission_ids))
        )
        await session.execute(delete(Archive).where(Archive.course_id.in_(course_ids)))
        if wish_ids:
            await session.execute(delete(ArchiveWish).where(ArchiveWish.id.in_(wish_ids)))
        await session.execute(delete(Course).where(Course.id.in_(course_ids)))
        await session.commit()


def _edit_data(course_id: int, **overrides) -> dict[str, str]:
    payload = {
        "course_id": str(course_id),
        "professor": "Edited Professor",
        "academic_year": "1151",
        "archive_type": "quiz",
        "sequence": "2",
        "has_answers": "true",
    }
    payload.update({key: str(value) for key, value in overrides.items()})
    return payload


@pytest.mark.asyncio
async def test_owner_pending_overlay_is_opt_in_and_actor_scoped(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    other = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    new_course, new_course_submission = await _create_context(
        session_maker,
        requester_id=int(owner.id),
        requested_course_name="Requested course",
    )
    new_category, new_category_submission = await _create_context(
        session_maker,
        requester_id=int(owner.id),
        requested_course_name="Requested category course",
        requested_category_key="requested-category",
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        default = await client.get(f"/courses/{course.id}/archives")
        assert default.status_code == 200
        assert default.json() == []

        visible = await client.get(
            f"/courses/{course.id}/archives?include_owner_pending=true"
        )
        assert visible.status_code == 200
        assert visible.json() == [
            {
                "item_kind": "pending_submission",
                "submission_id": submission.id,
                "course_id": course.id,
                "name": "midterm1",
                "academic_year": 1151,
                "archive_type": "midterm",
                "professor": "Owner Pending Professor",
                "has_answers": False,
                "status": "pending",
                "created_at": visible.json()[0]["created_at"],
                "can_preview": True,
                "can_edit": True,
                "can_withdraw": True,
            }
        ]
        assert "object_name" not in visible.json()[0]

        for actor_id, is_admin in ((other.id, False), (admin.id, True)):
            app.dependency_overrides[get_current_user] = _override_user(
                int(actor_id), is_admin=is_admin
            )
            hidden = await client.get(
                f"/courses/{course.id}/archives?include_owner_pending=true"
            )
            assert hidden.status_code == 200
            assert hidden.json() == []

        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        for excluded_course in (new_course, new_category):
            excluded = await client.get(
                f"/courses/{excluded_course.id}/archives?include_owner_pending=true"
            )
            assert excluded.status_code == 200
            assert excluded.json() == []

        app.dependency_overrides.pop(get_current_user, None)
        anonymous = await client.get(
            f"/courses/public/{course.id}/archives?include_owner_pending=true"
        )
        assert anonymous.status_code == 200
        assert anonymous.json() == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id, new_course.id, new_category.id],
            submission_ids=[
                submission.id,
                new_course_submission.id,
                new_category_submission.id,
            ],
        )


@pytest.mark.asyncio
async def test_owner_pending_overlay_fails_closed_on_ambiguous_course_resolution(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    async with session_maker() as session:
        duplicate = Course(name=course.name, category=course.category)
        session.add(duplicate)
        await session.commit()
        await session.refresh(duplicate)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        response = await client.get(
            f"/courses/{course.id}/archives?include_owner_pending=true"
        )
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id, duplicate.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_preview_is_owner_only_no_store_and_read_only(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    other = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    path = f"/archives/submissions/{submission.id}/pending/preview-file"
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(other.id))
        assert (await client.get(path)).status_code == 404
        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        assert (await client.get(path)).status_code == 403
        assert minio.get_names == []

        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        response = await client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.content == VALID_PDF_BYTES
        assert minio.get_names == [submission.object_name]
        async with session_maker() as session:
            assert (await session.get(ArchiveSubmission, submission.id)).object_name == (
                submission.object_name
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_value",
    [
        SubmissionStatus.APPROVED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.TAKEDOWN,
        SubmissionStatus.DELETED,
    ],
)
async def test_owner_pending_routes_reject_non_pending_before_storage(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
    status_value,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id), status=status_value
    )
    if status_value == SubmissionStatus.DELETED:
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored.deleted_at = datetime.now(UTC)
            stored.previous_status = SubmissionStatus.PENDING
            await session.commit()
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        overlay = await client.get(
            f"/courses/{course.id}/archives?include_owner_pending=true"
        )
        preview = await client.get(
            f"/archives/submissions/{submission.id}/pending/preview-file"
        )
        withdraw = await client.post(
            f"/archives/submissions/{submission.id}/withdraw"
        )
        edit = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert overlay.status_code == 200
        assert all(
            item["item_kind"] != "pending_submission" for item in overlay.json()
        )
        assert {preview.status_code, withdraw.status_code, edit.status_code} == {409}
        assert all(
            response.json()["detail"]["code"] == "archive_submission_stale_state"
            for response in (preview, withdraw, edit)
        )
        assert minio.get_names == []
        assert minio.put_names == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_edit_rejects_admin_and_inactive_course(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    path = f"/archives/submissions/{submission.id}/pending"
    try:
        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        assert (await client.patch(path, data=_edit_data(course.id))).status_code == 403

        async with session_maker() as session:
            stored_course = await session.get(Course, course.id)
            stored_course.deleted_at = datetime.now(UTC)
            await session.commit()
        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        assert (await client.patch(path, data=_edit_data(course.id))).status_code == 404
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.name == submission.name
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_edit_normalizes_exam_kinds_and_rejects_invalid_inputs(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    path = f"/archives/submissions/{submission.id}/pending"
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        cases = [
            ({"archive_type": "midterm", "sequence": 3}, "midterm3"),
            ({"archive_type": "quiz", "sequence": 4}, "quiz4"),
            ({"archive_type": "final", "sequence": ""}, "final"),
            (
                {"archive_type": "other", "sequence": "", "other_name": "makeup2"},
                "makeup2",
            ),
        ]
        for overrides, expected in cases:
            response = await client.patch(path, data=_edit_data(course.id, **overrides))
            assert response.status_code == 200
            assert response.json()["name"] == expected

        invalid_payloads = [
            _edit_data(course.id, archive_type="midterm", sequence=""),
            _edit_data(course.id, archive_type="final", sequence=1),
            _edit_data(
                course.id,
                archive_type="other",
                sequence="",
                other_name="自由 輸入",
            ),
            _edit_data(course.id, academic_year=1153),
            _edit_data(course.id, professor="   "),
        ]
        for payload in invalid_payloads:
            assert (await client.patch(path, data=payload)).status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_replacement_upload_failure_keeps_old_pointer(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    old_key = submission.object_name
    minio = _VersionedMinio(old_key)
    minio.fail_put = True
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        response = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert response.status_code == 500
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.object_name == old_key
            operations = list(
                (
                    await session.execute(
                        select(PermanentDeletionOperation).where(
                            PermanentDeletionOperation.root_entity_id == submission.id
                        )
                    )
                ).scalars()
            )
            assert operations == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_replacement_commit_failure_rolls_back_and_compensates(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    old_key = submission.object_name
    minio = _VersionedMinio(old_key)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    original_commit = AsyncSession.commit
    fail_next_commit = True

    async def fail_request_commit_once(self):
        nonlocal fail_next_commit
        if fail_next_commit:
            fail_next_commit = False
            raise RuntimeError("injected owner-edit commit failure")
        return await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_request_commit_once)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        response = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert response.status_code == 500
        assert len(minio.put_names) == 1
        new_key = minio.put_names[0]
        assert (new_key, None) in minio.removals
        assert new_key not in minio.versions
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.object_name == old_key
            operations = list(
                (
                    await session.execute(
                        select(PermanentDeletionOperation).where(
                            PermanentDeletionOperation.root_entity_id == submission.id
                        )
                    )
                ).scalars()
            )
            assert operations == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_withdraw_preserves_object_and_restores_to_pending(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        response = await client.post(
            f"/archives/submissions/{submission.id}/withdraw"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
        assert response.json()["previous_status"] == "pending"
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.PENDING
            assert stored.created_archive_id is None
            assert stored.object_name == submission.object_name
            assert stored.owner_self_delete_consumed is False
        assert minio.removals == []

        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        restored = await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": submission.id},
        )
        assert restored.status_code == 200
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.PENDING
            assert stored.previous_status is None
            assert stored.object_name == submission.object_name
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_edit_is_constrained_and_server_normalized(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    other = await make_user()
    source_course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    async with session_maker() as session:
        target = Course(
            name=f"Target Course {uuid.uuid4().hex}",
            name_en="Target Course English",
            category=CourseCategory.SOPHOMORE.value,
        )
        session.add(target)
        await session.commit()
        await session.refresh(target)
    old_revision = compute_archive_submission_review_revision(submission)
    path = f"/archives/submissions/{submission.id}/pending"
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(other.id))
        assert (await client.patch(path, data=_edit_data(target.id))).status_code == 404

        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        response = await client.patch(
            path,
            data={
                **_edit_data(target.id),
                "status": "approved",
                "owner_id": str(other.id),
                "object_name": "attacker-controlled.pdf",
                "requested_course_name": "Injected course",
            },
        )
        assert response.status_code == 200
        assert response.json()["name"] == "quiz2"
        assert response.json()["course_id"] == target.id
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.subject == target.name
            assert stored.category == target.category
            assert stored.requested_course_name_en == target.name_en
            assert stored.professor == "Edited Professor"
            assert stored.academic_year == 1151
            assert stored.archive_type == ArchiveType.QUIZ
            assert stored.name == "quiz2"
            assert stored.has_answers is True
            assert stored.status == SubmissionStatus.PENDING
            assert stored.requester_id == owner.id
            assert stored.owner_id is None
            assert stored.object_name == submission.object_name
            assert stored.requested_course_name is None
            assert compute_archive_submission_review_revision(stored) != old_revision
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[source_course.id, target.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_course_name", "requested_category_key"),
    [("New course", None), ("New course", "new-category")],
)
async def test_owner_pending_routes_exclude_requested_parent_submissions(
    client: AsyncClient,
    session_maker,
    make_user,
    requested_course_name,
    requested_category_key,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker,
        requester_id=int(owner.id),
        requested_course_name=requested_course_name,
        requested_category_key=requested_category_key,
    )
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        preview = await client.get(
            f"/archives/submissions/{submission.id}/pending/preview-file"
        )
        withdraw = await client.post(
            f"/archives/submissions/{submission.id}/withdraw"
        )
        edit = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
        )
        assert {preview.status_code, withdraw.status_code, edit.status_code} == {409}
        assert all(
            response.json()["detail"]["code"]
            == "owner_pending_submission_not_eligible"
            for response in (preview, withdraw, edit)
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_edit_preserves_help_upload_target(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    async with session_maker() as session:
        wish = ArchiveWish(
            title="Owner pending edit wish",
            target_key=f"owner-pending-{uuid.uuid4().hex}",
            course_id=course.id,
            subject=course.name,
            category=course.category,
            name=submission.name,
            academic_year=submission.academic_year,
            archive_type=submission.archive_type,
            professor=submission.professor,
            creator_id=owner.id,
        )
        session.add(wish)
        await session.commit()
        await session.refresh(wish)
        stored = await session.get(ArchiveSubmission, submission.id)
        stored.source_wish_id = wish.id
        await session.commit()
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        mismatch = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "wish_upload_target_mismatch"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
            wish_ids=[wish.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_pdf_replacement_is_atomic_and_stales_admin_review(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    old_key = submission.object_name
    old_revision = compute_archive_submission_review_revision(submission)
    minio = _VersionedMinio(old_key)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        response = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert response.status_code == 200
        assert len(minio.put_names) == 1
        new_key = minio.put_names[0]
        assert new_key.startswith(f"archive-submissions/{owner.id}/")
        assert new_key != old_key
        assert (old_key, "v-old") in minio.removals
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.object_name == new_key
            assert compute_archive_submission_review_revision(stored) != old_revision
            operation = (
                await session.execute(
                    select(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.root_entity_id == submission.id
                    )
                )
            ).scalar_one()
            assert operation.status == PermanentDeletionStatus.COMPLETED

        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        stale = await client.post(
            f"/archives/admin/submissions/{submission.id}/approve",
            json={
                "expected_status": "pending",
                "expected_revision": old_revision,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "archive_submission_stale_revision"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_pdf_replacement_retains_retryable_cleanup_authority(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    old_key = submission.object_name
    minio = _VersionedMinio(old_key)
    minio.retry_delete = True
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        response = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert response.status_code == 200
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.object_name == minio.put_names[0]
            operation = (
                await session.execute(
                    select(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.root_entity_id == submission.id
                    )
                )
            ).scalar_one()
            object_row = (
                await session.execute(
                    select(PermanentDeletionObject).where(
                        PermanentDeletionObject.operation_id == operation.id
                    )
                )
            ).scalar_one()
            assert operation.status == PermanentDeletionStatus.RETRYABLE_FAILED
            assert object_row.object_key == old_key
            assert object_row.version_id == "v-old"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_pending_pdf_replacement_fails_before_upload_when_state_or_identity_is_stale(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    course, submission = await _create_context(
        session_maker,
        requester_id=int(owner.id),
        status=SubmissionStatus.REJECTED,
    )
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
    try:
        stale = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "archive_submission_stale_state"
        assert minio.put_names == []

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored.status = SubmissionStatus.PENDING
            await session.commit()
        minio.versioning_enabled = False
        unavailable = await client.patch(
            f"/archives/submissions/{submission.id}/pending",
            data=_edit_data(course.id),
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
        assert unavailable.status_code == 503
        assert minio.put_names == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_admin_review_commit_wins_owner_replacement_stales_before_upload(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    revision = compute_archive_submission_review_revision(submission)
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    review_at_commit = asyncio.Event()
    release_review = asyncio.Event()
    original_enqueue = archives_service.enqueue_submission_status_notification

    async def enqueue_and_hold(db, submission_row, new_status):
        await original_enqueue(db, submission_row, new_status)
        await db.flush()
        review_at_commit.set()
        await asyncio.wait_for(release_review.wait(), timeout=10)

    monkeypatch.setattr(
        archives_service,
        "enqueue_submission_status_notification",
        enqueue_and_hold,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        admin_task = asyncio.create_task(
            client.post(
                f"/archives/admin/submissions/{submission.id}/approve",
                json={
                    "expected_status": "pending",
                    "expected_revision": revision,
                },
            )
        )
        await asyncio.wait_for(review_at_commit.wait(), timeout=10)

        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        owner_task = asyncio.create_task(
            client.patch(
                f"/archives/submissions/{submission.id}/pending",
                data=_edit_data(course.id),
                files={
                    "file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")
                },
            )
        )
        await asyncio.sleep(0.1)
        assert not owner_task.done()
        release_review.set()
        admin_response = await asyncio.wait_for(admin_task, timeout=10)
        owner_response = await asyncio.wait_for(owner_task, timeout=10)
        assert admin_response.status_code == 200
        assert owner_response.status_code == 409
        assert owner_response.json()["detail"]["code"] == "archive_submission_stale_state"
        assert minio.put_names == []
    finally:
        release_review.set()
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )


@pytest.mark.asyncio
async def test_owner_replacement_commit_wins_admin_old_revision_stales(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    course, submission = await _create_context(
        session_maker, requester_id=int(owner.id)
    )
    revision = compute_archive_submission_review_revision(submission)
    minio = _VersionedMinio(submission.object_name)
    monkeypatch.setattr("app.api.services.archives.get_minio_client", lambda: minio)
    edit_at_commit = asyncio.Event()
    release_edit = asyncio.Event()
    original_enqueue = (
        archives_service.enqueue_superseded_archive_submission_object_cleanup
    )

    async def enqueue_and_hold(db, **kwargs):
        operation = await original_enqueue(db, **kwargs)
        edit_at_commit.set()
        await asyncio.wait_for(release_edit.wait(), timeout=10)
        return operation

    monkeypatch.setattr(
        archives_service,
        "enqueue_superseded_archive_submission_object_cleanup",
        enqueue_and_hold,
    )
    try:
        app.dependency_overrides[get_current_user] = _override_user(int(owner.id))
        owner_task = asyncio.create_task(
            client.patch(
                f"/archives/submissions/{submission.id}/pending",
                data=_edit_data(course.id),
                files={
                    "file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")
                },
            )
        )
        await asyncio.wait_for(edit_at_commit.wait(), timeout=10)

        app.dependency_overrides[get_current_user] = _override_user(
            int(admin.id), is_admin=True
        )
        admin_task = asyncio.create_task(
            client.post(
                f"/archives/admin/submissions/{submission.id}/approve",
                json={
                    "expected_status": "pending",
                    "expected_revision": revision,
                },
            )
        )
        await asyncio.sleep(0.1)
        assert not admin_task.done()
        release_edit.set()
        owner_response = await asyncio.wait_for(owner_task, timeout=10)
        admin_response = await asyncio.wait_for(admin_task, timeout=10)
        assert owner_response.status_code == 200
        assert admin_response.status_code == 409
        assert admin_response.json()["detail"]["code"] == "archive_submission_stale_revision"
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.status == SubmissionStatus.PENDING
            assert stored.created_archive_id is None
            assert stored.object_name == minio.put_names[0]
    finally:
        release_edit.set()
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            course_ids=[course.id],
            submission_ids=[submission.id],
        )
