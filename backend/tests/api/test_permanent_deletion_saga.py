from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    PermanentDeletionObject,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    PersonalNotification,
    SubmissionStatus,
    TrashEntityType,
)
from app.services import permanent_deletion as permanent_deletion_service
from app.services.permanent_deletion import (
    PermanentDeletionError,
    _owned_operation,
    accept_permanent_deletion,
    claim_permanent_deletion,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_storage import (
    ExactVersionMinioAdapter,
    StorageSafetyError,
)


class FakeVersionedMinio:
    def __init__(self, key: str, version_id: str = "v1") -> None:
        self.status = "Enabled"
        self.versions: list[tuple[str, str, bool]] = [(key, version_id, False)]
        self.removals: list[tuple[str, str, str | None]] = []
        self.unknown_once = False
        self.retryable_once = False
        self.replacement_during_delete: str | None = None

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status=self.status)

    def list_objects(self, _bucket: str, **_kwargs):
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
            if row[0] == key and not row[2] and (version_id is None or row[1] == version_id)
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
            self.versions.append(
                (key, self.replacement_during_delete, False)
            )
            self.replacement_during_delete = None
        self.versions = [
            row for row in self.versions if not (row[0] == key and row[1] == version_id)
        ]
        if self.unknown_once:
            self.unknown_once = False
            raise TimeoutError("synthetic unknown delete outcome")


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
            delete(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.id == event_id
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.execute(
            delete(CourseCategoryConfig).where(
                CourseCategoryConfig.id == category_id
            )
        )
        await session.commit()


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
        )
        assert result == PermanentDeletionStatus.COMPLETED
        assert await session.get(CourseSubmission, request.id) is None

        again = await process_one_permanent_deletion(
            session,
            operation_id=first.id,
            storage=None,
            now=now + timedelta(minutes=2),
            jitter_fraction=0.0,
        )
        assert again == PermanentDeletionStatus.COMPLETED


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
        )
        assert result == PermanentDeletionStatus.COMPLETED
        assert client.removals == [
            ("stage5fb-test", archive.object_name, "v-exact")
        ]
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
        )
        assert first == PermanentDeletionStatus.VERIFICATION_REQUIRED
        assert await session.get(ArchiveSubmission, submission.id) is not None

        second = await process_one_permanent_deletion(
            session,
            operation_id=operation.id,
            storage=storage,
            now=now + timedelta(minutes=2),
            jitter_fraction=0.0,
        )
        assert second == PermanentDeletionStatus.COMPLETED
        assert len(client.removals) == 1


@pytest.mark.asyncio
async def test_replacement_drift_enters_manual_review_without_delete(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(
            session_maker, requester_id=requester.id
        )
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
            assert client.versions == [
                (archive.object_name, "v-replacement", False)
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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

    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
    category, course, archive, submission, event, notification = (
        await _create_deleted_pair(session_maker, requester_id=requester.id)
    )
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
