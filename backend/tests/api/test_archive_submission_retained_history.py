from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import archive_submission_lifecycle, trash
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    Course,
    CourseCategoryConfig,
    PermanentDeletionObject,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_lifecycle_locks, permanent_deletion
from app.services.archive_lifecycle_locks import LifecycleResourceClass
from app.services.permanent_deletion_storage import ExactVersionMinioAdapter
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


class _FakeVersionedMinio:
    def __init__(self, key: str) -> None:
        self.key = key
        self.version_id = "retained-v1"
        self.present = True

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status="Enabled")

    def list_objects(self, _bucket: str, **_kwargs):
        if not self.present:
            return []
        return [
            SimpleNamespace(
                object_name=self.key,
                version_id=self.version_id,
                is_delete_marker=False,
            )
        ]

    def stat_object(self, _bucket: str, key: str, version_id: str | None = None):
        if self.present and key == self.key and (
            version_id is None or version_id == self.version_id
        ):
            return SimpleNamespace(object_name=key, version_id=self.version_id)
        from minio.error import S3Error

        raise S3Error(None, "NoSuchVersion", "missing", key, "request-id", "host-id")

    def remove_object(
        self, _bucket: str, key: str, version_id: str | None = None
    ) -> None:
        assert key == self.key
        assert version_id == self.version_id
        self.present = False


async def _create_deleted_pair(session_maker, *, requester_id: int):
    marker = uuid.uuid4().hex
    deleted_at = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)
    submitted_at = datetime(2026, 8, 20, 3, 4, 5, 678901, tzinfo=UTC)
    async with session_maker() as session:
        category = CourseCategoryConfig(
            key=f"retained-{marker[:12]}",
            name=f"Retained category {marker}",
            label=f"Retained category {marker}",
        )
        course = Course(name=f"Retained course {marker}", category=category.key)
        session.add(category)
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"Retained archive {marker}",
            academic_year=115,
            archive_type=ArchiveType.FINAL,
            professor="Retained Professor",
            object_name=f"archive/retained-{marker}.pdf",
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
            object_name=archive.object_name,
            requester_id=requester_id,
            owner_id=requester_id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
            deleted_at=deleted_at,
            deleted_by_id=requester_id,
            created_at=submitted_at,
        )
        session.add(submission)
        await session.flush()
        event = ArchiveSubmissionEvent(
            submission_id=submission.id,
            submitted_at=submitted_at,
        )
        notification = PersonalNotification(
            user_id=requester_id,
            notification_type="archive_submission_approved",
            title="Submission approved",
            message="Your retained-history submission was approved.",
            source_type="archive_submission",
            source_id=submission.id,
            dedupe_key=f"retained-history-{marker}",
        )
        session.add(event)
        session.add(notification)
        await session.commit()
        for row in (category, course, archive, submission, event, notification):
            await session.refresh(row)
    return category, course, archive, submission, event, notification


async def _cleanup(
    session_maker,
    *,
    category_id: int,
    course_id: int,
    archive_id: int,
    submission_id: int,
    event_id: int,
    notification_id: int,
    operation_id: int | None = None,
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


def _disable_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SimpleNamespace(remove_object=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(trash, "get_minio_client", lambda: client)
    monkeypatch.setattr(
        archive_submission_lifecycle, "get_minio_client", lambda: client
    )


@pytest.mark.asyncio
async def test_permanent_delete_retains_minimal_event_and_durable_notification(
    client,
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
    traces: list[list[tuple[LifecycleResourceClass, int]]] = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append([(item.resource_class, item.row_id) for item in plan.resources])
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks, "acquire_lifecycle_locks", observed_acquire
    )
    storage = ExactVersionMinioAdapter(
        _FakeVersionedMinio(archive.object_name), bucket_name="retained-history-test"
    )
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    operation_id = None
    try:
        response = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert response.status_code == 200
        operation = response.json()
        operation_id = operation["operation_id"]
        assert operation["status"] == PermanentDeletionStatus.COMPLETED
        assert [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, submission.id),
        ] in traces

        async with session_maker() as session:
            assert await session.get(ArchiveSubmission, submission.id) is None
            retained = await session.get(ArchiveSubmissionEvent, event.id)
            assert retained is not None
            assert retained.submission_id is None
            assert retained.submitted_at == event.submitted_at
            durable = await session.get(PersonalNotification, notification.id)
            assert durable is not None
            assert durable.title == notification.title
            assert durable.message == notification.message
            assert durable.source_id == submission.id

        app.dependency_overrides[get_current_user] = _override_user(
            requester.id, is_admin=False
        )
        notifications = await client.get("/notifications/center")
        assert notifications.status_code == 200
        projected = next(
            item
            for item in notifications.json()["personal_notifications"]
            if item["id"] == notification.id
        )
        assert projected["source_available"] is False
        assert projected["title"] == notification.title
        assert projected["message"] == notification.message
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
            operation_id=operation_id,
        )


@pytest.mark.asyncio
async def test_permanent_delete_rollback_restores_submission_and_event_link(
    client,
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
    original_detach = permanent_deletion.detach_archive_submission_events

    async def fail_after_detach(db, submission_ids):
        await original_detach(db, submission_ids)
        raise RuntimeError("injected failure after event detach")

    monkeypatch.setattr(
        permanent_deletion, "detach_archive_submission_events", fail_after_detach
    )
    storage = ExactVersionMinioAdapter(
        _FakeVersionedMinio(archive.object_name), bucket_name="retained-history-test"
    )
    monkeypatch.setattr(trash, "_permanent_deletion_storage", lambda: storage)
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    operation_id = None
    try:
        response = await client.delete(f"/trash/archive_submission/{submission.id}")
        assert response.status_code == 202
        operation = response.json()
        operation_id = operation["operation_id"]
        assert operation["status"] == PermanentDeletionStatus.RETRYABLE_FAILED
        assert operation["result_code"] == "db_finalization_failed"
        async with session_maker() as session:
            stored_submission = await session.get(ArchiveSubmission, submission.id)
            retained = await session.get(ArchiveSubmissionEvent, event.id)
            assert stored_submission is not None
            assert stored_submission.status == SubmissionStatus.DELETED
            assert retained is not None
            assert retained.submission_id == submission.id
            assert retained.submitted_at == event.submitted_at
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
            event_id=event.id,
            notification_id=notification.id,
            operation_id=operation_id,
        )


@pytest.mark.asyncio
async def test_bulk_permanent_delete_retains_every_submission_event(
    client,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester = await make_user()
    admin = await make_user(is_admin=True)
    contexts = [
        await _create_deleted_pair(session_maker, requester_id=requester.id)
        for _ in range(2)
    ]
    _disable_storage(monkeypatch)
    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        response = await client.delete(
            "/trash/bulk", params={"item_type": "archive_submission"}
        )
        assert response.status_code == 200
        event_ids = [context[4].id for context in contexts]
        submission_ids = [context[3].id for context in contexts]
        async with session_maker() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count(ArchiveSubmission.id)).where(
                            ArchiveSubmission.id.in_(submission_ids)
                        )
                    )
                    or 0
                )
                == 0
            )
            retained = list(
                (
                    await session.execute(
                        select(ArchiveSubmissionEvent)
                        .where(ArchiveSubmissionEvent.id.in_(event_ids))
                        .order_by(ArchiveSubmissionEvent.id)
                    )
                )
                .scalars()
                .all()
            )
            assert [item.id for item in retained] == sorted(event_ids)
            assert all(item.submission_id is None for item in retained)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        for category, course, archive, submission, event, notification in contexts:
            await _cleanup(
                session_maker,
                category_id=category.id,
                course_id=course.id,
                archive_id=archive.id,
                submission_id=submission.id,
                event_id=event.id,
                notification_id=notification.id,
            )
