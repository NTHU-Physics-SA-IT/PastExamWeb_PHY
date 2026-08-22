from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.models import Archive, ArchiveReport, ArchiveSubmission, Course
from app.services import archive_report_lifecycle_locks
from app.services.archive_lifecycle_locks import (
    LifecycleMembershipFingerprint,
    LifecycleResourceClass,
    LifecycleResourceRef,
    LifecycleRevalidationResult,
    LockedLifecycleRows,
)
from app.services.archive_report_lifecycle_locks import (
    ArchiveReportLifecycleInvariantError,
    ArchiveReportLifecyclePlan,
    ArchiveReportMembershipFingerprint,
    acquire_stable_archive_report_locks,
    discover_archive_report_lifecycle_plan,
)
from app.services.archive_submission_links import (
    ArchiveSubmissionOneToOneInvariantError,
)


def _report(
    *,
    report_id: int = 11,
    archive_id: int | None = 7,
    course_id: int | None = 5,
    submission_id: int | None = 9,
    reporter_user_id: int | None = 4,
    deleted: bool = False,
) -> ArchiveReport:
    return ArchiveReport(
        id=report_id,
        reporter_user_id=reporter_user_id,
        reporter_name_snapshot="Reporter",
        archive_id=archive_id,
        archive_id_snapshot=archive_id or 7,
        course_id=course_id,
        archive_submission_id=submission_id,
        reason="metadata_mismatch",
        archive_name_snapshot="Archive",
        course_name_snapshot="Course",
        academic_year_snapshot=2026,
        archive_type_snapshot="final",
        professor_snapshot="Professor",
        deleted_at=datetime.now(UTC) if deleted else None,
    )


def _archive(*, archive_id: int = 7, course_id: int = 5) -> Archive:
    return Archive(
        id=archive_id,
        name="Archive",
        academic_year=2026,
        archive_type="final",
        professor="Professor",
        object_name="archive.pdf",
        course_id=course_id,
    )


def _submission(
    *,
    submission_id: int = 9,
    archive_id: int | None = 7,
) -> ArchiveSubmission:
    return ArchiveSubmission(
        id=submission_id,
        subject="Course",
        category="freshman",
        name="Archive",
        academic_year=2026,
        archive_type="final",
        professor="Professor",
        object_name="archive.pdf",
        requester_id=3,
        created_archive_id=archive_id,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_report_discovery_builds_exact_parent_first_plan() -> None:
    report = _report()
    archive = _archive()
    submission = _submission()
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(report),
        _scalar_result(archive),
        _scalar_result(submission),
        _scalars_result([submission.id]),
    ]

    discovered = await discover_archive_report_lifecycle_plan(
        db,
        report_id=report.id,
        operation="archive_report_review",
    )

    assert discovered is not None
    assert discovered.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 5),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 9),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_REPORT, 11),
    )
    assert discovered.fingerprint.archive_source_submission_ids == (9,)
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_legacy_report_discovery_omits_optional_submission() -> None:
    report = _report(submission_id=None)
    archive = _archive()
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(report),
        _scalar_result(archive),
        _scalars_result([]),
    ]

    discovered = await discover_archive_report_lifecycle_plan(
        db,
        report_id=report.id,
        operation="archive_report_review",
    )

    assert discovered is not None
    assert discovered.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 5),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_REPORT, 11),
    )
    assert discovered.fingerprint.submission_present is False


@pytest.mark.asyncio
async def test_report_discovery_rejects_static_multi_source_before_locking() -> None:
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(_report()),
        _scalar_result(_archive()),
        _scalar_result(_submission()),
        _scalars_result([9, 10]),
    ]

    with pytest.raises(ArchiveSubmissionOneToOneInvariantError):
        await discover_archive_report_lifecycle_plan(
            db,
            report_id=11,
            operation="archive_report_review",
        )


@pytest.mark.asyncio
async def test_report_parent_change_rolls_back_and_rebuilds_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    expected = ArchiveReportMembershipFingerprint(
        report_id=11,
        status="pending",
        deleted=False,
        reporter_user_id=4,
        archive_id=7,
        report_course_id=5,
        archive_submission_id=9,
        archive_present=True,
        archive_course_id=5,
        submission_present=True,
        submission_created_archive_id=7,
        archive_source_submission_ids=(9,),
    )
    plan = archive_report_lifecycle_locks.ArchiveLifecycleLockPlan.build(
        course_ids=[5],
        archive_ids=[7],
        submission_ids=[9],
        report_ids=[11],
        fingerprint=LifecycleMembershipFingerprint(
            archive_course_pairs=((7, 5),),
            sibling_submission_ids=(9,),
        ),
    )
    discovered = ArchiveReportLifecyclePlan(plan, expected)
    locked_rows = LockedLifecycleRows(
        plan=plan,
        courses=(Course(id=5, name="Course", category="freshman"),),
        archives=(_archive(),),
        submissions=(_submission(),),
        reports=(report,),
    )
    acquire = AsyncMock(return_value=locked_rows)
    revalidate = AsyncMock(
        return_value=LifecycleRevalidationResult(
            valid=True,
            fingerprint=plan.fingerprint,
        )
    )
    changed = ArchiveReportMembershipFingerprint(
        **{
            **expected.__dict__,
            "archive_id": 8,
        }
    )
    locked_fingerprint = AsyncMock(side_effect=[changed, expected])
    monkeypatch.setattr(
        archive_report_lifecycle_locks,
        "discover_archive_report_lifecycle_plan",
        AsyncMock(return_value=discovered),
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks.archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        acquire,
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks.archive_lifecycle_locks,
        "revalidate_lifecycle_membership",
        revalidate,
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks,
        "_locked_fingerprint",
        locked_fingerprint,
    )
    db = AsyncMock()

    locked = await acquire_stable_archive_report_locks(
        db,
        report_id=11,
        operation="archive_report_review",
    )

    assert locked is not None
    assert locked.report.id == 11
    assert acquire.await_count == 2
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_second_parent_change_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ArchiveReportMembershipFingerprint(
        report_id=11,
        status="pending",
        deleted=False,
        reporter_user_id=4,
        archive_id=7,
        report_course_id=5,
        archive_submission_id=None,
        archive_present=True,
        archive_course_id=5,
        submission_present=False,
        submission_created_archive_id=None,
        archive_source_submission_ids=(),
    )
    plan = archive_report_lifecycle_locks.ArchiveLifecycleLockPlan.build(
        report_ids=[11]
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks,
        "discover_archive_report_lifecycle_plan",
        AsyncMock(return_value=ArchiveReportLifecyclePlan(plan, expected)),
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks.archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        AsyncMock(return_value=LockedLifecycleRows(plan=plan)),
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks.archive_lifecycle_locks,
        "revalidate_lifecycle_membership",
        AsyncMock(
            return_value=LifecycleRevalidationResult(
                valid=False,
                fingerprint=LifecycleMembershipFingerprint(),
                reasons=("membership_fingerprint_changed",),
            )
        ),
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks,
        "_locked_fingerprint",
        AsyncMock(return_value=None),
    )
    db = AsyncMock()

    with pytest.raises(ArchiveReportLifecycleInvariantError):
        await acquire_stable_archive_report_locks(
            db,
            report_id=11,
            operation="archive_report_restore",
        )

    assert db.rollback.await_count == 2


@pytest.mark.asyncio
async def test_report_lock_acquisition_does_not_translate_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ArchiveReportMembershipFingerprint(
        report_id=11,
        status="pending",
        deleted=False,
        reporter_user_id=4,
        archive_id=None,
        report_course_id=None,
        archive_submission_id=None,
        archive_present=False,
        archive_course_id=None,
        submission_present=False,
        submission_created_archive_id=None,
        archive_source_submission_ids=None,
    )
    plan = archive_report_lifecycle_locks.ArchiveLifecycleLockPlan.build(
        report_ids=[11]
    )
    database_error = RuntimeError("database lock failure")
    monkeypatch.setattr(
        archive_report_lifecycle_locks,
        "discover_archive_report_lifecycle_plan",
        AsyncMock(return_value=ArchiveReportLifecyclePlan(plan, expected)),
    )
    monkeypatch.setattr(
        archive_report_lifecycle_locks.archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        AsyncMock(side_effect=database_error),
    )

    with pytest.raises(RuntimeError, match="database lock failure"):
        await acquire_stable_archive_report_locks(
            AsyncMock(),
            report_id=11,
            operation="archive_report_review",
        )
