from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from minio import Minio
from minio.versioningconfig import ENABLED, VersioningConfig
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import trash
from app.main import app
from app.models.models import (
    Archive,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    ArchiveWishReport,
    CommentReport,
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    Notification,
    PermanentDeletionObject,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    PersonalNotification,
    SubmissionStatus,
    SystemIssueReport,
    TrashEntityType,
    TrashItem,
    User,
    UserRoles,
)
from app.services import permanent_deletion as permanent_deletion_service
from app.services.permanent_deletion import (
    PermanentDeletionError,
    _owned_operation,
    accept_permanent_deletion,
    claim_permanent_deletion,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_reconciler import reconcile_due_once
from app.services.permanent_deletion_storage import (
    ExactVersionMinioAdapter,
    StorageSafetyError,
)
from app.utils.auth import get_current_user


class FakeVersionedMinio:
    def __init__(self, key: str, version_id: str = "v1") -> None:
        self.key = key
        self.status = "Enabled"
        self.versions: list[tuple[str, str, bool]] = [(key, version_id, False)]
        self.removals: list[tuple[str, str, str | None]] = []
        self.unknown_once = False
        self.retryable_once = False
        self.replacement_during_delete: str | None = None
        self.replacement_on_history_call: tuple[int, str] | None = None
        self.history_calls = 0
        self.on_history: Callable[[], None] | None = None
        self.on_remove: Callable[[], None] | None = None

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status=self.status)

    def list_objects(self, _bucket: str, **_kwargs):
        self.history_calls += 1
        if self.on_history is not None:
            self.on_history()
        if (
            self.replacement_on_history_call is not None
            and self.history_calls == self.replacement_on_history_call[0]
        ):
            self.versions.append((self.key, self.replacement_on_history_call[1], False))
            self.replacement_on_history_call = None
        return [
            SimpleNamespace(
                object_name=key,
                version_id=version_id,
                is_delete_marker=is_marker,
            )
            for key, version_id, is_marker in self.versions
        ]

    def stat_object(self, _bucket: str, key: str, version_id: str | None = None):
        rows = [
            row
            for row in self.versions
            if row[0] == key
            and not row[2]
            and (version_id is None or row[1] == version_id)
        ]
        if not rows:
            from minio.error import S3Error

            raise S3Error(
                None,
                "NoSuchVersion",
                "missing",
                key,
                "request-id",
                "host-id",
            )
        return SimpleNamespace(object_name=key, version_id=rows[-1][1])

    def remove_object(
        self, bucket: str, key: str, version_id: str | None = None
    ) -> None:
        self.removals.append((bucket, key, version_id))
        if self.retryable_once:
            self.retryable_once = False
            from minio.error import S3Error

            raise S3Error(
                None,
                "ServiceUnavailable",
                "synthetic retryable failure",
                key,
                "request-id",
                "host-id",
            )
        if self.replacement_during_delete is not None:
            self.versions.append((key, self.replacement_during_delete, False))
            self.replacement_during_delete = None
        self.versions = [
            row for row in self.versions if not (row[0] == key and row[1] == version_id)
        ]
        if self.on_remove is not None:
            self.on_remove()
        if self.unknown_once:
            self.unknown_once = False
            raise TimeoutError("synthetic unknown delete outcome")


class UnknownOnceRealMinio:
    def __init__(self, client: Minio) -> None:
        self.client = client
        self.remove_calls: list[tuple[str, str, str | None]] = []
        self.raise_unknown_once = True

    def __getattr__(self, name: str):
        return getattr(self.client, name)

    def remove_object(
        self, bucket: str, key: str, version_id: str | None = None
    ) -> None:
        self.remove_calls.append((bucket, key, version_id))
        self.client.remove_object(bucket, key, version_id=version_id)
        if self.raise_unknown_once:
            self.raise_unknown_once = False
            raise TimeoutError("synthetic unknown outcome after real exact delete")


class MutableLeaseClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


async def _create_deleted_pair(session_maker, *, requester_id: int):
    marker = uuid.uuid4().hex
    deleted_at = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=f"saga-{marker[:12]}",
            name=f"Saga category {marker}",
            label=f"Saga category {marker}",
        )
        course = Course(name=f"Saga course {marker}", category=category.key)
        session.add(category)
        session.add(course)
        await session.flush()
        key = f"archive/saga-{marker}.pdf"
        archive = Archive(
            name=f"Saga archive {marker}",
            academic_year=115,
            archive_type=ArchiveType.FINAL,
            professor="Saga Professor",
            object_name=key,
            uploader_id=requester_id,
            course_id=course.id,
            deleted_at=deleted_at,
            deleted_by_id=requester_id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=category.key,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=key,
            requester_id=requester_id,
            owner_id=requester_id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
            deleted_at=deleted_at,
            deleted_by_id=requester_id,
        )
        session.add(submission)
        await session.flush()
        event = ArchiveSubmissionEvent(
            submission_id=submission.id,
            submitted_at=datetime(2026, 8, 20, 3, 4, 5, tzinfo=UTC),
        )
        notification = PersonalNotification(
            user_id=requester_id,
            notification_type="archive_submission_approved",
            title="Saga notification",
            message="Retain me",
            source_type="archive_submission",
            source_id=submission.id,
            dedupe_key=f"saga-{marker}",
        )
        session.add(event)
        session.add(notification)
        await session.commit()
        for row in (category, course, archive, submission, event, notification):
            await session.refresh(row)
    return category, course, archive, submission, event, notification


async def _cleanup_pair_and_operation(
    session_maker,
    *,
    operation_id: int | None,
    category_id: int,
    course_id: int,
    archive_id: int,
    submission_id: int,
    event_id: int,
    notification_id: int,
) -> None:
    async with session_maker() as session:
        if operation_id is not None:
            await session.execute(
                delete(PermanentDeletionObject).where(
                    PermanentDeletionObject.operation_id == operation_id
                )
            )
            await session.execute(
                delete(PermanentDeletionTarget).where(
                    PermanentDeletionTarget.operation_id == operation_id
                )
            )
            await session.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id == operation_id
                )
            )
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.id == notification_id
            )
        )
        await session.execute(
            delete(ArchiveSubmissionEvent).where(ArchiveSubmissionEvent.id == event_id)
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.execute(
            delete(CourseCategoryConfig).where(CourseCategoryConfig.id == category_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_reconciler_recovers_unknown_exact_delete_without_second_delete(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
    client = FakeVersionedMinio(archive.object_name, "stage5fe-unknown-v1")
    client.unknown_once = True
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fe-test")
    operation_id: int | None = None
    now = datetime(2026, 8, 28, 4, 30, tzinfo=UTC)
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE,
                root_entity_id=int(archive.id),
                idempotency_key=f"stage5fe:unknown:{archive.id}",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)

        first = await reconcile_due_once(
            session_maker=session_maker,
            storage_factory=lambda: storage,
            now=now,
        )
        assert first.pending == 1
        async with session_maker() as session:
            pending = await session.get(PermanentDeletionOperation, operation_id)
            assert pending.status == PermanentDeletionStatus.VERIFICATION_REQUIRED

        second = await reconcile_due_once(
            session_maker=session_maker,
            storage_factory=lambda: storage,
            now=now + timedelta(seconds=1),
        )
        assert second.completed == 1
        assert client.removals == [
            ("stage5fe-test", archive.object_name, "stage5fe-unknown-v1")
        ]
        async with session_maker() as session:
            retained_event = await session.get(ArchiveSubmissionEvent, event.id)
            assert retained_event is not None
            assert retained_event.submission_id is None
            assert retained_event.submitted_at == event.submitted_at
            assert await session.get(PersonalNotification, notification.id) is not None
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_concurrent_reconciler_passes_do_not_double_delete_exact_version(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
    client = FakeVersionedMinio(archive.object_name, "stage5fe-concurrent-v1")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fe-test")
    operation_id: int | None = None
    now = datetime(2026, 8, 28, 4, 45, tzinfo=UTC)
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE,
                root_entity_id=int(archive.id),
                idempotency_key=f"stage5fe:concurrent:{archive.id}",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)

        await asyncio.gather(
            reconcile_due_once(
                session_maker=session_maker,
                storage_factory=lambda: storage,
                now=now,
            ),
            reconcile_due_once(
                session_maker=session_maker,
                storage_factory=lambda: storage,
                now=now,
            ),
        )

        assert client.removals == [
            ("stage5fe-test", archive.object_name, "stage5fe-concurrent-v1")
        ]
        async with session_maker() as session:
            completed = await session.get(PermanentDeletionOperation, operation_id)
            assert completed.status == PermanentDeletionStatus.COMPLETED
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_db_only_acceptance_reuses_intent_and_completes_idempotently(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    now = datetime(2026, 8, 27, 2, 0, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Deleted course request",
            category="physics-department",
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=now,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

        first = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.COURSE_SUBMISSION,
            root_entity_id=request.id,
            idempotency_key=f"course-request:{request.id}:delete",
            requested_by_user_id=requester.id,
            storage=None,
            now=now,
        )
        repeated = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.COURSE_SUBMISSION,
            root_entity_id=request.id,
            idempotency_key=f"course-request:{request.id}:delete",
            requested_by_user_id=requester.id,
            storage=None,
            now=now + timedelta(seconds=1),
        )
        assert repeated.id == first.id

        result = await process_one_permanent_deletion(
            session,
            operation_id=first.id,
            storage=None,
            now=now + timedelta(minutes=1),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
        )
        assert result == PermanentDeletionStatus.COMPLETED
        assert await session.get(CourseSubmission, request.id) is None

        again = await process_one_permanent_deletion(
            session,
            operation_id=first.id,
            storage=None,
            now=now + timedelta(minutes=2),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=2, seconds=1)),
        )
        assert again == PermanentDeletionStatus.COMPLETED


@pytest.mark.asyncio
async def test_public_single_delete_reports_accepted_then_completed_truth(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    minio = FakeVersionedMinio(archive.object_name, "v-route")
    minio.unknown_once = True
    storage = ExactVersionMinioAdapter(minio, bucket_name="stage5fc-test")
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    operation_id = None

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            requester.id, is_admin=False
        )
        forbidden = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert forbidden.status_code == 403
        assert minio.removals == []

        app.dependency_overrides[get_current_user] = _override_user(
            requester.id, is_admin=True
        )
        accepted = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert accepted.status_code == 202
        accepted_body = accepted.json()
        operation_id = accepted_body["operation_id"]
        assert accepted_body["status"] == "VERIFICATION_REQUIRED"
        assert accepted_body["root_type"] == "archive_submission"
        assert "object_key" not in accepted_body
        assert "version_id" not in accepted_body

        listed = await client.get("/trash", params={"item_type": "archive_submission"})
        assert listed.status_code == 200
        pending = next(item for item in listed.json() if item["id"] == submission.id)
        assert pending["status"] == "deleted"
        assert pending["canRestore"] is False
        assert pending["canPermanentDelete"] is False
        assert pending["permanent_deletion"]["operation_id"] == operation_id
        assert pending["permanent_deletion"]["status"] == "VERIFICATION_REQUIRED"

        blocked_restore = await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": submission.id},
        )
        assert blocked_restore.status_code == 409
        assert blocked_restore.json()["detail"]["code"] == (
            "permanent_deletion_already_accepted"
        )

        status_response = await client.get(f"/trash/permanent-deletions/{operation_id}")
        assert status_response.status_code == 200
        assert status_response.json()["can_retry"] is True

        completed = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"
        assert len(minio.removals) == 1

        repeated = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert repeated.status_code == 200
        assert repeated.json()["operation_id"] == operation_id
        assert repeated.json()["status"] == "COMPLETED"
        assert len(minio.removals) == 1

        async with session_maker() as session:
            assert await session.get(Archive, archive.id) is None
            assert await session.get(ArchiveSubmission, submission.id) is None
            retained_event = await session.get(ArchiveSubmissionEvent, event.id)
            assert retained_event is not None
            assert retained_event.submission_id is None
            assert retained_event.submitted_at == event.submitted_at
            assert await session.get(PersonalNotification, notification.id) is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_public_db_only_remaining_root_completes_and_reuses_operation(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    admin = await make_user(is_admin=True)
    deleted_at = datetime(2026, 8, 27, 19, 10, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Stage 5F-D durable course request",
            category="physics-department",
            requester_id=admin.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=deleted_at,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

    operation_id = None
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        completed = await client.delete(f"/trash/course_submission/{request.id}")
        assert completed.status_code == 200
        body = completed.json()
        operation_id = body["operation_id"]
        assert body["root_type"] == TrashEntityType.COURSE_SUBMISSION
        assert body["root_id"] == request.id
        assert body["status"] == PermanentDeletionStatus.COMPLETED

        repeated = await client.delete(f"/trash/course_submission/{request.id}")
        assert repeated.status_code == 200
        assert repeated.json()["operation_id"] == operation_id
        assert repeated.json()["status"] == PermanentDeletionStatus.COMPLETED

        async with session_maker() as session:
            assert await session.get(CourseSubmission, request.id) is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if operation_id is not None:
                await session.execute(
                    delete(PermanentDeletionTarget).where(
                        PermanentDeletionTarget.operation_id == operation_id
                    )
                )
                await session.execute(
                    delete(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.id == operation_id
                    )
                )
            await session.execute(
                delete(CourseSubmission).where(CourseSubmission.id == request.id)
            )
            await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "root_type",
    [
        TrashEntityType.COURSE_CATEGORY,
        TrashEntityType.COURSE_SUBMISSION,
        TrashEntityType.SYSTEM_ISSUE_REPORT,
        TrashEntityType.COMMENT_REPORT,
        TrashEntityType.ARCHIVE_WISH_REPORT,
        TrashEntityType.ARCHIVE_REPORT,
        TrashEntityType.NOTIFICATION,
        TrashEntityType.USER,
    ],
)
async def test_every_remaining_root_accepts_completes_and_reuses_durable_operation(
    root_type: TrashEntityType,
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await make_user(is_admin=True)
    now = datetime(2026, 8, 27, 19, 15, tzinfo=UTC)
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        if root_type == TrashEntityType.COURSE_CATEGORY:
            root = CourseCategoryConfig(
                key=f"durable-{marker[:12]}",
                name=f"Durable category {marker}",
                label=f"Durable category {marker}",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.COURSE_SUBMISSION:
            root = CourseSubmission(
                name=f"Durable course request {marker}",
                category=f"missing-{marker[:12]}",
                requester_id=admin.id,
                status=SubmissionStatus.DELETED,
                previous_status=SubmissionStatus.PENDING,
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.SYSTEM_ISSUE_REPORT:
            root = SystemIssueReport(
                reporter_user_id=admin.id,
                report_type="other",
                title=f"Durable issue {marker}",
                description="Stage 5F-D route matrix",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.COMMENT_REPORT:
            root = CommentReport(
                reporter_user_id=admin.id,
                reason="other",
                comment_content_snapshot="Durable comment snapshot",
                comment_author_name_snapshot="Durable author",
                comment_created_at_snapshot=now,
                archive_name_snapshot="Durable archive",
                course_name_snapshot="Durable course",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.ARCHIVE_WISH_REPORT:
            root = ArchiveWishReport(
                reporter_user_id=admin.id,
                wish_title_snapshot=f"Durable wish {marker}",
                target_summary_snapshot="Durable target",
                reason="other",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.ARCHIVE_REPORT:
            root = ArchiveReport(
                reporter_user_id=admin.id,
                reporter_name_snapshot=admin.name,
                archive_id_snapshot=900_000,
                reason="other",
                archive_name_snapshot=f"Durable archive {marker}",
                course_name_snapshot="Durable course",
                academic_year_snapshot=115,
                archive_type_snapshot=ArchiveType.FINAL.value,
                professor_snapshot="Durable professor",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        elif root_type == TrashEntityType.NOTIFICATION:
            root = Notification(
                title=f"Durable notification {marker}",
                body="Stage 5F-D route matrix",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        else:
            root = User(
                email=f"durable-{marker}@example.com",
                name=f"Durable user {marker}",
                password_hash="not-used",
                deleted_at=now,
                deleted_by_id=admin.id,
            )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        root_id = int(root.id)
        root_model = type(root)

    if root_type == TrashEntityType.USER:
        storage = ExactVersionMinioAdapter(
            FakeVersionedMinio(f"unused/{marker}.pdf"),
            bucket_name="stage5fd-empty-user-test",
        )
        monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    else:
        monkeypatch.setattr(
            trash,
            "_permanent_deletion_storage",
            lambda: pytest.fail("DB-only root must not initialize MinIO"),
        )

    operation_id = None
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        completed = await client.delete(f"/trash/{root_type.value}/{root_id}")
        assert completed.status_code == 200
        body = completed.json()
        operation_id = body["operation_id"]
        assert body["root_type"] == root_type.value
        assert body["root_id"] == root_id
        assert body["status"] == PermanentDeletionStatus.COMPLETED

        repeated = await client.delete(f"/trash/{root_type.value}/{root_id}")
        assert repeated.status_code == 200
        assert repeated.json()["operation_id"] == operation_id
        assert repeated.json()["status"] == PermanentDeletionStatus.COMPLETED

        async with session_maker() as session:
            assert await session.get(root_model, root_id) is None
            assert (
                int(
                    await session.scalar(
                        select(func.count(PermanentDeletionOperation.id)).where(
                            PermanentDeletionOperation.root_entity_type
                            == root_type.value,
                            PermanentDeletionOperation.root_entity_id == root_id,
                        )
                    )
                    or 0
                )
                == 1
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if operation_id is not None:
                await session.execute(
                    delete(PermanentDeletionTarget).where(
                        PermanentDeletionTarget.operation_id == operation_id
                    )
                )
                await session.execute(
                    delete(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.id == operation_id
                    )
                )
            await session.execute(delete(root_model).where(root_model.id == root_id))
            await session.commit()


@pytest.mark.asyncio
async def test_remaining_root_restore_is_blocked_after_durable_acceptance(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await make_user(is_admin=True)
    deleted_at = datetime(2026, 8, 27, 19, 20, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Stage 5F-D accepted course request",
            category="physics-department",
            requester_id=admin.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=deleted_at,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

    async def leave_accepted(_db, operation):
        return operation

    monkeypatch.setattr(
        trash,
        "_process_public_permanent_deletion_once",
        leave_accepted,
    )
    operation_id = None
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        accepted = await client.delete(f"/trash/course_submission/{request.id}")
        assert accepted.status_code == 202
        operation_id = accepted.json()["operation_id"]
        assert accepted.json()["status"] == PermanentDeletionStatus.ACCEPTED

        restore = await client.post(
            "/trash/restore",
            json={
                "item_type": TrashEntityType.COURSE_SUBMISSION,
                "item_id": request.id,
            },
        )
        assert restore.status_code == 409
        assert restore.json()["detail"]["code"] == (
            "permanent_deletion_already_accepted"
        )
        async with session_maker() as session:
            stored = await session.get(CourseSubmission, request.id)
            assert stored is not None
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.PENDING
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if operation_id is not None:
                await session.execute(
                    delete(PermanentDeletionTarget).where(
                        PermanentDeletionTarget.operation_id == operation_id
                    )
                )
                await session.execute(
                    delete(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.id == operation_id
                    )
                )
            await session.execute(
                delete(CourseSubmission).where(CourseSubmission.id == request.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_user_root_with_deleted_storage_children_uses_exact_version_saga(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await make_user()
    admin = await make_user(is_admin=True)
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=owner.id)
    async with session_maker() as session:
        stored_owner = await session.get(User, owner.id)
        stored_owner.deleted_at = datetime(2026, 8, 27, 19, 25, tzinfo=UTC)
        stored_owner.deleted_by_id = admin.id
        await session.commit()

    minio = FakeVersionedMinio(archive.object_name, "user-root-v1")
    storage = ExactVersionMinioAdapter(minio, bucket_name="stage5fd-user-test")
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    operation_id = None
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        completed = await client.delete(f"/trash/user/{owner.id}")
        assert completed.status_code == 200
        body = completed.json()
        operation_id = body["operation_id"]
        assert body["root_type"] == TrashEntityType.USER
        assert body["status"] == PermanentDeletionStatus.COMPLETED
        assert minio.removals == [
            ("stage5fd-user-test", archive.object_name, "user-root-v1")
        ]

        repeated = await client.delete(f"/trash/user/{owner.id}")
        assert repeated.status_code == 200
        assert repeated.json()["operation_id"] == operation_id
        assert minio.removals == [
            ("stage5fd-user-test", archive.object_name, "user-root-v1")
        ]

        async with session_maker() as session:
            assert await session.get(User, owner.id) is None
            assert await session.get(Archive, archive.id) is None
            assert await session.get(ArchiveSubmission, submission.id) is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_bulk_mixed_truth_reuses_operations_and_preserves_restore_boundaries(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await make_user()
    admin = await make_user(is_admin=True)
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    deleted_at = datetime(2026, 8, 27, 19, 30, tzinfo=UTC)
    async with session_maker() as session:
        stored_category = await session.get(CourseCategoryConfig, category.id)
        stored_category.deleted_at = deleted_at
        stored_category.deleted_by_id = admin.id
        stored_category.pre_delete_is_active = True
        stored_category.is_active = False
        bulletin = Notification(
            title="Stage 5F-D completed bulk item",
            body="DB-only bulk truth",
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
        )
        session.add(bulletin)
        await session.commit()
        await session.refresh(bulletin)

    snapshot = [
        TrashItem(
            item_type=TrashEntityType.ARCHIVE_SUBMISSION,
            id=submission.id,
            display_name="Pending exact storage item",
            deleted_at=deleted_at,
        ),
        TrashItem(
            item_type=TrashEntityType.COURSE_CATEGORY,
            id=category.id,
            display_name="Blocked category item",
            deleted_at=deleted_at,
        ),
        TrashItem(
            item_type=TrashEntityType.NOTIFICATION,
            id=bulletin.id,
            display_name="Completed notification item",
            deleted_at=deleted_at,
        ),
    ]
    monkeypatch.setattr(trash, "list_trash_items", AsyncMock(return_value=snapshot))
    minio = FakeVersionedMinio(archive.object_name, "bulk-mixed-v1")
    minio.unknown_once = True
    storage = ExactVersionMinioAdapter(minio, bucket_name="stage5fd-bulk-test")
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    operation_ids: set[int] = set()
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        first = await client.delete("/trash/bulk")
        assert first.status_code == 200
        first_body = first.json()
        assert {
            key: first_body[key]
            for key in (
                "requested_count",
                "completed_count",
                "pending_count",
                "manual_review_count",
                "failed_count",
                "skipped_count",
            )
        } == {
            "requested_count": 3,
            "completed_count": 1,
            "pending_count": 1,
            "manual_review_count": 0,
            "failed_count": 1,
            "skipped_count": 0,
        }
        first_by_type = {item["item_type"]: item for item in first_body["results"]}
        assert first_by_type["archive_submission"]["outcome"] == "PENDING"
        assert first_by_type["course_category"]["outcome"] == "FAILED"
        assert first_by_type["notification"]["outcome"] == "COMPLETED"
        assert first_by_type["course_category"]["operation"] is None
        assert minio.removals == [
            ("stage5fd-bulk-test", archive.object_name, "bulk-mixed-v1")
        ]
        pending_operation_id = first_by_type["archive_submission"]["operation"][
            "operation_id"
        ]
        completed_operation_id = first_by_type["notification"]["operation"][
            "operation_id"
        ]
        operation_ids.update({pending_operation_id, completed_operation_id})

        restore_pending = await client.post(
            "/trash/restore",
            json={
                "item_type": TrashEntityType.ARCHIVE_SUBMISSION,
                "item_id": submission.id,
            },
        )
        assert restore_pending.status_code == 409
        assert restore_pending.json()["detail"]["code"] == (
            "permanent_deletion_already_accepted"
        )

        second = await client.delete("/trash/bulk")
        assert second.status_code == 200
        second_body = second.json()
        second_by_type = {item["item_type"]: item for item in second_body["results"]}
        assert second_by_type["archive_submission"]["outcome"] == "COMPLETED"
        assert (
            second_by_type["archive_submission"]["operation"]["operation_id"]
            == pending_operation_id
        )
        assert second_by_type["notification"]["outcome"] == "COMPLETED"
        assert (
            second_by_type["notification"]["operation"]["operation_id"]
            == completed_operation_id
        )
        assert minio.removals == [
            ("stage5fd-bulk-test", archive.object_name, "bulk-mixed-v1")
        ]

        restore_failed = await client.post(
            "/trash/restore",
            json={
                "item_type": TrashEntityType.COURSE_CATEGORY,
                "item_id": category.id,
            },
        )
        assert restore_failed.status_code == 200
        async with session_maker() as session:
            retained = await session.get(ArchiveSubmissionEvent, event.id)
            assert retained is not None
            assert retained.submission_id is None
            assert retained.submitted_at == event.submitted_at
            assert await session.get(PersonalNotification, notification.id) is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if operation_ids:
                await session.execute(
                    delete(PermanentDeletionObject).where(
                        PermanentDeletionObject.operation_id.in_(operation_ids)
                    )
                )
                await session.execute(
                    delete(PermanentDeletionTarget).where(
                        PermanentDeletionTarget.operation_id.in_(operation_ids)
                    )
                )
                await session.execute(
                    delete(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.id.in_(operation_ids)
                    )
                )
            await session.execute(
                delete(Notification).where(Notification.id == bulletin.id)
            )
            await session.commit()
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=None,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_bulk_overlapping_roots_use_one_operation_and_truthful_skip(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await make_user()
    admin = await make_user(is_admin=True)
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    snapshot = [
        TrashItem(
            item_type=TrashEntityType.ARCHIVE_SUBMISSION,
            id=submission.id,
            display_name="Containing submission",
            deleted_at=submission.deleted_at,
        ),
        TrashItem(
            item_type=TrashEntityType.ARCHIVE,
            id=archive.id,
            display_name="Covered archive",
            deleted_at=archive.deleted_at,
        ),
    ]
    monkeypatch.setattr(trash, "list_trash_items", AsyncMock(return_value=snapshot))
    minio = FakeVersionedMinio(archive.object_name, "overlap-v1")
    storage = ExactVersionMinioAdapter(minio, bucket_name="stage5fd-overlap-test")
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    operation_id = None
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        response = await client.delete("/trash/bulk")
        assert response.status_code == 200
        body = response.json()
        assert body["requested_count"] == 2
        assert body["completed_count"] == 1
        assert body["skipped_count"] == 1
        assert body["pending_count"] == 0
        assert body["failed_count"] == 0
        by_type = {item["item_type"]: item for item in body["results"]}
        containing = by_type["archive_submission"]
        covered = by_type["archive"]
        assert containing["outcome"] == "COMPLETED"
        assert covered["outcome"] == "SKIPPED"
        operation_id = containing["operation"]["operation_id"]
        assert covered["operation"]["operation_id"] == operation_id
        assert covered["reason_code"] == "covered_by_permanent_deletion"
        assert minio.removals == [
            ("stage5fd-overlap-test", archive.object_name, "overlap-v1")
        ]
        async with session_maker() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count(PermanentDeletionOperation.id)).where(
                            PermanentDeletionOperation.id == operation_id
                        )
                    )
                    or 0
                )
                == 1
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("STAGE5FD_REAL_MINIO_ENDPOINT"),
    reason="requires the task-owned Stage 5F-D MinIO container",
)
async def test_real_minio_mixed_bulk_user_root_and_stage5e_retention(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = os.environ["STAGE5FD_REAL_MINIO_ENDPOINT"]
    access_key = os.environ["STAGE5FD_REAL_MINIO_ACCESS_KEY"]
    secret_key = os.environ["STAGE5FD_REAL_MINIO_SECRET_KEY"]
    bucket_name = os.environ["STAGE5FD_REAL_MINIO_BUCKET"]
    real_client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )
    if not real_client.bucket_exists(bucket_name):
        real_client.make_bucket(bucket_name)
    real_client.set_bucket_versioning(bucket_name, VersioningConfig(ENABLED))

    owner = await make_user()
    admin = await make_user(is_admin=True)
    (
        category,
        course,
        archive,
        submission,
        event,
        owner_notification,
    ) = await _create_deleted_pair(session_maker, requester_id=owner.id)
    payload = b"stage5fd-real-versioned-object"
    uploaded = real_client.put_object(
        bucket_name,
        archive.object_name,
        BytesIO(payload),
        len(payload),
        content_type="application/pdf",
    )
    assert uploaded.version_id not in {None, "", "null"}

    deleted_at = datetime(2026, 8, 27, 19, 35, tzinfo=UTC)
    async with session_maker() as session:
        stored_category = await session.get(CourseCategoryConfig, category.id)
        stored_category.deleted_at = deleted_at
        stored_category.deleted_by_id = admin.id
        stored_category.pre_delete_is_active = True
        stored_category.is_active = False
        stored_owner = await session.get(User, owner.id)
        stored_owner.deleted_at = deleted_at
        stored_owner.deleted_by_id = admin.id
        bulletin = Notification(
            title="Stage 5F-D real completed item",
            body="Task-owned real MinIO matrix",
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
        )
        retained_notification = PersonalNotification(
            user_id=admin.id,
            notification_type="archive_submission_approved",
            title="Retained real-matrix notification",
            message="Retain after source deletion",
            source_type="archive_submission",
            source_id=submission.id,
            dedupe_key=f"stage5fd-real-{uuid.uuid4().hex}",
        )
        session.add(bulletin)
        session.add(retained_notification)
        await session.commit()
        await session.refresh(bulletin)
        await session.refresh(retained_notification)

    snapshot = [
        TrashItem(
            item_type=TrashEntityType.USER,
            id=owner.id,
            display_name="Pending user storage group",
            deleted_at=deleted_at,
        ),
        TrashItem(
            item_type=TrashEntityType.NOTIFICATION,
            id=bulletin.id,
            display_name="Completed DB-only item",
            deleted_at=deleted_at,
        ),
        TrashItem(
            item_type=TrashEntityType.COURSE_CATEGORY,
            id=category.id,
            display_name="Pre-accept blocked item",
            deleted_at=deleted_at,
        ),
    ]
    monkeypatch.setattr(trash, "list_trash_items", AsyncMock(return_value=snapshot))
    observed_client = UnknownOnceRealMinio(real_client)
    storage = ExactVersionMinioAdapter(observed_client, bucket_name=bucket_name)
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    operation_ids: set[int] = set()
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        first = await client.delete("/trash/bulk")
        assert first.status_code == 200
        first_body = first.json()
        assert {
            key: first_body[key]
            for key in (
                "requested_count",
                "completed_count",
                "pending_count",
                "manual_review_count",
                "failed_count",
                "skipped_count",
            )
        } == {
            "requested_count": 3,
            "completed_count": 1,
            "pending_count": 1,
            "manual_review_count": 0,
            "failed_count": 1,
            "skipped_count": 0,
        }
        first_by_type = {item["item_type"]: item for item in first_body["results"]}
        assert first_by_type["user"]["outcome"] == "PENDING"
        assert first_by_type["notification"]["outcome"] == "COMPLETED"
        assert first_by_type["course_category"]["outcome"] == "FAILED"
        user_operation_id = first_by_type["user"]["operation"]["operation_id"]
        bulletin_operation_id = first_by_type["notification"]["operation"][
            "operation_id"
        ]
        operation_ids.update({user_operation_id, bulletin_operation_id})
        assert observed_client.remove_calls == [
            (bucket_name, archive.object_name, uploaded.version_id)
        ]

        async with session_maker() as session:
            object_record = (
                await session.execute(
                    select(PermanentDeletionObject).where(
                        PermanentDeletionObject.operation_id == user_operation_id
                    )
                )
            ).scalar_one()
            assert object_record.version_id == uploaded.version_id
            assert await session.get(User, owner.id) is not None

        restore_user = await client.post(
            "/trash/restore",
            json={"item_type": TrashEntityType.USER, "item_id": owner.id},
        )
        assert restore_user.status_code == 409
        assert restore_user.json()["detail"]["code"] == (
            "permanent_deletion_already_accepted"
        )

        second = await client.delete("/trash/bulk")
        assert second.status_code == 200
        second_by_type = {item["item_type"]: item for item in second.json()["results"]}
        assert second_by_type["user"]["outcome"] == "COMPLETED"
        assert second_by_type["user"]["operation"]["operation_id"] == (
            user_operation_id
        )
        assert second_by_type["notification"]["outcome"] == "COMPLETED"
        assert second_by_type["notification"]["operation"]["operation_id"] == (
            bulletin_operation_id
        )
        assert second_by_type["course_category"]["outcome"] == "FAILED"
        assert observed_client.remove_calls == [
            (bucket_name, archive.object_name, uploaded.version_id)
        ]

        restore_category = await client.post(
            "/trash/restore",
            json={
                "item_type": TrashEntityType.COURSE_CATEGORY,
                "item_id": category.id,
            },
        )
        assert restore_category.status_code == 200
        async with session_maker() as session:
            assert await session.get(User, owner.id) is None
            retained_event = await session.get(ArchiveSubmissionEvent, event.id)
            assert retained_event is not None
            assert retained_event.submission_id is None
            assert retained_event.submitted_at == event.submitted_at
            retained = await session.get(PersonalNotification, retained_notification.id)
            assert retained is not None
            assert retained.source_id == submission.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            if operation_ids:
                await session.execute(
                    delete(PermanentDeletionObject).where(
                        PermanentDeletionObject.operation_id.in_(operation_ids)
                    )
                )
                await session.execute(
                    delete(PermanentDeletionTarget).where(
                        PermanentDeletionTarget.operation_id.in_(operation_ids)
                    )
                )
                await session.execute(
                    delete(PermanentDeletionOperation).where(
                        PermanentDeletionOperation.id.in_(operation_ids)
                    )
                )
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.id == retained_notification.id
                )
            )
            await session.execute(
                delete(Notification).where(Notification.id == bulletin.id)
            )
            await session.commit()
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=None,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=owner_notification.id,
        )


@pytest.mark.asyncio
async def test_exact_storage_completion_is_atomic_with_stage5e_detach(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    _, _, archive, submission, event, notification = await _create_deleted_pair(
        session_maker, requester_id=requester.id
    )
    client = FakeVersionedMinio(archive.object_name, "v-exact")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 3, 0, tzinfo=UTC)

    async with session_maker() as session:
        operation = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
            root_entity_id=submission.id,
            idempotency_key=f"submission:{submission.id}:delete",
            requested_by_user_id=requester.id,
            storage=storage,
            now=now,
        )
        stored_object = (
            await session.execute(
                select(PermanentDeletionObject).where(
                    PermanentDeletionObject.operation_id == operation.id
                )
            )
        ).scalar_one()
        assert stored_object.version_id == "v-exact"

        result = await process_one_permanent_deletion(
            session,
            operation_id=operation.id,
            storage=storage,
            now=now + timedelta(minutes=1),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
        )
        assert result == PermanentDeletionStatus.COMPLETED
        assert client.removals == [("stage5fb-test", archive.object_name, "v-exact")]
        assert await session.get(Archive, archive.id) is None
        assert await session.get(ArchiveSubmission, submission.id) is None
        retained_event = await session.get(ArchiveSubmissionEvent, event.id)
        assert retained_event is not None
        assert retained_event.submission_id is None
        assert retained_event.submitted_at == event.submitted_at
        assert await session.get(PersonalNotification, notification.id) is not None
        assert (
            await session.execute(
                select(func.count(PermanentDeletionObject.id)).where(
                    PermanentDeletionObject.operation_id == operation.id
                )
            )
        ).scalar_one() == 0

        repeated = await process_one_permanent_deletion(
            session,
            operation_id=operation.id,
            storage=storage,
            now=now + timedelta(minutes=2),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=2, seconds=1)),
        )
        assert repeated == PermanentDeletionStatus.COMPLETED
        assert client.removals == [("stage5fb-test", archive.object_name, "v-exact")]


@pytest.mark.asyncio
async def test_unknown_delete_outcome_verifies_before_finalization(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    _, _, archive, submission, _, _ = await _create_deleted_pair(
        session_maker, requester_id=requester.id
    )
    client = FakeVersionedMinio(archive.object_name, "v-unknown")
    client.unknown_once = True
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)

    async with session_maker() as session:
        operation = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
            root_entity_id=submission.id,
            idempotency_key=f"submission:{submission.id}:unknown",
            requested_by_user_id=requester.id,
            storage=storage,
            now=now,
        )
        first = await process_one_permanent_deletion(
            session,
            operation_id=operation.id,
            storage=storage,
            now=now + timedelta(minutes=1),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
        )
        assert first == PermanentDeletionStatus.VERIFICATION_REQUIRED
        assert await session.get(ArchiveSubmission, submission.id) is not None

        second = await process_one_permanent_deletion(
            session,
            operation_id=operation.id,
            storage=storage,
            now=now + timedelta(minutes=2),
            jitter_fraction=0.0,
            lease_clock=MutableLeaseClock(now + timedelta(minutes=2, seconds=1)),
        )
        assert second == PermanentDeletionStatus.COMPLETED
        assert len(client.removals) == 1


@pytest.mark.asyncio
async def test_replacement_drift_enters_manual_review_without_delete(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-recorded")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 5, 0, tzinfo=UTC)

    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:drift",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            client.versions.append((archive.object_name, "v-replacement", False))
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now + timedelta(minutes=1),
                jitter_fraction=0.0,
                lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == []
            assert await session.get(ArchiveSubmission, submission.id) is not None
    finally:
        if operation_id is not None:
            await _cleanup_pair_and_operation(
                session_maker,
                operation_id=operation_id,
                category_id=category.id,
                course_id=course.id,
                archive_id=archive.id,
                submission_id=submission.id,
                event_id=event.id,
                notification_id=notification.id,
            )


@pytest.mark.asyncio
async def test_acceptance_failures_leave_no_durable_operation(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-one")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            client.status = "Suspended"
            with pytest.raises(StorageSafetyError, match="versioning_not_enabled"):
                await accept_permanent_deletion(
                    session,
                    root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                    root_entity_id=submission.id,
                    idempotency_key=f"submission:{submission.id}:suspended",
                    requested_by_user_id=requester.id,
                    storage=storage,
                )

            client.status = "Enabled"
            client.versions.append((archive.object_name, "v-two", False))
            with pytest.raises(StorageSafetyError, match="ambiguous_object_history"):
                await accept_permanent_deletion(
                    session,
                    root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                    root_entity_id=submission.id,
                    idempotency_key=f"submission:{submission.id}:ambiguous",
                    requested_by_user_id=requester.id,
                    storage=storage,
                )
            operation_count = (
                await session.execute(
                    select(func.count(PermanentDeletionOperation.id)).where(
                        PermanentDeletionOperation.idempotency_key.in_(
                            [
                                f"submission:{submission.id}:suspended",
                                f"submission:{submission.id}:ambiguous",
                            ]
                        )
                    )
                )
            ).scalar_one()
            assert operation_count == 0
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_conflicting_active_target_reservation_is_rejected(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    storage = ExactVersionMinioAdapter(
        FakeVersionedMinio(archive.object_name), bucket_name="stage5fb-test"
    )
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:first",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            with pytest.raises(
                PermanentDeletionError, match="target_reservation_conflict"
            ):
                await accept_permanent_deletion(
                    session,
                    root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                    root_entity_id=submission.id,
                    idempotency_key=f"submission:{submission.id}:conflict",
                    requested_by_user_id=requester.id,
                    storage=storage,
                )
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_replacement_between_validation_and_delete_blocks_finalization(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-recorded")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:race",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            client.replacement_during_delete = "v-replacement"
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == [
                ("stage5fb-test", archive.object_name, "v-recorded")
            ]
            assert client.versions == [(archive.object_name, "v-replacement", False)]
            assert await session.get(ArchiveSubmission, submission.id) is not None
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_post_delete_replacement_blocks_final_db_transaction(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-recorded")
    client.replacement_on_history_call = (5, "v-post-delete-replacement")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:post-delete-drift",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == [
                ("stage5fb-test", archive.object_name, "v-recorded")
            ]
            assert client.versions == [
                (archive.object_name, "v-post-delete-replacement", False)
            ]
            assert await session.get(ArchiveSubmission, submission.id) is not None
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_retryable_failure_tracks_budget_and_retries_same_exact_version(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-retry")
    client.retryable_once = True
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 7, 0, tzinfo=UTC)
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:retry",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            first = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now + timedelta(minutes=1),
                jitter_fraction=0.0,
                lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
            )
            assert first == PermanentDeletionStatus.RETRYABLE_FAILED
            await session.refresh(operation)
            assert operation.automatic_attempt_count == 1
            assert operation.next_attempt_at is not None
            assert operation.next_attempt_at <= operation.retry_deadline_at
            retry_at = operation.next_attempt_at

            second = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=retry_at,
                jitter_fraction=0.0,
                lease_clock=MutableLeaseClock(retry_at + timedelta(seconds=1)),
            )
            assert second == PermanentDeletionStatus.COMPLETED
            assert client.removals == [
                ("stage5fb-test", archive.object_name, "v-retry"),
                ("stage5fb-test", archive.object_name, "v-retry"),
            ]
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_budget_exhaustion_and_versioning_drift_fail_closed(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-budget")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:budget",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            operation.automatic_attempt_count = 10
            await session.commit()
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == []
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )

    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-suspended")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:post-suspend",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            client.status = "Suspended"
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == []
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_membership_drift_prevents_storage_delete(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-membership")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    operation_id: int | None = None
    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:membership",
                requested_by_user_id=requester.id,
                storage=storage,
            )
            operation_id = int(operation.id)
            live_submission = await session.get(ArchiveSubmission, submission.id)
            live_submission.status = SubmissionStatus.PENDING
            live_submission.previous_status = None
            live_submission.deleted_at = None
            await session.commit()
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
            )
            assert result == PermanentDeletionStatus.MANUAL_REVIEW
            assert client.removals == []
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_db_finalization_rollback_recovers_from_verified_storage_absence(
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-finalize")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
    operation_id: int | None = None
    original_finalize = permanent_deletion_service._finalize_plan

    async def fail_finalization(*_args, **_kwargs):
        raise RuntimeError("synthetic finalization failure")

    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:finalize",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            monkeypatch.setattr(
                permanent_deletion_service, "_finalize_plan", fail_finalization
            )
            first = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now + timedelta(minutes=1),
                jitter_fraction=0.0,
                lease_clock=MutableLeaseClock(now + timedelta(minutes=1, seconds=1)),
            )
            assert first == PermanentDeletionStatus.RETRYABLE_FAILED
            assert await session.get(ArchiveSubmission, submission.id) is not None
            await session.refresh(operation)
            retry_at = operation.next_attempt_at
            assert retry_at is not None

            monkeypatch.setattr(
                permanent_deletion_service, "_finalize_plan", original_finalize
            )
            second = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=retry_at,
                jitter_fraction=0.0,
                lease_clock=MutableLeaseClock(retry_at + timedelta(seconds=1)),
            )
            assert second == PermanentDeletionStatus.COMPLETED
            assert client.removals == [
                ("stage5fb-test", archive.object_name, "v-finalize")
            ]
    finally:
        monkeypatch.setattr(
            permanent_deletion_service, "_finalize_plan", original_finalize
        )
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_claim_is_single_owner_and_expired_lease_is_reclaimable(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    now = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Lease request",
            category="physics-department",
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=now,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        operation = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.COURSE_SUBMISSION,
            root_entity_id=request.id,
            idempotency_key=f"course-request:{request.id}:lease",
            requested_by_user_id=requester.id,
            storage=None,
            now=now,
        )

    async with session_maker() as first_session, session_maker() as second_session:
        first = await claim_permanent_deletion(
            first_session,
            operation_id=operation.id,
            lease_token="first-token",
            now=now + timedelta(seconds=1),
            lease_for=timedelta(seconds=30),
        )
        second = await claim_permanent_deletion(
            second_session,
            operation_id=operation.id,
            lease_token="second-token",
            now=now + timedelta(seconds=2),
            lease_for=timedelta(seconds=30),
        )
        assert first is True
        assert second is False
        reclaimed = await claim_permanent_deletion(
            second_session,
            operation_id=operation.id,
            lease_token="reclaimed-token",
            now=now + timedelta(minutes=1),
            lease_for=timedelta(seconds=30),
        )
        assert reclaimed is True

        with pytest.raises(PermanentDeletionError, match="lease_lost"):
            await _owned_operation(
                first_session,
                int(operation.id),
                "first-token",
            )

    async with session_maker() as cleanup_session:
        await cleanup_session.execute(
            delete(PermanentDeletionTarget).where(
                PermanentDeletionTarget.operation_id == operation.id
            )
        )
        await cleanup_session.execute(
            delete(PermanentDeletionOperation).where(
                PermanentDeletionOperation.id == operation.id
            )
        )
        await cleanup_session.execute(
            delete(CourseSubmission).where(CourseSubmission.id == request.id)
        )
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_expired_unreclaimed_lease_is_not_owned(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    now = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Expired unreclaimed lease",
            category="physics-department",
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=now,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        operation = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.COURSE_SUBMISSION,
            root_entity_id=request.id,
            idempotency_key=f"course-request:{request.id}:expired-unreclaimed",
            requested_by_user_id=requester.id,
            storage=None,
            now=now,
        )
        assert await claim_permanent_deletion(
            session,
            operation_id=operation.id,
            lease_token="expired-token",
            now=now,
            lease_for=timedelta(seconds=1),
        )

        try:
            with pytest.raises(PermanentDeletionError, match="lease_lost"):
                await _owned_operation(session, int(operation.id), "expired-token")
        finally:
            await session.execute(
                delete(PermanentDeletionTarget).where(
                    PermanentDeletionTarget.operation_id == operation.id
                )
            )
            await session.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id == operation.id
                )
            )
            await session.execute(
                delete(CourseSubmission).where(CourseSubmission.id == request.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_lease_expiry_before_delete_boundary_prevents_destructive_call(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-before-delete-expiry")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
    lease_clock = MutableLeaseClock(now + timedelta(seconds=1))
    operation_id: int | None = None

    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:pre-delete-expiry",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            client.on_history = lambda: setattr(
                lease_clock, "current", now + timedelta(seconds=31)
            )

            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now,
                lease_for=timedelta(seconds=30),
                lease_clock=lease_clock,
            )

            assert result == PermanentDeletionStatus.PROCESSING
            assert client.removals == []
            assert await session.get(ArchiveSubmission, submission.id) is not None
            await session.refresh(operation)
            assert operation.completed_at is None
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_delete_crossing_lease_expiry_cannot_persist_post_delete_state(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-mid-call-expiry")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)
    lease_clock = MutableLeaseClock(now + timedelta(seconds=1))
    operation_id: int | None = None

    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:mid-call-expiry",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            client.on_remove = lambda: setattr(
                lease_clock, "current", now + timedelta(seconds=31)
            )

            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now,
                lease_for=timedelta(seconds=30),
                lease_clock=lease_clock,
            )

            assert result == PermanentDeletionStatus.PROCESSING
            assert client.removals == [
                ("stage5fb-test", archive.object_name, "v-mid-call-expiry")
            ]
            stored_object = (
                await session.execute(
                    select(PermanentDeletionObject).where(
                        PermanentDeletionObject.operation_id == operation.id
                    )
                )
            ).scalar_one()
            assert stored_object.verified_absent_at is None
            assert await session.get(ArchiveSubmission, submission.id) is not None
            await session.refresh(operation)
            assert operation.completed_at is None
    finally:
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_lease_expiry_during_finalization_rolls_back_live_rows_and_completion(
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    requester = await make_user()
    (
        category,
        course,
        archive,
        submission,
        event,
        notification,
    ) = await _create_deleted_pair(session_maker, requester_id=requester.id)
    client = FakeVersionedMinio(archive.object_name, "v-finalization-expiry")
    storage = ExactVersionMinioAdapter(client, bucket_name="stage5fb-test")
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    lease_clock = MutableLeaseClock(now + timedelta(seconds=1))
    operation_id: int | None = None
    original_finalize = permanent_deletion_service._finalize_plan

    async def expire_after_live_row_effects(*args, **kwargs):
        await original_finalize(*args, **kwargs)
        lease_clock.current = now + timedelta(seconds=31)

    try:
        async with session_maker() as session:
            operation = await accept_permanent_deletion(
                session,
                root_entity_type=TrashEntityType.ARCHIVE_SUBMISSION,
                root_entity_id=submission.id,
                idempotency_key=f"submission:{submission.id}:finalization-expiry",
                requested_by_user_id=requester.id,
                storage=storage,
                now=now,
            )
            operation_id = int(operation.id)
            monkeypatch.setattr(
                permanent_deletion_service,
                "_finalize_plan",
                expire_after_live_row_effects,
            )

            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=storage,
                now=now,
                lease_for=timedelta(seconds=30),
                lease_clock=lease_clock,
            )

            assert result == PermanentDeletionStatus.PROCESSING
            assert await session.get(Archive, archive.id) is not None
            assert await session.get(ArchiveSubmission, submission.id) is not None
            await session.refresh(operation)
            assert operation.completed_at is None
            assert operation.status == PermanentDeletionStatus.PROCESSING
    finally:
        monkeypatch.setattr(
            permanent_deletion_service,
            "_finalize_plan",
            original_finalize,
        )
        await _cleanup_pair_and_operation(
            session_maker,
            operation_id=operation_id,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
        )


@pytest.mark.asyncio
async def test_reclaimed_owner_can_complete_after_expired_owner_loses_authority(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    now = datetime(2026, 8, 27, 13, 0, tzinfo=UTC)
    async with session_maker() as session:
        request = CourseSubmission(
            name="Reclaimed lease request",
            category="physics-department",
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.PENDING,
            deleted_at=now,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        operation = await accept_permanent_deletion(
            session,
            root_entity_type=TrashEntityType.COURSE_SUBMISSION,
            root_entity_id=request.id,
            idempotency_key=f"course-request:{request.id}:reclaimed-owner",
            requested_by_user_id=requester.id,
            storage=None,
            now=now,
        )
        assert await claim_permanent_deletion(
            session,
            operation_id=operation.id,
            lease_token="old-owner",
            now=now,
            lease_for=timedelta(seconds=30),
        )

        try:
            recovered_at = now + timedelta(minutes=1)
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation.id,
                storage=None,
                now=recovered_at,
                lease_for=timedelta(seconds=30),
                lease_clock=MutableLeaseClock(recovered_at + timedelta(seconds=1)),
            )

            assert result == PermanentDeletionStatus.COMPLETED
            assert await session.get(CourseSubmission, request.id) is None
            with pytest.raises(PermanentDeletionError, match="lease_lost"):
                await _owned_operation(session, int(operation.id), "old-owner")
        finally:
            await session.execute(
                delete(PermanentDeletionTarget).where(
                    PermanentDeletionTarget.operation_id == operation.id
                )
            )
            await session.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id == operation.id
                )
            )
            await session.execute(
                delete(CourseSubmission).where(CourseSubmission.id == request.id)
            )
            await session.commit()
