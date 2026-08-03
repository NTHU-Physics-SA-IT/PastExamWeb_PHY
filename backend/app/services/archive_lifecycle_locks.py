"""Canonical row-lock planning for Archive and ArchiveSubmission lifecycles."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum
import hashlib
import json
from typing import Iterable, Sequence

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    Archive,
    ArchiveSubmission,
    Course,
    CourseCategoryConfig,
)
from app.services.archive_submission_links import (
    ArchiveSubmissionLinkOperation,
    validate_archive_source_membership,
)


class LifecycleResourceClass(IntEnum):
    """Stable rank for every row class currently owned by this planner."""

    COURSE_CATEGORY = 10
    COURSE = 20
    ARCHIVE = 30
    ARCHIVE_SUBMISSION = 40


class LifecycleLockSetExpansionError(RuntimeError):
    """Raised when a caller tries to lock a row absent from its original plan."""


class LifecyclePlanRetryExhausted(RuntimeError):
    """Raised after the single permitted membership-plan rebuild is consumed."""


def _stable_ids(values: Iterable[int | None]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Lifecycle lock IDs must be positive integers")
        normalized.add(value)
    return tuple(sorted(normalized))


def _stable_archive_course_pairs(
    values: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    normalized: set[tuple[int, int]] = set()
    for archive_id, course_id in values:
        stable_archive_id = _stable_ids((archive_id,))
        stable_course_id = _stable_ids((course_id,))
        normalized.add((stable_archive_id[0], stable_course_id[0]))
    return tuple(sorted(normalized))


@dataclass(frozen=True, order=True)
class LifecycleResourceRef:
    resource_class: LifecycleResourceClass
    row_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource_class, LifecycleResourceClass):
            raise TypeError("Unknown lifecycle resource class")
        stable_id = _stable_ids((self.row_id,))
        object.__setattr__(self, "row_id", stable_id[0])


@dataclass(frozen=True)
class LifecycleMembershipFingerprint:
    """Exact parent and membership values discovered before the first row lock."""

    target_submission_id: int | None = None
    target_created_archive_id: int | None = None
    target_requester_id: int | None = None
    target_owner_id: int | None = None
    archive_course_pairs: tuple[tuple[int, int], ...] = ()
    sibling_submission_ids: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        for attribute in (
            "target_submission_id",
            "target_created_archive_id",
            "target_requester_id",
            "target_owner_id",
        ):
            value = getattr(self, attribute)
            if value is not None:
                object.__setattr__(self, attribute, _stable_ids((value,))[0])
        object.__setattr__(
            self,
            "archive_course_pairs",
            _stable_archive_course_pairs(self.archive_course_pairs),
        )
        if self.sibling_submission_ids is not None:
            object.__setattr__(
                self,
                "sibling_submission_ids",
                _stable_ids(self.sibling_submission_ids),
            )

    @property
    def token(self) -> str:
        payload = {
            "target_submission_id": self.target_submission_id,
            "target_created_archive_id": self.target_created_archive_id,
            "target_requester_id": self.target_requester_id,
            "target_owner_id": self.target_owner_id,
            "archive_course_pairs": self.archive_course_pairs,
            "sibling_submission_ids": self.sibling_submission_ids,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ArchiveLifecycleLockPlan:
    """Immutable, already-canonical sequence of rows to lock."""

    resources: tuple[LifecycleResourceRef, ...]
    fingerprint: LifecycleMembershipFingerprint = field(
        default_factory=LifecycleMembershipFingerprint
    )
    approval_namespace_scope: str | None = None

    def __post_init__(self) -> None:
        canonical = tuple(sorted(set(self.resources)))
        if canonical != self.resources:
            raise ValueError("Lifecycle resources must already be canonical")

    @classmethod
    def build(
        cls,
        *,
        category_ids: Iterable[int | None] = (),
        course_ids: Iterable[int | None] = (),
        archive_ids: Iterable[int | None] = (),
        submission_ids: Iterable[int | None] = (),
        fingerprint: LifecycleMembershipFingerprint | None = None,
        approval_namespace_scope: str | None = None,
    ) -> ArchiveLifecycleLockPlan:
        resources = tuple(
            LifecycleResourceRef(resource_class, row_id)
            for resource_class, values in (
                (LifecycleResourceClass.COURSE_CATEGORY, category_ids),
                (LifecycleResourceClass.COURSE, course_ids),
                (LifecycleResourceClass.ARCHIVE, archive_ids),
                (
                    LifecycleResourceClass.ARCHIVE_SUBMISSION,
                    submission_ids,
                ),
            )
            for row_id in _stable_ids(values)
        )
        return cls(
            resources=resources,
            fingerprint=fingerprint or LifecycleMembershipFingerprint(),
            approval_namespace_scope=approval_namespace_scope,
        )

    def ids_for(self, resource_class: LifecycleResourceClass) -> tuple[int, ...]:
        if not isinstance(resource_class, LifecycleResourceClass):
            raise TypeError("Unknown lifecycle resource class")
        return tuple(
            resource.row_id
            for resource in self.resources
            if resource.resource_class == resource_class
        )

    def assert_no_expansion(self, candidate: ArchiveLifecycleLockPlan) -> None:
        unexpected = set(candidate.resources).difference(self.resources)
        if unexpected:
            raise LifecycleLockSetExpansionError(
                "Lifecycle lock set cannot expand after acquisition starts"
            )


@dataclass(frozen=True)
class PlanRebuildBudget:
    max_rebuilds: int = 1
    rebuilds_used: int = 0

    def consume(self) -> PlanRebuildBudget:
        if self.rebuilds_used >= self.max_rebuilds:
            raise LifecyclePlanRetryExhausted(
                "Lifecycle membership changed after the bounded rebuild"
            )
        return replace(self, rebuilds_used=self.rebuilds_used + 1)


@dataclass(frozen=True)
class LockedLifecycleRows:
    plan: ArchiveLifecycleLockPlan
    categories: tuple[CourseCategoryConfig, ...] = ()
    courses: tuple[Course, ...] = ()
    archives: tuple[Archive, ...] = ()
    submissions: tuple[ArchiveSubmission, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("categories", "courses", "archives", "submissions"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))
        for resource_class, rows in (
            (LifecycleResourceClass.COURSE_CATEGORY, self.categories),
            (LifecycleResourceClass.COURSE, self.courses),
            (LifecycleResourceClass.ARCHIVE, self.archives),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, self.submissions),
        ):
            allowed = set(self.plan.ids_for(resource_class))
            actual = {row.id for row in rows}
            if None in actual or not actual.issubset(allowed):
                raise LifecycleLockSetExpansionError(
                    "Locked result contains a row outside the lifecycle plan"
                )

    def category(self, row_id: int) -> CourseCategoryConfig | None:
        return next((row for row in self.categories if row.id == row_id), None)

    def course(self, row_id: int) -> Course | None:
        return next((row for row in self.courses if row.id == row_id), None)

    def archive(self, row_id: int) -> Archive | None:
        return next((row for row in self.archives if row.id == row_id), None)

    def submission(self, row_id: int) -> ArchiveSubmission | None:
        return next((row for row in self.submissions if row.id == row_id), None)


@dataclass(frozen=True)
class LifecycleRevalidationResult:
    valid: bool
    fingerprint: LifecycleMembershipFingerprint
    reasons: tuple[str, ...] = ()


async def discover_exact_archive_lifecycle_plan(
    db: AsyncSession,
    *,
    archive_id: int,
    operation: ArchiveSubmissionLinkOperation,
) -> ArchiveLifecycleLockPlan | None:
    """Discover one Archive's exact Course and Submission membership."""

    archive = (
        await db.execute(
            select(Archive)
            .where(Archive.id == archive_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if archive is None or archive.id is None:
        return None

    sibling_ids = validate_archive_source_membership(
        (
            (
                await db.execute(
                    select(ArchiveSubmission.id)
                    .where(ArchiveSubmission.created_archive_id == archive.id)
                    .order_by(ArchiveSubmission.id.asc())
                )
            )
            .scalars()
            .all()
        ),
        operation=operation,
    )
    fingerprint = LifecycleMembershipFingerprint(
        archive_course_pairs=((archive.id, archive.course_id),),
        sibling_submission_ids=sibling_ids,
    )
    return ArchiveLifecycleLockPlan.build(
        course_ids=(archive.course_id,),
        archive_ids=(archive.id,),
        submission_ids=sibling_ids,
        fingerprint=fingerprint,
    )


def approval_namespace_scope(*, category_key: str, course_name: str) -> str:
    return f"archive_approval:{category_key}:{course_name.lower().strip()}"


async def acquire_approval_namespace_mutex(
    db: AsyncSession,
    *,
    category_key: str,
    course_name: str,
) -> str:
    """Acquire the established approval namespace mutex before any row lock."""

    scope = approval_namespace_scope(
        category_key=category_key,
        course_name=course_name,
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": scope},
    )
    return scope


async def _lock_rows(
    db: AsyncSession,
    model,
    row_ids: Sequence[int],
) -> tuple:
    if not row_ids:
        return ()
    return tuple(
        (
            await db.execute(
                select(model)
                .where(model.id.in_(row_ids))
                .order_by(model.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def acquire_lifecycle_locks(
    db: AsyncSession,
    plan: ArchiveLifecycleLockPlan,
) -> LockedLifecycleRows:
    """Lock an already-complete plan without committing or expanding it."""

    categories = await _lock_rows(
        db,
        CourseCategoryConfig,
        plan.ids_for(LifecycleResourceClass.COURSE_CATEGORY),
    )
    courses = await _lock_rows(
        db,
        Course,
        plan.ids_for(LifecycleResourceClass.COURSE),
    )
    archives = await _lock_rows(
        db,
        Archive,
        plan.ids_for(LifecycleResourceClass.ARCHIVE),
    )
    submissions = await _lock_rows(
        db,
        ArchiveSubmission,
        plan.ids_for(LifecycleResourceClass.ARCHIVE_SUBMISSION),
    )
    return LockedLifecycleRows(
        plan=plan,
        categories=categories,
        courses=courses,
        archives=archives,
        submissions=submissions,
    )


async def acquire_exact_archive_lifecycle_locks(
    db: AsyncSession,
    *,
    archive_id: int,
    operation: ArchiveSubmissionLinkOperation,
) -> tuple[LockedLifecycleRows | None, LifecycleRevalidationResult | None]:
    """Discover, lock, and revalidate one exact Archive group once."""

    plan = await discover_exact_archive_lifecycle_plan(
        db,
        archive_id=archive_id,
        operation=operation,
    )
    if plan is None:
        return None, None
    locked = await acquire_lifecycle_locks(db, plan)
    revalidation = await revalidate_lifecycle_membership(db, locked)
    return locked, revalidation


async def revalidate_lifecycle_membership(
    db: AsyncSession,
    locked: LockedLifecycleRows,
) -> LifecycleRevalidationResult:
    """Re-read exact relationships after locking and compare the fingerprint."""

    expected = locked.plan.fingerprint
    reasons: list[str] = []

    for resource_class, rows in (
        (LifecycleResourceClass.COURSE_CATEGORY, locked.categories),
        (LifecycleResourceClass.COURSE, locked.courses),
        (LifecycleResourceClass.ARCHIVE, locked.archives),
        (LifecycleResourceClass.ARCHIVE_SUBMISSION, locked.submissions),
    ):
        if {row.id for row in rows} != set(locked.plan.ids_for(resource_class)):
            reasons.append(f"missing:{resource_class.name.lower()}")

    target = (
        locked.submission(expected.target_submission_id)
        if expected.target_submission_id is not None
        else None
    )
    if expected.target_submission_id is not None and target is None:
        reasons.append("target_submission_missing")

    current_archive_pairs = tuple(
        (archive.id, archive.course_id)
        for archive in locked.archives
        if archive.id is not None
    )
    current_sibling_ids: tuple[int, ...] | None = None
    if expected.sibling_submission_ids is not None:
        archive_ids = locked.plan.ids_for(LifecycleResourceClass.ARCHIVE)
        current_sibling_ids = (
            tuple(
                (
                    await db.execute(
                        select(ArchiveSubmission.id)
                        .where(ArchiveSubmission.created_archive_id.in_(archive_ids))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if archive_ids
            else ()
        )

    current = LifecycleMembershipFingerprint(
        target_submission_id=expected.target_submission_id,
        target_created_archive_id=(
            target.created_archive_id if target is not None else None
        ),
        target_requester_id=target.requester_id if target is not None else None,
        target_owner_id=target.owner_id if target is not None else None,
        archive_course_pairs=current_archive_pairs,
        sibling_submission_ids=current_sibling_ids,
    )
    if current != expected:
        reasons.append("membership_fingerprint_changed")

    return LifecycleRevalidationResult(
        valid=not reasons,
        fingerprint=current,
        reasons=tuple(reasons),
    )
