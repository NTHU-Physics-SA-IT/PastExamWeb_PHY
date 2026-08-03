"""Course trash/restore discovery built on the canonical lifecycle lock planner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Iterable

from sqlalchemy import and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.archive_submission_lifecycle import (
    LIFECYCLE_COURSE_TRASHED,
)
from app.models.models import (
    Archive,
    ArchiveSubmission,
    Course,
    CourseCategoryConfig,
    SubmissionStatus,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleResourceClass,
    LockedLifecycleRows,
)
from app.services.archive_submission_links import (
    validate_archive_source_submission_rows,
)
from app.utils.course_text import (
    normalize_course_search_text,
    normalized_course_text_expr,
)


class CourseLifecycleOperation(StrEnum):
    TRASH = "course_trash"
    RESTORE = "course_restore"


def _stable_ids(values: Iterable[int | None]) -> tuple[int, ...]:
    normalized = {value for value in values if value is not None}
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in normalized
    ):
        raise ValueError("Course lifecycle IDs must be positive integers")
    return tuple(sorted(normalized))


@dataclass(frozen=True, order=True)
class CourseArchiveMembership:
    archive_id: int
    course_id: int
    deleted: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "archive_id", _stable_ids((self.archive_id,))[0])
        object.__setattr__(self, "course_id", _stable_ids((self.course_id,))[0])


@dataclass(frozen=True, order=True)
class CourseSubmissionMembership:
    submission_id: int
    created_archive_id: int | None
    status: str
    deleted: bool
    lifecycle_reason: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "submission_id",
            _stable_ids((self.submission_id,))[0],
        )
        if self.created_archive_id is not None:
            object.__setattr__(
                self,
                "created_archive_id",
                _stable_ids((self.created_archive_id,))[0],
            )


@dataclass(frozen=True)
class CourseLifecycleFingerprint:
    operation: CourseLifecycleOperation
    course_id: int
    course_name_key: str
    course_category_key: str
    category_state: tuple[int, str, bool, bool] | None
    direct_archive_ids: tuple[int, ...]
    archive_membership: tuple[CourseArchiveMembership, ...]
    submission_membership: tuple[CourseSubmissionMembership, ...]
    mutable_archive_ids: tuple[int, ...]
    mutable_submission_ids: tuple[int, ...]
    blocked_archive_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operation, CourseLifecycleOperation):
            raise TypeError("Unknown Course lifecycle operation")
        object.__setattr__(self, "course_id", _stable_ids((self.course_id,))[0])
        object.__setattr__(
            self,
            "direct_archive_ids",
            _stable_ids(self.direct_archive_ids),
        )
        object.__setattr__(
            self,
            "archive_membership",
            tuple(sorted(set(self.archive_membership))),
        )
        object.__setattr__(
            self,
            "submission_membership",
            tuple(sorted(set(self.submission_membership))),
        )
        for attribute in (
            "mutable_archive_ids",
            "mutable_submission_ids",
            "blocked_archive_ids",
        ):
            object.__setattr__(
                self,
                attribute,
                _stable_ids(getattr(self, attribute)),
            )

    @property
    def token(self) -> str:
        payload = {
            "operation": self.operation.value,
            "course_id": self.course_id,
            "course_name_key": self.course_name_key,
            "course_category_key": self.course_category_key,
            "category_state": self.category_state,
            "direct_archive_ids": self.direct_archive_ids,
            "archive_membership": [
                (item.archive_id, item.course_id, item.deleted)
                for item in self.archive_membership
            ],
            "submission_membership": [
                (
                    item.submission_id,
                    item.created_archive_id,
                    item.status,
                    item.deleted,
                    item.lifecycle_reason,
                )
                for item in self.submission_membership
            ],
            "mutable_archive_ids": self.mutable_archive_ids,
            "mutable_submission_ids": self.mutable_submission_ids,
            "blocked_archive_ids": self.blocked_archive_ids,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CourseLifecyclePlan:
    operation: CourseLifecycleOperation
    lock_plan: ArchiveLifecycleLockPlan
    fingerprint: CourseLifecycleFingerprint
    mutable_archive_ids: tuple[int, ...]
    mutable_submission_ids: tuple[int, ...]
    blocked_archive_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.operation is not self.fingerprint.operation:
            raise ValueError("Course lifecycle operation and fingerprint differ")
        for attribute, resource_class in (
            ("mutable_archive_ids", LifecycleResourceClass.ARCHIVE),
            (
                "mutable_submission_ids",
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
            ),
            ("blocked_archive_ids", LifecycleResourceClass.ARCHIVE),
        ):
            normalized = _stable_ids(getattr(self, attribute))
            if not set(normalized).issubset(self.lock_plan.ids_for(resource_class)):
                raise ValueError("Course lifecycle mutation row is outside the plan")
            object.__setattr__(self, attribute, normalized)


@dataclass(frozen=True)
class LockedCourseLifecyclePlan:
    plan: CourseLifecyclePlan
    rows: LockedLifecycleRows


@dataclass(frozen=True)
class CourseLifecycleRevalidationResult:
    valid: bool
    fingerprint: CourseLifecycleFingerprint | None
    reasons: tuple[str, ...] = ()


def build_course_lifecycle_plan(
    *,
    operation: CourseLifecycleOperation,
    course_id: int,
    category_id: int | None,
    archive_membership: Iterable[CourseArchiveMembership],
    submission_membership: Iterable[CourseSubmissionMembership],
    mutable_archive_ids: Iterable[int | None],
    mutable_submission_ids: Iterable[int | None],
    blocked_archive_ids: Iterable[int | None],
    course_name_key: str,
    course_category_key: str,
    category_state: tuple[int, str, bool, bool] | None = None,
    direct_archive_ids: Iterable[int | None] = (),
) -> CourseLifecyclePlan:
    stable_archives = tuple(sorted(set(archive_membership)))
    stable_submissions = tuple(sorted(set(submission_membership)))
    stable_mutable_archives = _stable_ids(mutable_archive_ids)
    stable_mutable_submissions = _stable_ids(mutable_submission_ids)
    stable_blocked_archives = _stable_ids(blocked_archive_ids)
    fingerprint = CourseLifecycleFingerprint(
        operation=operation,
        course_id=course_id,
        course_name_key=course_name_key,
        course_category_key=course_category_key,
        category_state=category_state,
        direct_archive_ids=_stable_ids(direct_archive_ids),
        archive_membership=stable_archives,
        submission_membership=stable_submissions,
        mutable_archive_ids=stable_mutable_archives,
        mutable_submission_ids=stable_mutable_submissions,
        blocked_archive_ids=stable_blocked_archives,
    )
    parent_course_ids = _stable_ids(
        (course_id, *(item.course_id for item in stable_archives))
    )
    lock_plan = ArchiveLifecycleLockPlan.build(
        category_ids=(category_id,),
        course_ids=parent_course_ids,
        archive_ids=(item.archive_id for item in stable_archives),
        submission_ids=(item.submission_id for item in stable_submissions),
    )
    return CourseLifecyclePlan(
        operation=operation,
        lock_plan=lock_plan,
        fingerprint=fingerprint,
        mutable_archive_ids=stable_mutable_archives,
        mutable_submission_ids=stable_mutable_submissions,
        blocked_archive_ids=stable_blocked_archives,
    )


def _submission_match_conditions(
    *,
    course_name: str,
    course_category: str,
) -> list:
    normalized_course_name = normalize_course_search_text(course_name)
    if not normalized_course_name:
        return []
    name_match = or_(
        normalized_course_text_expr(ArchiveSubmission.requested_course_name)
        == normalized_course_name,
        normalized_course_text_expr(ArchiveSubmission.subject)
        == normalized_course_name,
    )
    normalized_category = normalize_course_search_text(course_category)
    if not normalized_category:
        return [name_match]
    return [
        and_(
            name_match,
            or_(
                func.lower(func.trim(ArchiveSubmission.requested_category_key))
                == normalized_category,
                func.lower(func.trim(ArchiveSubmission.category))
                == normalized_category,
            ),
        )
    ]


def _archive_membership(
    archives: Iterable[Archive],
) -> tuple[CourseArchiveMembership, ...]:
    return tuple(
        CourseArchiveMembership(
            archive_id=archive.id,
            course_id=archive.course_id,
            deleted=archive.deleted_at is not None,
        )
        for archive in archives
        if archive.id is not None
    )


def _submission_membership(
    submissions: Iterable[ArchiveSubmission],
) -> tuple[CourseSubmissionMembership, ...]:
    return tuple(
        CourseSubmissionMembership(
            submission_id=submission.id,
            created_archive_id=submission.created_archive_id,
            status=submission.status.value,
            deleted=(
                submission.deleted_at is not None
                or submission.status == SubmissionStatus.DELETED
            ),
            lifecycle_reason=submission.lifecycle_reason,
        )
        for submission in submissions
        if submission.id is not None
    )


async def _course(
    db: AsyncSession,
    *,
    course_id: int,
    deleted: bool,
) -> Course | None:
    deleted_condition = (
        Course.deleted_at.is_not(None) if deleted else Course.deleted_at.is_(None)
    )
    return (
        await db.execute(
            select(Course)
            .where(Course.id == course_id, deleted_condition)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def discover_course_trash_plan(
    db: AsyncSession,
    *,
    course_id: int,
) -> CourseLifecyclePlan | None:
    course = await _course(db, course_id=course_id, deleted=False)
    if course is None or course.id is None:
        return None

    direct_archives = tuple(
        (
            await db.execute(
                select(Archive)
                .where(Archive.course_id == course.id)
                .order_by(Archive.id.asc())
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    direct_archive_ids = _stable_ids(archive.id for archive in direct_archives)
    conditions: list = []
    if direct_archive_ids:
        conditions.append(ArchiveSubmission.created_archive_id.in_(direct_archive_ids))
    conditions.extend(
        _submission_match_conditions(
            course_name=course.name,
            course_category=course.category,
        )
    )
    submissions = (
        tuple(
            (
                await db.execute(
                    select(ArchiveSubmission)
                    .where(
                        or_(*conditions),
                        ArchiveSubmission.deleted_at.is_(None),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                    )
                    .order_by(ArchiveSubmission.id.asc())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if conditions
        else ()
    )
    linked_archive_ids = _stable_ids(
        submission.created_archive_id for submission in submissions
    )
    extra_archive_ids = tuple(
        archive_id
        for archive_id in linked_archive_ids
        if archive_id not in set(direct_archive_ids)
    )
    extra_archives = (
        tuple(
            (
                await db.execute(
                    select(Archive)
                    .where(Archive.id.in_(extra_archive_ids))
                    .order_by(Archive.id.asc())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if extra_archive_ids
        else ()
    )
    archives_by_id = {
        archive.id: archive
        for archive in (*direct_archives, *extra_archives)
        if archive.id is not None
    }
    validate_archive_source_submission_rows(
        ((submission.created_archive_id, submission.id) for submission in submissions),
        operation=CourseLifecycleOperation.TRASH.value,
    )
    mutable_archive_ids = (
        archive.id for archive in archives_by_id.values() if archive.deleted_at is None
    )
    return build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.TRASH,
        course_id=course.id,
        category_id=None,
        archive_membership=_archive_membership(archives_by_id.values()),
        submission_membership=_submission_membership(submissions),
        mutable_archive_ids=mutable_archive_ids,
        mutable_submission_ids=(submission.id for submission in submissions),
        blocked_archive_ids=(),
        course_name_key=normalize_course_search_text(course.name),
        course_category_key=normalize_course_search_text(course.category),
        direct_archive_ids=direct_archive_ids,
    )


def _course_marker_condition(course_id: int):
    pattern = f"course_id={course_id}"
    return or_(
        ArchiveSubmission.lifecycle_reason.like(f"%|{pattern}|%"),
        ArchiveSubmission.lifecycle_reason.like(f"%|{pattern}"),
    )


def _course_trash_reason_condition(course_id: int):
    return or_(
        ArchiveSubmission.lifecycle_reason == LIFECYCLE_COURSE_TRASHED,
        ArchiveSubmission.lifecycle_reason.like(f"{LIFECYCLE_COURSE_TRASHED}|%"),
        _course_marker_condition(course_id),
    )


async def discover_course_restore_plan(
    db: AsyncSession,
    *,
    course_id: int,
) -> CourseLifecyclePlan | None:
    course = await _course(db, course_id=course_id, deleted=True)
    if course is None or course.id is None:
        return None

    category = (
        await db.execute(
            select(CourseCategoryConfig)
            .where(CourseCategoryConfig.key == course.category)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    direct_archives = tuple(
        (
            await db.execute(
                select(Archive)
                .where(Archive.course_id == course.id)
                .order_by(Archive.id.asc())
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    direct_archive_ids = _stable_ids(archive.id for archive in direct_archives)
    marker_submissions = tuple(
        (
            await db.execute(
                select(ArchiveSubmission)
                .where(
                    ArchiveSubmission.deleted_at.is_(None),
                    ArchiveSubmission.status != SubmissionStatus.DELETED,
                    ArchiveSubmission.created_archive_id.is_not(None),
                    _course_marker_condition(course.id),
                )
                .order_by(ArchiveSubmission.id.asc())
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    marker_archive_ids = _stable_ids(
        submission.created_archive_id for submission in marker_submissions
    )
    archive_conditions = [Archive.course_id == course.id]
    if marker_archive_ids:
        archive_conditions.append(Archive.id.in_(marker_archive_ids))
    candidate_archives = tuple(
        (
            await db.execute(
                select(Archive)
                .where(
                    or_(*archive_conditions),
                    Archive.deleted_at.is_not(None),
                )
                .order_by(Archive.id.asc())
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    candidate_archive_ids = _stable_ids(archive.id for archive in candidate_archives)
    blocker_submissions = (
        tuple(
            (
                await db.execute(
                    select(ArchiveSubmission)
                    .where(
                        ArchiveSubmission.created_archive_id.in_(candidate_archive_ids),
                        or_(
                            ArchiveSubmission.deleted_at.is_not(None),
                            ArchiveSubmission.status == SubmissionStatus.DELETED,
                        ),
                    )
                    .order_by(ArchiveSubmission.id.asc())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if candidate_archive_ids
        else ()
    )
    validate_archive_source_submission_rows(
        (
            (submission.created_archive_id, submission.id)
            for submission in (*marker_submissions, *blocker_submissions)
        ),
        operation=CourseLifecycleOperation.RESTORE.value,
    )
    blocked_archive_ids = _stable_ids(
        submission.created_archive_id for submission in blocker_submissions
    )
    mutable_archive_ids = tuple(
        archive_id
        for archive_id in candidate_archive_ids
        if archive_id not in set(blocked_archive_ids)
    )

    submission_conditions: list = []
    if mutable_archive_ids:
        submission_conditions.append(
            ArchiveSubmission.created_archive_id.in_(mutable_archive_ids)
        )
    submission_conditions.extend(
        _submission_match_conditions(
            course_name=course.name,
            course_category=course.category,
        )
    )
    mutable_submissions = (
        tuple(
            (
                await db.execute(
                    select(ArchiveSubmission)
                    .where(
                        ArchiveSubmission.deleted_at.is_(None),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                        or_(*submission_conditions),
                        _course_trash_reason_condition(course.id),
                    )
                    .order_by(ArchiveSubmission.id.asc())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if submission_conditions
        else ()
    )
    all_submissions_by_id = {
        submission.id: submission
        for submission in (
            *marker_submissions,
            *blocker_submissions,
            *mutable_submissions,
        )
        if submission.id is not None
    }
    validate_archive_source_submission_rows(
        (
            (submission.created_archive_id, submission.id)
            for submission in all_submissions_by_id.values()
        ),
        operation=CourseLifecycleOperation.RESTORE.value,
    )
    archives_by_id = {
        archive.id: archive
        for archive in (*direct_archives, *candidate_archives)
        if archive.id is not None
    }
    category_state = (
        (
            category.id,
            category.key,
            category.is_active,
            category.deleted_at is not None,
        )
        if category is not None and category.id is not None
        else None
    )
    return build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.RESTORE,
        course_id=course.id,
        category_id=category.id if category is not None else None,
        archive_membership=_archive_membership(archives_by_id.values()),
        submission_membership=_submission_membership(all_submissions_by_id.values()),
        mutable_archive_ids=mutable_archive_ids,
        mutable_submission_ids=(submission.id for submission in mutable_submissions),
        blocked_archive_ids=blocked_archive_ids,
        course_name_key=normalize_course_search_text(course.name),
        course_category_key=normalize_course_search_text(course.category),
        category_state=category_state,
        direct_archive_ids=direct_archive_ids,
    )


async def discover_course_lifecycle_plan(
    db: AsyncSession,
    *,
    course_id: int,
    operation: CourseLifecycleOperation,
) -> CourseLifecyclePlan | None:
    if operation is CourseLifecycleOperation.TRASH:
        return await discover_course_trash_plan(db, course_id=course_id)
    if operation is CourseLifecycleOperation.RESTORE:
        return await discover_course_restore_plan(db, course_id=course_id)
    raise TypeError("Unknown Course lifecycle operation")


async def revalidate_course_lifecycle_plan(
    db: AsyncSession,
    locked: LockedCourseLifecyclePlan,
) -> CourseLifecycleRevalidationResult:
    reasons: list[str] = []
    for resource_class, rows in (
        (LifecycleResourceClass.COURSE_CATEGORY, locked.rows.categories),
        (LifecycleResourceClass.COURSE, locked.rows.courses),
        (LifecycleResourceClass.ARCHIVE, locked.rows.archives),
        (
            LifecycleResourceClass.ARCHIVE_SUBMISSION,
            locked.rows.submissions,
        ),
    ):
        if {row.id for row in rows} != set(
            locked.plan.lock_plan.ids_for(resource_class)
        ):
            reasons.append(f"missing:{resource_class.name.lower()}")

    current = await discover_course_lifecycle_plan(
        db,
        course_id=locked.plan.fingerprint.course_id,
        operation=locked.plan.operation,
    )
    if current is None:
        reasons.append("course_membership_missing")
        return CourseLifecycleRevalidationResult(
            valid=False,
            fingerprint=None,
            reasons=tuple(reasons),
        )
    if current.fingerprint != locked.plan.fingerprint:
        reasons.append("course_membership_fingerprint_changed")
    return CourseLifecycleRevalidationResult(
        valid=not reasons,
        fingerprint=current.fingerprint,
        reasons=tuple(reasons),
    )


async def acquire_course_lifecycle_plan_once(
    db: AsyncSession,
    *,
    course_id: int,
    operation: CourseLifecycleOperation,
) -> tuple[
    LockedCourseLifecyclePlan | None,
    CourseLifecycleRevalidationResult | None,
]:
    plan = await discover_course_lifecycle_plan(
        db,
        course_id=course_id,
        operation=operation,
    )
    if plan is None:
        return None, None
    rows = await archive_lifecycle_locks.acquire_lifecycle_locks(
        db,
        plan.lock_plan,
    )
    locked = LockedCourseLifecyclePlan(plan=plan, rows=rows)
    revalidation = await revalidate_course_lifecycle_plan(db, locked)
    return locked, revalidation
