"""Internal PostgreSQL-authoritative permanent-deletion saga.

Nothing in this module is wired to a public route.  Acceptance, processing,
and finalization are explicit internal primitives for later orchestration.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_ARCHIVE_TRASHED,
    LIFECYCLE_COURSE_TRASHED,
    LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED,
    acquire_stable_archive_submission_group_locks,
    detach_archive_submission_events,
    is_archive_submission_trashed,
)
from app.models.models import (
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveWishReport,
    CommentReport,
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    Notification,
    PermanentDeletionObject,
    PermanentDeletionObjectState,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    SubmissionStatus,
    SystemIssueReport,
    TrashEntityType,
    User,
)
from app.services.permanent_deletion_storage import (
    DeleteOutcomeUnknown,
    ExactVersionMinioAdapter,
    ExactVersionState,
    RetryableStorageError,
    RetryBudgetExhausted,
    StorageSafetyError,
    next_retry_at,
)


class PermanentDeletionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PlannedTarget:
    entity_type: str
    entity_id: int
    role: str
    snapshot: dict[str, Any]

    @property
    def identity(self) -> tuple[str, int]:
        return self.entity_type, self.entity_id


@dataclass(frozen=True)
class PlannedObject:
    target_identity: tuple[str, int]
    object_key: str


@dataclass
class DeletionPlan:
    root_entity_type: str
    root_entity_id: int
    targets: dict[tuple[str, int], PlannedTarget] = field(default_factory=dict)
    objects: dict[str, PlannedObject] = field(default_factory=dict)

    def add_target(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        role: str,
        snapshot: dict[str, Any],
    ) -> None:
        if entity_id is None:
            raise PermanentDeletionError("target_missing_identity")
        target = PlannedTarget(entity_type, entity_id, role, snapshot)
        existing = self.targets.get(target.identity)
        if existing is not None and existing != target:
            raise PermanentDeletionError("conflicting_target_plan")
        self.targets[target.identity] = target

    def add_object(
        self,
        *,
        target_identity: tuple[str, int],
        object_key: str | None,
    ) -> None:
        if not object_key:
            return
        existing = self.objects.get(object_key)
        if existing is None or target_identity < existing.target_identity:
            self.objects[object_key] = PlannedObject(target_identity, object_key)

    @property
    def fingerprint(self) -> str:
        payload = {
            "root": [self.root_entity_type, self.root_entity_id],
            "targets": [
                {
                    "entity_type": target.entity_type,
                    "entity_id": target.entity_id,
                    "role": target.role,
                    "snapshot": target.snapshot,
                }
                for target in sorted(
                    self.targets.values(),
                    key=lambda item: (item.entity_type, item.entity_id),
                )
            ],
            "objects": [
                {
                    "object_key": item.object_key,
                    "target": list(item.target_identity),
                }
                for item in sorted(
                    self.objects.values(), key=lambda value: value.object_key
                )
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _locked_row(
    db: SQLModelAsyncSession,
    model,
    row_id: int,
):
    statement = select(model).where(model.id == row_id).with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def _all(db: SQLModelAsyncSession, statement) -> list[Any]:
    return list((await db.execute(statement)).scalars().all())


def _submission_snapshot(item: ArchiveSubmission, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "created_archive_id": item.created_archive_id,
        "object_name": item.object_name,
        "status": item.status.value,
        "deleted_at": _timestamp(item.deleted_at),
        "lifecycle_reason": item.lifecycle_reason,
        "requester_id": item.requester_id,
        "owner_id": item.owner_id,
    }


def _archive_snapshot(item: Archive) -> dict[str, Any]:
    return {
        "course_id": item.course_id,
        "object_name": item.object_name,
        "deleted_at": _timestamp(item.deleted_at),
        "uploader_id": item.uploader_id,
    }


def _is_temporary_takedown(item: ArchiveSubmission) -> bool:
    reason = item.lifecycle_reason or ""
    return item.status == SubmissionStatus.TAKEDOWN and (
        reason == LIFECYCLE_ARCHIVE_TRASHED
        or reason == LIFECYCLE_COURSE_TRASHED
        or reason.startswith(f"{LIFECYCLE_COURSE_TRASHED}|")
    )


async def _add_archive_group(
    db: SQLModelAsyncSession,
    plan: DeletionPlan,
    *,
    archive: Archive | None = None,
    submission: ArchiveSubmission | None = None,
) -> None:
    group = await acquire_stable_archive_submission_group_locks(
        db,
        archive=archive,
        submission=submission,
    )
    if submission is not None and submission.created_archive_id is None:
        candidates = [
            item
            for item in group.archives
            if item.object_name == submission.object_name
            and item.name == submission.name
            and item.academic_year == submission.academic_year
            and item.archive_type == submission.archive_type
            and (not submission.professor or item.professor == submission.professor)
        ]
        if len(candidates) > 1:
            raise PermanentDeletionError("ambiguous_legacy_archive_membership")

    for item in group.archives:
        plan.add_target(
            entity_type=TrashEntityType.ARCHIVE.value,
            entity_id=item.id,
            role="delete",
            snapshot=_archive_snapshot(item),
        )
        plan.add_object(
            target_identity=(TrashEntityType.ARCHIVE.value, int(item.id)),
            object_key=item.object_name,
        )
        messages = await _all(
            db,
            select(ArchiveDiscussionMessage).where(
                ArchiveDiscussionMessage.archive_id == item.id
            ),
        )
        for message in messages:
            plan.add_target(
                entity_type="archive_discussion_message",
                entity_id=message.id,
                role="delete",
                snapshot={"archive_id": message.archive_id},
            )

    deleting_submission_ids: set[int] = set()
    for item in group.submissions:
        if is_archive_submission_trashed(item):
            role = "delete"
            deleting_submission_ids.add(int(item.id))
        elif _is_temporary_takedown(item):
            role = "mark_unrecoverable"
        else:
            raise PermanentDeletionError("active_submission_blocks_deletion")
        plan.add_target(
            entity_type=TrashEntityType.ARCHIVE_SUBMISSION.value,
            entity_id=item.id,
            role=role,
            snapshot=_submission_snapshot(item, role),
        )
        plan.add_object(
            target_identity=(TrashEntityType.ARCHIVE_SUBMISSION.value, int(item.id)),
            object_key=item.object_name,
        )

    if deleting_submission_ids:
        events = await _all(
            db,
            select(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.submission_id.in_(deleting_submission_ids)
            ),
        )
        for event in events:
            plan.add_target(
                entity_type="archive_submission_event",
                entity_id=event.id,
                role="detach",
                snapshot={
                    "submission_id": event.submission_id,
                    "submitted_at": _timestamp(event.submitted_at),
                },
            )


async def _validate_storage_references(
    db: SQLModelAsyncSession,
    plan: DeletionPlan,
) -> None:
    archive_ids = {
        entity_id
        for entity_type, entity_id in plan.targets
        if entity_type == TrashEntityType.ARCHIVE.value
    }
    submission_ids = {
        entity_id
        for entity_type, entity_id in plan.targets
        if entity_type == TrashEntityType.ARCHIVE_SUBMISSION.value
    }
    for object_key in plan.objects:
        archives = await _all(
            db, select(Archive.id).where(Archive.object_name == object_key)
        )
        submissions = await _all(
            db,
            select(ArchiveSubmission.id).where(
                ArchiveSubmission.object_name == object_key
            ),
        )
        if any(int(row) not in archive_ids for row in archives) or any(
            int(row) not in submission_ids for row in submissions
        ):
            raise PermanentDeletionError("object_has_external_reference")


async def _build_plan(
    db: SQLModelAsyncSession,
    *,
    root_entity_type: str,
    root_entity_id: int,
) -> DeletionPlan:
    try:
        root_type = TrashEntityType(root_entity_type)
    except ValueError as exc:
        raise PermanentDeletionError("unsupported_root_entity_type") from exc
    plan = DeletionPlan(root_type.value, root_entity_id)

    direct_models = {
        TrashEntityType.SYSTEM_ISSUE_REPORT: SystemIssueReport,
        TrashEntityType.COMMENT_REPORT: CommentReport,
        TrashEntityType.ARCHIVE_WISH_REPORT: ArchiveWishReport,
        TrashEntityType.ARCHIVE_REPORT: ArchiveReport,
        TrashEntityType.NOTIFICATION: Notification,
    }
    if root_type in direct_models:
        row = await _locked_row(db, direct_models[root_type], root_entity_id)
        if row is None or row.deleted_at is None:
            raise PermanentDeletionError("root_not_permanently_deletable")
        plan.add_target(
            entity_type=root_type.value,
            entity_id=row.id,
            role="delete",
            snapshot={"deleted_at": _timestamp(row.deleted_at)},
        )

    elif root_type == TrashEntityType.COURSE_SUBMISSION:
        row = await _locked_row(db, CourseSubmission, root_entity_id)
        if row is None or (
            row.deleted_at is None and row.status != SubmissionStatus.DELETED
        ):
            raise PermanentDeletionError("root_not_permanently_deletable")
        plan.add_target(
            entity_type=root_type.value,
            entity_id=row.id,
            role="delete",
            snapshot={
                "status": row.status.value,
                "deleted_at": _timestamp(row.deleted_at),
                "created_course_id": row.created_course_id,
            },
        )

    elif root_type == TrashEntityType.COURSE_CATEGORY:
        row = await _locked_row(db, CourseCategoryConfig, root_entity_id)
        if row is None or row.deleted_at is None:
            raise PermanentDeletionError("root_not_permanently_deletable")
        course_count = int(
            (
                await db.execute(
                    select(func.count(Course.id)).where(Course.category == row.key)
                )
            ).scalar_one()
        )
        active_request_count = int(
            (
                await db.execute(
                    select(func.count(CourseSubmission.id)).where(
                        CourseSubmission.category == row.key,
                        CourseSubmission.status == SubmissionStatus.PENDING,
                        CourseSubmission.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        active_submission_count = int(
            (
                await db.execute(
                    select(func.count(ArchiveSubmission.id)).where(
                        or_(
                            ArchiveSubmission.category == row.key,
                            ArchiveSubmission.requested_category_key == row.key,
                        ),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                        ArchiveSubmission.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        if course_count or active_request_count or active_submission_count:
            raise PermanentDeletionError("category_has_blocking_dependencies")
        plan.add_target(
            entity_type=root_type.value,
            entity_id=row.id,
            role="delete",
            snapshot={"key": row.key, "deleted_at": _timestamp(row.deleted_at)},
        )

    elif root_type == TrashEntityType.COURSE:
        row = await _locked_row(db, Course, root_entity_id)
        if row is None or row.deleted_at is None:
            raise PermanentDeletionError("root_not_permanently_deletable")
        active_count = int(
            (
                await db.execute(
                    select(func.count(Archive.id)).where(
                        Archive.course_id == row.id,
                        Archive.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        if active_count:
            raise PermanentDeletionError("course_has_active_archives")
        plan.add_target(
            entity_type=root_type.value,
            entity_id=row.id,
            role="delete",
            snapshot={
                "category": row.category,
                "deleted_at": _timestamp(row.deleted_at),
            },
        )
        archives = await _all(
            db,
            select(Archive).where(
                Archive.course_id == row.id,
                Archive.deleted_at.is_not(None),
            ),
        )
        for archive in archives:
            await _add_archive_group(db, plan, archive=archive)

    elif root_type == TrashEntityType.ARCHIVE:
        row = await _locked_row(db, Archive, root_entity_id)
        if row is None or row.deleted_at is None:
            raise PermanentDeletionError("root_not_permanently_deletable")
        await _add_archive_group(db, plan, archive=row)

    elif root_type == TrashEntityType.ARCHIVE_SUBMISSION:
        row = await _locked_row(db, ArchiveSubmission, root_entity_id)
        if row is None or not is_archive_submission_trashed(row):
            raise PermanentDeletionError("root_not_permanently_deletable")
        await _add_archive_group(db, plan, submission=row)

    elif root_type == TrashEntityType.USER:
        row = await _locked_row(db, User, root_entity_id)
        if row is None or row.deleted_at is None:
            raise PermanentDeletionError("root_not_permanently_deletable")
        active_archives = int(
            (
                await db.execute(
                    select(func.count(Archive.id)).where(
                        Archive.uploader_id == row.id,
                        Archive.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        active_submissions = int(
            (
                await db.execute(
                    select(func.count(ArchiveSubmission.id)).where(
                        or_(
                            ArchiveSubmission.owner_id == row.id,
                            ArchiveSubmission.requester_id == row.id,
                        ),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                        ArchiveSubmission.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        if active_archives or active_submissions:
            raise PermanentDeletionError("user_has_active_storage_children")
        plan.add_target(
            entity_type=root_type.value,
            entity_id=row.id,
            role="delete",
            snapshot={"deleted_at": _timestamp(row.deleted_at)},
        )
        submissions = await _all(
            db,
            select(ArchiveSubmission).where(
                or_(
                    ArchiveSubmission.owner_id == row.id,
                    ArchiveSubmission.requester_id == row.id,
                ),
                or_(
                    ArchiveSubmission.deleted_at.is_not(None),
                    ArchiveSubmission.status == SubmissionStatus.DELETED,
                ),
            ),
        )
        archives = await _all(
            db,
            select(Archive).where(
                Archive.uploader_id == row.id,
                Archive.deleted_at.is_not(None),
            ),
        )
        for submission in submissions:
            if (TrashEntityType.ARCHIVE_SUBMISSION.value, int(submission.id)) not in plan.targets:
                await _add_archive_group(db, plan, submission=submission)
        for archive in archives:
            if (TrashEntityType.ARCHIVE.value, int(archive.id)) not in plan.targets:
                await _add_archive_group(db, plan, archive=archive)

    else:  # pragma: no cover - the enum cases above are exhaustive
        raise PermanentDeletionError("unsupported_root_entity_type")

    if not plan.targets:
        raise PermanentDeletionError("empty_deletion_plan")
    await _validate_storage_references(db, plan)
    return plan


async def _existing_operation(
    db: SQLModelAsyncSession,
    idempotency_key: str,
) -> PermanentDeletionOperation | None:
    return (
        await db.execute(
            select(PermanentDeletionOperation).where(
                PermanentDeletionOperation.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()


async def accept_permanent_deletion(
    db: SQLModelAsyncSession,
    *,
    root_entity_type: TrashEntityType | str,
    root_entity_id: int,
    idempotency_key: str,
    requested_by_user_id: int | None,
    storage: ExactVersionMinioAdapter | None,
    now: datetime | None = None,
) -> PermanentDeletionOperation:
    timestamp = now or datetime.now(UTC)
    root_type = (
        root_entity_type.value
        if isinstance(root_entity_type, TrashEntityType)
        else str(root_entity_type)
    )
    if root_entity_id <= 0 or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise PermanentDeletionError("invalid_acceptance_identity")

    existing = await _existing_operation(db, idempotency_key)
    if existing is not None:
        if (
            existing.root_entity_type != root_type
            or existing.root_entity_id != root_entity_id
        ):
            raise PermanentDeletionError("idempotency_identity_conflict")
        return existing

    try:
        plan = await _build_plan(
            db,
            root_entity_type=root_type,
            root_entity_id=root_entity_id,
        )
        captured_versions: dict[str, str] = {}
        if plan.objects:
            if storage is None:
                raise PermanentDeletionError("storage_adapter_required")
            for object_key in sorted(plan.objects):
                captured_versions[object_key] = storage.capture_version_id(object_key)

        operation = PermanentDeletionOperation(
            root_entity_type=root_type,
            root_entity_id=root_entity_id,
            requested_by_user_id=requested_by_user_id,
            idempotency_key=idempotency_key,
            status=PermanentDeletionStatus.ACCEPTED,
            accepted_at=timestamp,
            automatic_attempt_count=0,
            retry_deadline_at=timestamp + timedelta(hours=24),
            next_attempt_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(operation)
        await db.flush()
        target_rows: dict[tuple[str, int], PermanentDeletionTarget] = {}
        for target in sorted(
            plan.targets.values(), key=lambda item: (item.entity_type, item.entity_id)
        ):
            row = PermanentDeletionTarget(
                operation_id=int(operation.id),
                entity_type=target.entity_type,
                entity_id=target.entity_id,
                target_role=target.role,
                membership_fingerprint=plan.fingerprint,
                membership_captured_at=timestamp,
                created_at=timestamp,
            )
            db.add(row)
            target_rows[target.identity] = row
        await db.flush()
        for object_key, planned_object in sorted(plan.objects.items()):
            target = target_rows[planned_object.target_identity]
            db.add(
                PermanentDeletionObject(
                    operation_id=int(operation.id),
                    target_id=int(target.id),
                    bucket_name=storage.bucket_name if storage else "",
                    object_key=object_key,
                    version_id=captured_versions[object_key],
                    state=PermanentDeletionObjectState.CAPTURED,
                    captured_at=timestamp,
                    created_at=timestamp,
                )
            )
        await db.commit()
        await db.refresh(operation)
        return operation
    except IntegrityError as exc:
        await db.rollback()
        existing = await _existing_operation(db, idempotency_key)
        if existing is not None and (
            existing.root_entity_type == root_type
            and existing.root_entity_id == root_entity_id
        ):
            return existing
        raise PermanentDeletionError("target_reservation_conflict") from exc
    except Exception:
        await db.rollback()
        raise


async def claim_permanent_deletion(
    db: SQLModelAsyncSession,
    *,
    operation_id: int,
    lease_token: str,
    now: datetime,
    lease_for: timedelta = timedelta(minutes=5),
) -> bool:
    if not lease_token.strip() or len(lease_token) > 64 or lease_for <= timedelta(0):
        raise PermanentDeletionError("invalid_lease")
    eligible = (
        PermanentDeletionStatus.ACCEPTED,
        PermanentDeletionStatus.PROCESSING,
        PermanentDeletionStatus.VERIFICATION_REQUIRED,
        PermanentDeletionStatus.RETRYABLE_FAILED,
    )
    statement = (
        update(PermanentDeletionOperation)
        .where(
            PermanentDeletionOperation.id == operation_id,
            PermanentDeletionOperation.status.in_(eligible),
            or_(
                PermanentDeletionOperation.lease_token.is_(None),
                PermanentDeletionOperation.lease_expires_at <= now,
            ),
            or_(
                PermanentDeletionOperation.next_attempt_at.is_(None),
                PermanentDeletionOperation.next_attempt_at <= now,
                PermanentDeletionOperation.status
                == PermanentDeletionStatus.VERIFICATION_REQUIRED,
            ),
        )
        .values(
            status=PermanentDeletionStatus.PROCESSING,
            lease_token=lease_token,
            lease_expires_at=now + lease_for,
            next_attempt_at=None,
            updated_at=now,
        )
    )
    result = await db.execute(statement)
    await db.commit()
    return bool(result.rowcount)


async def _operation_status(
    db: SQLModelAsyncSession, operation_id: int
) -> PermanentDeletionStatus:
    operation = await db.get(PermanentDeletionOperation, operation_id)
    if operation is None:
        raise PermanentDeletionError("operation_not_found")
    return operation.status


async def _stored_targets(
    db: SQLModelAsyncSession, operation_id: int
) -> list[PermanentDeletionTarget]:
    return await _all(
        db,
        select(PermanentDeletionTarget).where(
            PermanentDeletionTarget.operation_id == operation_id
        ),
    )


async def _validate_membership(
    db: SQLModelAsyncSession,
    operation: PermanentDeletionOperation,
) -> DeletionPlan:
    plan = await _build_plan(
        db,
        root_entity_type=operation.root_entity_type,
        root_entity_id=operation.root_entity_id,
    )
    stored = await _stored_targets(db, int(operation.id))
    stored_identities = {(item.entity_type, item.entity_id) for item in stored}
    if stored_identities != set(plan.targets) or not stored:
        raise PermanentDeletionError("membership_drift")
    if any(
        item.membership_fingerprint != plan.fingerprint
        or item.target_role != plan.targets[(item.entity_type, item.entity_id)].role
        for item in stored
    ):
        raise PermanentDeletionError("membership_drift")
    return plan


async def _owned_operation(
    db: SQLModelAsyncSession,
    operation_id: int,
    lease_token: str,
) -> PermanentDeletionOperation:
    operation = (
        await db.execute(
            select(PermanentDeletionOperation)
            .where(
                PermanentDeletionOperation.id == operation_id,
                PermanentDeletionOperation.lease_token == lease_token,
                PermanentDeletionOperation.status == PermanentDeletionStatus.PROCESSING,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise PermanentDeletionError("lease_lost")
    return operation


async def _manual_review(
    db: SQLModelAsyncSession,
    *,
    operation_id: int,
    lease_token: str,
    code: str,
    now: datetime,
    object_id: int | None = None,
) -> PermanentDeletionStatus:
    operation = await _owned_operation(db, operation_id, lease_token)
    operation.status = PermanentDeletionStatus.MANUAL_REVIEW
    operation.result_code = code[:64]
    operation.next_attempt_at = None
    operation.lease_token = None
    operation.lease_expires_at = None
    operation.updated_at = now
    if object_id is not None:
        current = await db.get(PermanentDeletionObject, object_id)
        if current is not None:
            current.state = PermanentDeletionObjectState.MANUAL_REVIEW
            current.result_code = code[:64]
    await db.commit()
    return PermanentDeletionStatus.MANUAL_REVIEW


async def _retryable(
    db: SQLModelAsyncSession,
    *,
    operation_id: int,
    lease_token: str,
    code: str,
    now: datetime,
    jitter_fraction: float,
    object_id: int | None = None,
) -> PermanentDeletionStatus:
    operation = await _owned_operation(db, operation_id, lease_token)
    try:
        scheduled = next_retry_at(
            accepted_at=operation.accepted_at,
            attempt_count=operation.automatic_attempt_count,
            now=now,
            jitter_fraction=jitter_fraction,
        )
    except RetryBudgetExhausted:
        return await _manual_review(
            db,
            operation_id=operation_id,
            lease_token=lease_token,
            code="automatic_retry_budget_exhausted",
            now=now,
            object_id=object_id,
        )
    operation.status = PermanentDeletionStatus.RETRYABLE_FAILED
    operation.result_code = code[:64]
    operation.next_attempt_at = scheduled
    operation.lease_token = None
    operation.lease_expires_at = None
    operation.updated_at = now
    if object_id is not None:
        current = await db.get(PermanentDeletionObject, object_id)
        if current is not None:
            current.state = PermanentDeletionObjectState.RETRYABLE_FAILED
            current.result_code = code[:64]
    await db.commit()
    return PermanentDeletionStatus.RETRYABLE_FAILED


async def _finalize_plan(
    db: SQLModelAsyncSession,
    plan: DeletionPlan,
    *,
    now: datetime,
) -> None:
    detach_submission_ids = {
        int(target.snapshot["submission_id"])
        for target in plan.targets.values()
        if target.entity_type == "archive_submission_event"
        and target.role == "detach"
        and target.snapshot.get("submission_id") is not None
    }
    await detach_archive_submission_events(db, detach_submission_ids)

    for target in plan.targets.values():
        if target.entity_type == TrashEntityType.ARCHIVE_SUBMISSION.value and target.role == "mark_unrecoverable":
            row = await db.get(ArchiveSubmission, target.entity_id)
            if row is None:
                raise PermanentDeletionError("finalization_target_missing")
            row.status = SubmissionStatus.DELETED
            row.deleted_at = row.deleted_at or now
            row.delete_reason = "linked archive permanently deleted"
            row.lifecycle_reason = LIFECYCLE_LINKED_ARCHIVE_PERMANENTLY_DELETED
            row.created_archive_id = None
            row.restored_at = None
            row.restored_by_id = None

    model_by_type = {
        "archive_discussion_message": ArchiveDiscussionMessage,
        TrashEntityType.ARCHIVE_SUBMISSION.value: ArchiveSubmission,
        TrashEntityType.ARCHIVE.value: Archive,
        TrashEntityType.COURSE_SUBMISSION.value: CourseSubmission,
        TrashEntityType.SYSTEM_ISSUE_REPORT.value: SystemIssueReport,
        TrashEntityType.COMMENT_REPORT.value: CommentReport,
        TrashEntityType.ARCHIVE_WISH_REPORT.value: ArchiveWishReport,
        TrashEntityType.ARCHIVE_REPORT.value: ArchiveReport,
        TrashEntityType.NOTIFICATION.value: Notification,
        TrashEntityType.COURSE.value: Course,
        TrashEntityType.COURSE_CATEGORY.value: CourseCategoryConfig,
        TrashEntityType.USER.value: User,
    }
    priority = {
        "archive_discussion_message": 0,
        TrashEntityType.ARCHIVE_SUBMISSION.value: 1,
        TrashEntityType.ARCHIVE.value: 2,
        TrashEntityType.COURSE_SUBMISSION.value: 3,
        TrashEntityType.SYSTEM_ISSUE_REPORT.value: 3,
        TrashEntityType.COMMENT_REPORT.value: 3,
        TrashEntityType.ARCHIVE_WISH_REPORT.value: 3,
        TrashEntityType.ARCHIVE_REPORT.value: 3,
        TrashEntityType.NOTIFICATION.value: 3,
        TrashEntityType.COURSE.value: 4,
        TrashEntityType.COURSE_CATEGORY.value: 5,
        TrashEntityType.USER.value: 6,
    }
    deletions = [
        target
        for target in plan.targets.values()
        if target.role == "delete" and target.entity_type in model_by_type
    ]
    for target in sorted(
        deletions,
        key=lambda item: (priority[item.entity_type], item.entity_id),
    ):
        row = await db.get(model_by_type[target.entity_type], target.entity_id)
        if row is None:
            raise PermanentDeletionError("finalization_target_missing")
        if isinstance(row, ArchiveSubmission):
            row.created_archive_id = None
        await db.delete(row)
    await db.flush()


async def process_one_permanent_deletion(
    db: SQLModelAsyncSession,
    *,
    operation_id: int,
    storage: ExactVersionMinioAdapter | None,
    now: datetime | None = None,
    jitter_fraction: float = 0.0,
    lease_for: timedelta = timedelta(minutes=5),
) -> PermanentDeletionStatus:
    timestamp = now or datetime.now(UTC)
    current_status = await _operation_status(db, operation_id)
    if current_status in {
        PermanentDeletionStatus.COMPLETED,
        PermanentDeletionStatus.MANUAL_REVIEW,
    }:
        return current_status
    lease_token = uuid.uuid4().hex
    claimed = await claim_permanent_deletion(
        db,
        operation_id=operation_id,
        lease_token=lease_token,
        now=timestamp,
        lease_for=lease_for,
    )
    if not claimed:
        return await _operation_status(db, operation_id)

    try:
        operation = await _owned_operation(db, operation_id, lease_token)
        await _validate_membership(db, operation)
        await db.commit()
    except (PermanentDeletionError, StorageSafetyError) as exc:
        await db.rollback()
        return await _manual_review(
            db,
            operation_id=operation_id,
            lease_token=lease_token,
            code=getattr(exc, "code", "membership_revalidation_failed"),
            now=timestamp,
        )

    objects = await _all(
        db,
        select(PermanentDeletionObject)
        .where(PermanentDeletionObject.operation_id == operation_id)
        .order_by(PermanentDeletionObject.id),
    )
    if objects and storage is None:
        return await _manual_review(
            db,
            operation_id=operation_id,
            lease_token=lease_token,
            code="storage_adapter_missing",
            now=timestamp,
        )

    for object_row in objects:
        object_id = int(object_row.id)
        try:
            operation = await _owned_operation(db, operation_id, lease_token)
            await _validate_membership(db, operation)
            observation = storage.inspect_exact_version(
                object_row.object_key, object_row.version_id
            )
        except (PermanentDeletionError, StorageSafetyError) as exc:
            await db.rollback()
            return await _manual_review(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code=getattr(exc, "code", "storage_revalidation_failed"),
                now=timestamp,
                object_id=object_id,
            )

        current_object = await db.get(PermanentDeletionObject, object_row.id)
        if current_object is None:
            await db.rollback()
            return await _manual_review(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code="storage_recovery_record_missing",
                now=timestamp,
            )
        current_object.last_verified_at = timestamp
        if observation is ExactVersionState.VERIFIED_ABSENT:
            current_object.state = PermanentDeletionObjectState.VERIFIED_ABSENT
            current_object.verified_absent_at = timestamp
            current_object.result_code = "verified_absent"
            await db.commit()
            continue
        if current_object.state == PermanentDeletionObjectState.VERIFICATION_REQUIRED:
            await db.commit()
            return await _retryable(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code="unknown_outcome_verified_present",
                now=timestamp,
                jitter_fraction=jitter_fraction,
                object_id=object_id,
            )

        operation = await _owned_operation(db, operation_id, lease_token)
        if (
            operation.automatic_attempt_count >= 10
            or current_object.delete_attempt_count >= 10
            or operation.retry_deadline_at is None
            or timestamp >= operation.retry_deadline_at
        ):
            await db.rollback()
            return await _manual_review(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code="automatic_retry_budget_exhausted",
                now=timestamp,
                object_id=object_id,
            )
        operation.automatic_attempt_count += 1
        operation.updated_at = timestamp
        current_object.delete_attempt_count += 1
        current_object.last_delete_attempt_at = timestamp
        current_object.state = PermanentDeletionObjectState.DELETE_IN_PROGRESS
        current_object.result_code = None
        await db.commit()

        try:
            result = storage.delete_exact_version(
                current_object.object_key,
                current_object.version_id,
            )
        except DeleteOutcomeUnknown as exc:
            current_object = await db.get(PermanentDeletionObject, object_row.id)
            operation = await _owned_operation(db, operation_id, lease_token)
            current_object.state = PermanentDeletionObjectState.VERIFICATION_REQUIRED
            current_object.last_unknown_outcome_at = timestamp
            current_object.result_code = exc.code
            operation.status = PermanentDeletionStatus.VERIFICATION_REQUIRED
            operation.result_code = exc.code
            operation.lease_token = None
            operation.lease_expires_at = None
            operation.updated_at = timestamp
            await db.commit()
            return PermanentDeletionStatus.VERIFICATION_REQUIRED
        except RetryableStorageError as exc:
            return await _retryable(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code=exc.code,
                now=timestamp,
                jitter_fraction=jitter_fraction,
                object_id=object_id,
            )
        except StorageSafetyError as exc:
            return await _manual_review(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code=exc.code,
                now=timestamp,
                object_id=object_id,
            )
        if result is not ExactVersionState.VERIFIED_ABSENT:
            return await _manual_review(
                db,
                operation_id=operation_id,
                lease_token=lease_token,
                code="delete_not_verified_absent",
                now=timestamp,
                object_id=object_id,
            )
        current_object = await db.get(PermanentDeletionObject, object_row.id)
        current_object.state = PermanentDeletionObjectState.VERIFIED_ABSENT
        current_object.last_verified_at = timestamp
        current_object.verified_absent_at = timestamp
        current_object.result_code = "verified_absent"
        await db.commit()

    try:
        operation = await _owned_operation(db, operation_id, lease_token)
        plan = await _validate_membership(db, operation)
        current_objects = await _all(
            db,
            select(PermanentDeletionObject).where(
                PermanentDeletionObject.operation_id == operation_id
            ),
        )
        for object_row in current_objects:
            if storage is None or storage.inspect_exact_version(
                object_row.object_key, object_row.version_id
            ) is not ExactVersionState.VERIFIED_ABSENT:
                raise PermanentDeletionError("final_storage_truth_unproven")
        await _finalize_plan(db, plan, now=timestamp)
        operation.status = PermanentDeletionStatus.COMPLETED
        operation.completed_at = timestamp
        operation.audit_purge_after = timestamp + timedelta(days=180)
        operation.result_code = "completed"
        operation.next_attempt_at = None
        operation.lease_token = None
        operation.lease_expires_at = None
        operation.updated_at = timestamp
        targets = await _stored_targets(db, operation_id)
        for target in targets:
            target.reservation_released_at = timestamp
        await db.execute(
            delete(PermanentDeletionObject).where(
                PermanentDeletionObject.operation_id == operation_id
            )
        )
        await db.commit()
        return PermanentDeletionStatus.COMPLETED
    except Exception:  # noqa: BLE001 - finalization rollback is the saga barrier
        await db.rollback()
        return await _retryable(
            db,
            operation_id=operation_id,
            lease_token=lease_token,
            code="db_finalization_failed",
            now=timestamp,
            jitter_fraction=jitter_fraction,
        )
