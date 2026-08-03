from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.models import Archive, ArchiveSubmission, Course, CourseCategoryConfig
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleLockSetExpansionError,
    LifecycleMembershipFingerprint,
    LifecyclePlanRetryExhausted,
    LifecycleResourceClass,
    LifecycleResourceRef,
    LockedLifecycleRows,
    PlanRebuildBudget,
    revalidate_lifecycle_membership,
)


def test_plan_uses_resource_class_then_numeric_primary_key_order() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        category_ids=[9, 2],
        course_ids=[8, 3],
        archive_ids=[7, 1],
        submission_ids=[6, 4],
    )

    assert plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE_CATEGORY, 2),
        LifecycleResourceRef(LifecycleResourceClass.COURSE_CATEGORY, 9),
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 3),
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 8),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 1),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 4),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 6),
    )


def test_plan_deduplicates_omits_null_and_is_input_order_independent() -> None:
    first = ArchiveLifecycleLockPlan.build(
        category_ids=[None, 4, 2, 4],
        course_ids=[7, None, 7],
        archive_ids=[5, 1, None],
        submission_ids=[11, 3, 11],
    )
    second = ArchiveLifecycleLockPlan.build(
        category_ids=[2, 4],
        course_ids=[7],
        archive_ids=[1, 5],
        submission_ids=[3, 11],
    )

    assert first == second


def test_plan_and_fingerprint_are_immutable() -> None:
    fingerprint = LifecycleMembershipFingerprint(
        target_submission_id=5,
        target_created_archive_id=3,
        target_requester_id=8,
        target_owner_id=None,
        archive_course_pairs=((3, 2),),
        sibling_submission_ids=(9, 5),
    )
    plan = ArchiveLifecycleLockPlan.build(
        course_ids=[2],
        archive_ids=[3],
        submission_ids=[5, 9],
        fingerprint=fingerprint,
    )

    with pytest.raises(FrozenInstanceError):
        plan.resources = ()
    with pytest.raises(FrozenInstanceError):
        fingerprint.target_created_archive_id = None


def test_fingerprint_is_stable_and_preserves_exact_parent_only() -> None:
    first = LifecycleMembershipFingerprint(
        target_submission_id=7,
        target_created_archive_id=None,
        target_requester_id=4,
        target_owner_id=6,
        archive_course_pairs=((9, 3), (5, 2)),
        sibling_submission_ids=(12, 7, 12),
    )
    second = LifecycleMembershipFingerprint(
        target_submission_id=7,
        target_created_archive_id=None,
        target_requester_id=4,
        target_owner_id=6,
        archive_course_pairs=((5, 2), (9, 3)),
        sibling_submission_ids=(7, 12),
    )

    assert first == second
    assert first.token == second.token
    assert first.target_created_archive_id is None


def test_plan_rejects_lock_set_expansion() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        course_ids=[2],
        archive_ids=[3],
        submission_ids=[5],
    )
    expanded = ArchiveLifecycleLockPlan.build(
        course_ids=[2],
        archive_ids=[3],
        submission_ids=[5, 8],
    )

    plan.assert_no_expansion(plan)
    with pytest.raises(LifecycleLockSetExpansionError):
        plan.assert_no_expansion(expanded)


def test_plan_allows_one_rebuild_only() -> None:
    exhausted = PlanRebuildBudget().consume()

    assert exhausted.rebuilds_used == 1
    with pytest.raises(LifecyclePlanRetryExhausted):
        exhausted.consume()


def test_unknown_resource_class_is_rejected() -> None:
    with pytest.raises((TypeError, ValueError)):
        LifecycleResourceRef("user", 1)


def test_locked_result_rejects_rows_outside_plan() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        category_ids=[1],
        course_ids=[2],
        archive_ids=[3],
        submission_ids=[4],
    )
    valid = LockedLifecycleRows(
        plan=plan,
        categories=(CourseCategoryConfig(id=1, key="x", name="x"),),
        courses=(Course(id=2, name="x", category="x"),),
        archives=(
            Archive(
                id=3,
                name="x",
                academic_year=2026,
                archive_type="final",
                professor="x",
                object_name="x.pdf",
                course_id=2,
            ),
        ),
        submissions=(
            ArchiveSubmission(
                id=4,
                subject="x",
                category="x",
                name="x",
                academic_year=2026,
                archive_type="final",
                professor="x",
                object_name="x.pdf",
                requester_id=9,
            ),
        ),
    )
    assert valid.submission(4).id == 4

    with pytest.raises(LifecycleLockSetExpansionError):
        LockedLifecycleRows(
            plan=plan,
            submissions=(
                ArchiveSubmission(
                    id=8,
                    subject="x",
                    category="x",
                    name="x",
                    academic_year=2026,
                    archive_type="final",
                    professor="x",
                    object_name="x.pdf",
                    requester_id=9,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_revalidation_rejects_disappeared_target() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        submission_ids=[4],
        fingerprint=LifecycleMembershipFingerprint(
            target_submission_id=4,
            target_requester_id=9,
        ),
    )

    result = await revalidate_lifecycle_membership(
        AsyncMock(),
        LockedLifecycleRows(plan=plan),
    )

    assert result.valid is False
    assert "target_submission_missing" in result.reasons


@pytest.mark.parametrize(
    ("created_archive_id", "requester_id"),
    [(5, 9), (3, 10)],
)
@pytest.mark.asyncio
async def test_revalidation_rejects_parent_or_authorization_identity_change(
    created_archive_id,
    requester_id,
) -> None:
    plan = ArchiveLifecycleLockPlan.build(
        submission_ids=[4],
        fingerprint=LifecycleMembershipFingerprint(
            target_submission_id=4,
            target_created_archive_id=3,
            target_requester_id=9,
        ),
    )
    changed = ArchiveSubmission(
        id=4,
        subject="x",
        category="x",
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        requester_id=requester_id,
        created_archive_id=created_archive_id,
    )

    result = await revalidate_lifecycle_membership(
        AsyncMock(),
        LockedLifecycleRows(plan=plan, submissions=(changed,)),
    )

    assert result.valid is False
    assert "membership_fingerprint_changed" in result.reasons


@pytest.mark.asyncio
async def test_revalidation_rejects_wrong_course_parent() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        course_ids=[2],
        archive_ids=[3],
        fingerprint=LifecycleMembershipFingerprint(
            archive_course_pairs=((3, 2),),
        ),
    )
    changed_archive = Archive(
        id=3,
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        course_id=8,
    )

    result = await revalidate_lifecycle_membership(
        AsyncMock(),
        LockedLifecycleRows(
            plan=plan,
            courses=(Course(id=2, name="x", category="x"),),
            archives=(changed_archive,),
        ),
    )

    assert result.valid is False
    assert "membership_fingerprint_changed" in result.reasons


@pytest.mark.asyncio
async def test_revalidation_rejects_sibling_membership_change() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        course_ids=[2],
        archive_ids=[3],
        submission_ids=[4],
        fingerprint=LifecycleMembershipFingerprint(
            archive_course_pairs=((3, 2),),
            sibling_submission_ids=(4,),
        ),
    )
    db = AsyncMock()
    query_result = MagicMock()
    query_result.scalars.return_value.all.return_value = [4, 5]
    db.execute.return_value = query_result

    result = await revalidate_lifecycle_membership(
        db,
        LockedLifecycleRows(
            plan=plan,
            courses=(Course(id=2, name="x", category="x"),),
            archives=(
                Archive(
                    id=3,
                    name="x",
                    academic_year=2026,
                    archive_type="final",
                    professor="x",
                    object_name="x.pdf",
                    course_id=2,
                ),
            ),
            submissions=(
                ArchiveSubmission(
                    id=4,
                    subject="x",
                    category="x",
                    name="x",
                    academic_year=2026,
                    archive_type="final",
                    professor="x",
                    object_name="x.pdf",
                    requester_id=9,
                    created_archive_id=3,
                ),
            ),
        ),
    )

    assert result.valid is False
    assert "membership_fingerprint_changed" in result.reasons
