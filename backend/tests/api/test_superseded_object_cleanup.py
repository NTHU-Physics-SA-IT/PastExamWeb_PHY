from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services.trash import list_trash_items
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    CourseCategory,
    PermanentDeletionObject,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    SubmissionStatus,
)
from app.services import permanent_deletion as permanent_deletion_service
from app.services.permanent_deletion import (
    enqueue_superseded_archive_submission_object_cleanup,
    process_one_permanent_deletion,
)
from app.services.permanent_deletion_reconciler import reconcile_due_once
from app.services.permanent_deletion_storage import ExactVersionMinioAdapter

NOW = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)


class _FakeVersionedMinio:
    def __init__(self, key: str, version_id: str) -> None:
        self.key = key
        self.versions = [(key, version_id, False)]
        self.removals: list[tuple[str, str, str | None]] = []
        self.retryable_once = False
        self.unknown_once = False

    def get_bucket_versioning(self, _bucket: str):
        return SimpleNamespace(status="Enabled")

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
            if row[0] == key
            and not row[2]
            and (version_id is None or row[1] == version_id)
        ]
        if not rows:
            from minio.error import S3Error

            raise S3Error(None, "NoSuchVersion", "missing", key, "request", "host")
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
                "retry",
                key,
                "request",
                "host",
            )
        self.versions = [
            row for row in self.versions if not (row[0] == key and row[1] == version_id)
        ]
        if self.unknown_once:
            self.unknown_once = False
            raise TimeoutError("unknown exact-delete outcome")


async def _create_live_submission(session_maker, *, requester_id: int):
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=f"Cleanup subject {marker}",
            category=CourseCategory.FRESHMAN.value,
            name=f"Cleanup exam {marker}",
            academic_year=115,
            archive_type=ArchiveType.FINAL,
            professor="Cleanup Professor",
            object_name=f"archive/current-{marker}.pdf",
            requester_id=requester_id,
            owner_id=requester_id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return submission


async def _cleanup_rows(session_maker, *, operation_ids: list[int], submission_id: int):
    async with session_maker() as session:
        if operation_ids:
            await session.execute(
                delete(PermanentDeletionOperation).where(
                    PermanentDeletionOperation.id.in_(operation_ids)
                )
            )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_storage_only_enqueue_is_caller_transaction_owned(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    operation_id = None
    try:
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            old_key = stored.object_name
            stored.object_name = f"archive/replacement-{marker}.pdf"
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-old",
                idempotency_key=f"superseded:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_id = int(operation.id)
            await session.rollback()

        async with session_maker() as session:
            assert await session.get(PermanentDeletionOperation, operation_id) is None
            stored = await session.get(ArchiveSubmission, submission.id)
            assert stored.object_name == old_key
    finally:
        await _cleanup_rows(
            session_maker, operation_ids=[], submission_id=int(submission.id)
        )


@pytest.mark.asyncio
async def test_storage_only_cleanup_completes_without_mutating_live_submission(
    session_maker,
    make_user,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/old-{marker}.pdf"
    operation_ids: list[int] = []
    client = _FakeVersionedMinio(old_key, "v-old")
    storage = ExactVersionMinioAdapter(client, bucket_name="archive")
    try:
        async with session_maker() as session:
            first = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-old",
                idempotency_key=f"superseded:first:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            second = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=f"archive/older-{marker}.pdf",
                version_id="v-older",
                idempotency_key=f"superseded:second:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(first.id), int(second.id)]
            await session.commit()

        async with session_maker() as session:
            targets = list(
                (
                    await session.execute(
                        select(PermanentDeletionTarget).where(
                            PermanentDeletionTarget.operation_id.in_(operation_ids)
                        )
                    )
                ).scalars()
            )
            assert len(targets) == 2
            assert len({target.entity_id for target in targets}) == 2
            assert await list_trash_items(
                item_type=None,
                current_user=SimpleNamespace(is_admin=True),
                db=session,
            ) == []

        async with session_maker() as session:
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation_ids[0],
                storage=storage,
                now=NOW,
                lease_clock=lambda: NOW,
            )
        assert result == PermanentDeletionStatus.COMPLETED
        assert client.removals == [("archive", old_key, "v-old")]

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            operation = await session.get(PermanentDeletionOperation, operation_ids[0])
            assert stored is not None
            assert stored.status == SubmissionStatus.PENDING
            assert stored.object_name == submission.object_name
            assert operation.status == PermanentDeletionStatus.COMPLETED
    finally:
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_kind", ["submission", "archive"])
async def test_storage_only_cleanup_fails_closed_when_object_is_referenced(
    session_maker,
    make_user,
    reference_kind,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/referenced-{marker}.pdf"
    operation_ids: list[int] = []
    course_id = None
    archive_id = None
    try:
        async with session_maker() as session:
            if reference_kind == "submission":
                stored = await session.get(ArchiveSubmission, submission.id)
                stored.object_name = old_key
            else:
                course = Course(
                    name=f"Cleanup course {marker}",
                    category=CourseCategory.FRESHMAN.value,
                )
                session.add(course)
                await session.flush()
                course_id = int(course.id)
                archive = Archive(
                    name=f"Cleanup archive {marker}",
                    academic_year=115,
                    archive_type=ArchiveType.FINAL,
                    professor="Cleanup Professor",
                    object_name=old_key,
                    uploader_id=int(requester.id),
                    course_id=course_id,
                )
                session.add(archive)
                await session.flush()
                archive_id = int(archive.id)
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-ref",
                idempotency_key=f"superseded:ref:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(operation.id)]
            await session.commit()

        client = _FakeVersionedMinio(old_key, "v-ref")
        storage = ExactVersionMinioAdapter(client, bucket_name="archive")
        async with session_maker() as session:
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation_ids[0],
                storage=storage,
                now=NOW,
                lease_clock=lambda: NOW,
            )
        assert result == PermanentDeletionStatus.MANUAL_REVIEW
        assert client.removals == []
    finally:
        async with session_maker() as session:
            if archive_id is not None:
                await session.execute(delete(Archive).where(Archive.id == archive_id))
            if course_id is not None:
                await session.execute(delete(Course).where(Course.id == course_id))
            await session.commit()
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        ("retryable_once", PermanentDeletionStatus.RETRYABLE_FAILED),
        ("unknown_once", PermanentDeletionStatus.VERIFICATION_REQUIRED),
    ],
)
async def test_storage_only_cleanup_retains_durable_state_after_storage_failure(
    session_maker,
    make_user,
    failure,
    expected_status,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/failure-{marker}.pdf"
    operation_ids: list[int] = []
    try:
        async with session_maker() as session:
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-failure",
                idempotency_key=f"superseded:failure:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(operation.id)]
            await session.commit()

        client = _FakeVersionedMinio(old_key, "v-failure")
        setattr(client, failure, True)
        storage = ExactVersionMinioAdapter(client, bucket_name="archive")
        async with session_maker() as session:
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation_ids[0],
                storage=storage,
                now=NOW,
                lease_clock=lambda: NOW,
            )
        assert result == expected_status
        async with session_maker() as session:
            operation = await session.get(PermanentDeletionOperation, operation_ids[0])
            object_count = await session.scalar(
                select(func.count(PermanentDeletionObject.id)).where(
                    PermanentDeletionObject.operation_id == operation_ids[0]
                )
            )
            assert operation.status == expected_status
            assert object_count == 1
    finally:
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["version", "bucket"])
async def test_storage_only_cleanup_rejects_storage_identity_drift(
    session_maker,
    make_user,
    drift,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/drift-{marker}.pdf"
    operation_ids: list[int] = []
    try:
        async with session_maker() as session:
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-recorded",
                idempotency_key=f"superseded:drift:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(operation.id)]
            await session.commit()

        client = _FakeVersionedMinio(old_key, "v-recorded")
        if drift == "version":
            client.versions.append((old_key, "v-unexpected", False))
        storage = ExactVersionMinioAdapter(
            client,
            bucket_name="unexpected" if drift == "bucket" else "archive",
        )
        async with session_maker() as session:
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation_ids[0],
                storage=storage,
                now=NOW,
                lease_clock=lambda: NOW,
            )
        assert result == PermanentDeletionStatus.MANUAL_REVIEW
        assert client.removals == []
    finally:
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )


@pytest.mark.asyncio
async def test_storage_only_cleanup_does_not_delete_when_reference_truth_fails(
    session_maker,
    make_user,
    monkeypatch,
) -> None:
    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/authority-failure-{marker}.pdf"
    operation_ids: list[int] = []
    try:
        async with session_maker() as session:
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-authority",
                idempotency_key=f"superseded:authority:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(operation.id)]
            await session.commit()

        original_all = permanent_deletion_service._all

        async def fail_archive_reference_query(db, statement):
            if "FROM archives" in str(statement):
                raise RuntimeError("reference authority unavailable")
            return await original_all(db, statement)

        monkeypatch.setattr(
            permanent_deletion_service,
            "_all",
            fail_archive_reference_query,
        )
        client = _FakeVersionedMinio(old_key, "v-authority")
        storage = ExactVersionMinioAdapter(client, bucket_name="archive")
        async with session_maker() as session:
            result = await process_one_permanent_deletion(
                session,
                operation_id=operation_ids[0],
                storage=storage,
                now=NOW,
                lease_clock=lambda: NOW,
            )
        assert result == PermanentDeletionStatus.MANUAL_REVIEW
        assert client.removals == []
    finally:
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )


@pytest.mark.asyncio
async def test_reconciler_dispatches_storage_only_cleanup(
    session_maker,
    make_user,
) -> None:
    def clock():
        return NOW

    async def processor(db, **kwargs):
        return await process_one_permanent_deletion(
            db,
            lease_clock=clock,
            **kwargs,
        )

    requester = await make_user()
    submission = await _create_live_submission(
        session_maker, requester_id=int(requester.id)
    )
    marker = uuid.uuid4().hex
    old_key = f"archive/reconcile-{marker}.pdf"
    operation_ids: list[int] = []
    try:
        async with session_maker() as session:
            operation = await enqueue_superseded_archive_submission_object_cleanup(
                session,
                submission_id=int(submission.id),
                bucket_name="archive",
                object_key=old_key,
                version_id="v-reconcile",
                idempotency_key=f"superseded:reconcile:{marker}",
                requested_by_user_id=int(requester.id),
                now=NOW,
            )
            operation_ids = [int(operation.id)]
            await session.commit()

        storage = ExactVersionMinioAdapter(
            _FakeVersionedMinio(old_key, "v-reconcile"), bucket_name="archive"
        )
        summary = await reconcile_due_once(
            session_maker=session_maker,
            storage_factory=lambda: storage,
            now=clock(),
            event_clock=clock,
            processor=processor,
        )
        assert summary.completed == 1
        async with session_maker() as session:
            operation = await session.get(PermanentDeletionOperation, operation_ids[0])
            assert operation.status == PermanentDeletionStatus.COMPLETED
    finally:
        await _cleanup_rows(
            session_maker,
            operation_ids=operation_ids,
            submission_id=int(submission.id),
        )
