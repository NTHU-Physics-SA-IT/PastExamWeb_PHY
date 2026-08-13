from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.archive_submission_lifecycle import (
    acquire_stable_submission_lifecycle_locks,
)
from app.models.models import (
    Archive,
    ArchiveReport,
    ArchiveSubmission,
    Course,
    CourseCategoryConfig,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    ArchiveLifecycleLockPlan,
    LifecycleLockSetExpansionError,
    LifecycleMembershipFingerprint,
    LifecyclePlanRetryExhausted,
    LifecycleResourceClass,
    LifecycleResourceRef,
    LifecycleRevalidationResult,
    LockedLifecycleRows,
    PlanRebuildBudget,
    discover_exact_archive_lifecycle_plan,
    revalidate_lifecycle_membership,
)
from app.services.archive_submission_links import (
    ArchiveSubmissionOneToOneInvariantError,
)


def test_plan_uses_resource_class_then_numeric_primary_key_order() -> None:
    plan = ArchiveLifecycleLockPlan.build(
        category_ids=[9, 2],
        course_ids=[8, 3],
        archive_ids=[7, 1],
        submission_ids=[6, 4],
        report_ids=[12, 10],
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
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_REPORT, 10),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_REPORT, 12),
    )


def test_plan_deduplicates_omits_null_and_is_input_order_independent() -> None:
    first = ArchiveLifecycleLockPlan.build(
        category_ids=[None, 4, 2, 4],
        course_ids=[7, None, 7],
        archive_ids=[5, 1, None],
        submission_ids=[11, 3, 11],
        report_ids=[13, None, 9, 13],
    )
    second = ArchiveLifecycleLockPlan.build(
        category_ids=[2, 4],
        course_ids=[7],
        archive_ids=[1, 5],
        submission_ids=[3, 11],
        report_ids=[9, 13],
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
        report_ids=[5],
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
        reports=(
            ArchiveReport(
                id=5,
                reporter_name_snapshot="x",
                archive_id_snapshot=3,
                reason="other",
                archive_name_snapshot="x",
                course_name_snapshot="x",
                academic_year_snapshot=2026,
                archive_type_snapshot="final",
                professor_snapshot="x",
            ),
        ),
    )
    assert valid.submission(4).id == 4
    assert valid.report(5).id == 5

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
async def test_archive_discovery_rejects_static_multi_source_membership() -> None:
    archive = Archive(
        id=3,
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        course_id=2,
    )
    archive_result = MagicMock()
    archive_result.scalar_one_or_none.return_value = archive
    sibling_result = MagicMock()
    sibling_result.scalars.return_value.all.return_value = [4, 5]
    db = AsyncMock()
    db.execute.side_effect = [archive_result, sibling_result]

    with pytest.raises(ArchiveSubmissionOneToOneInvariantError):
        await discover_exact_archive_lifecycle_plan(
            db,
            archive_id=archive.id,
            operation="archive_trash",
        )


@pytest.mark.asyncio
async def test_unlinked_submission_discovery_plans_only_the_submission() -> None:
    submission = ArchiveSubmission(
        id=7,
        subject="x",
        category="x",
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        requester_id=9,
        owner_id=11,
        created_archive_id=None,
    )
    submission_result = MagicMock()
    submission_result.scalar_one_or_none.return_value = submission
    db = AsyncMock()
    db.execute.return_value = submission_result

    plan = await archive_lifecycle_locks.discover_exact_submission_lifecycle_plan(
        db,
        submission_id=submission.id,
        operation="submission_delete",
    )

    assert plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 7),
    )
    assert plan.fingerprint == LifecycleMembershipFingerprint(
        target_submission_id=7,
        target_created_archive_id=None,
        target_requester_id=9,
        target_owner_id=11,
    )


@pytest.mark.asyncio
async def test_linked_submission_discovery_plans_parent_first() -> None:
    submission = ArchiveSubmission(
        id=7,
        subject="x",
        category="x",
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        requester_id=9,
        created_archive_id=5,
    )
    archive = Archive(
        id=5,
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        course_id=3,
    )
    submission_result = MagicMock()
    submission_result.scalar_one_or_none.return_value = submission
    archive_result = MagicMock()
    archive_result.scalar_one_or_none.return_value = archive
    sibling_result = MagicMock()
    sibling_result.scalars.return_value.all.return_value = [7]
    db = AsyncMock()
    db.execute.side_effect = [
        submission_result,
        archive_result,
        sibling_result,
    ]

    plan = await archive_lifecycle_locks.discover_exact_submission_lifecycle_plan(
        db,
        submission_id=submission.id,
        operation="submission_restore",
    )

    assert plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 3),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 5),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 7),
    )
    assert plan.fingerprint == LifecycleMembershipFingerprint(
        target_submission_id=7,
        target_created_archive_id=5,
        target_requester_id=9,
        target_owner_id=None,
        archive_course_pairs=((5, 3),),
        sibling_submission_ids=(7,),
    )


@pytest.mark.asyncio
async def test_submission_discovery_rejects_static_multi_source_membership() -> None:
    submission = ArchiveSubmission(
        id=7,
        subject="x",
        category="x",
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        requester_id=9,
        created_archive_id=5,
    )
    archive = Archive(
        id=5,
        name="x",
        academic_year=2026,
        archive_type="final",
        professor="x",
        object_name="x.pdf",
        course_id=3,
    )
    submission_result = MagicMock()
    submission_result.scalar_one_or_none.return_value = submission
    archive_result = MagicMock()
    archive_result.scalar_one_or_none.return_value = archive
    sibling_result = MagicMock()
    sibling_result.scalars.return_value.all.return_value = [7, 8]
    db = AsyncMock()
    db.execute.side_effect = [
        submission_result,
        archive_result,
        sibling_result,
    ]

    with pytest.raises(ArchiveSubmissionOneToOneInvariantError):
        await archive_lifecycle_locks.discover_exact_submission_lifecycle_plan(
            db,
            submission_id=submission.id,
            operation="submission_delete",
        )


@pytest.mark.asyncio
async def test_submission_lifecycle_rebuilds_once_after_membership_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = ArchiveLifecycleLockPlan.build(submission_ids=[7])
    locked = LockedLifecycleRows(
        plan=plan,
        submissions=(
            ArchiveSubmission(
                id=7,
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
    invalid = LifecycleRevalidationResult(
        valid=False,
        fingerprint=LifecycleMembershipFingerprint(),
        reasons=("membership_fingerprint_changed",),
    )
    valid = LifecycleRevalidationResult(
        valid=True,
        fingerprint=LifecycleMembershipFingerprint(),
    )
    acquire = AsyncMock(side_effect=[(locked, invalid), (locked, valid)])
    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_exact_submission_lifecycle_locks",
        acquire,
    )
    db = AsyncMock()

    result = await acquire_stable_submission_lifecycle_locks(
        db,
        submission_id=7,
        operation="submission_restore",
    )

    assert result is locked
    assert acquire.await_count == 2
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_submission_lifecycle_second_membership_change_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = ArchiveLifecycleLockPlan.build(submission_ids=[7])
    locked = LockedLifecycleRows(plan=plan)
    invalid = LifecycleRevalidationResult(
        valid=False,
        fingerprint=LifecycleMembershipFingerprint(),
        reasons=("membership_fingerprint_changed",),
    )
    acquire = AsyncMock(return_value=(locked, invalid))
    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_exact_submission_lifecycle_locks",
        acquire,
    )
    db = AsyncMock()

    with pytest.raises(LifecyclePlanRetryExhausted):
        await acquire_stable_submission_lifecycle_locks(
            db,
            submission_id=7,
            operation="submission_delete",
        )

    assert acquire.await_count == 2
    assert db.rollback.await_count == 2


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
