from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.services import archive_submission_lifecycle as lifecycle
from app.api.services.archive_submission_lifecycle import (
    ArchiveSubmissionGroup,
    acquire_stable_archive_submission_group_locks,
    detach_archive_submission_events,
)
from app.services.archive_lifecycle_locks import LifecycleResourceClass


@pytest.mark.asyncio
async def test_detach_archive_submission_events_targets_exact_ids() -> None:
    result = SimpleNamespace(rowcount=2)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    detached = await detach_archive_submission_events(db, {17, 23})

    assert detached == 2
    statement = db.execute.await_args.args[0]
    assert "UPDATE archive_submission_events" in str(statement)
    assert "submission_id=:submission_id" in str(statement)
    assert statement.compile().params["submission_id"] is None
    assert sorted(statement.compile().params["submission_id_1"]) == [17, 23]


@pytest.mark.asyncio
async def test_detach_archive_submission_events_skips_empty_set() -> None:
    db = SimpleNamespace(execute=AsyncMock())

    detached = await detach_archive_submission_events(db, set())

    assert detached == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_permanent_delete_group_lock_plan_rebuilds_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = SimpleNamespace(id=7, course_id=3)
    submission = SimpleNamespace(
        id=11,
        created_archive_id=7,
        requester_id=13,
        owner_id=13,
    )
    group = ArchiveSubmissionGroup(
        archives=[archive],
        submissions=[submission],
    )
    locked = SimpleNamespace(
        archive=lambda row_id: archive if row_id == archive.id else None,
        submission=lambda row_id: submission if row_id == submission.id else None,
    )
    collect = AsyncMock(side_effect=[group, group, group, group])
    acquire = AsyncMock(return_value=locked)
    revalidate = AsyncMock(
        side_effect=[SimpleNamespace(valid=False), SimpleNamespace(valid=True)]
    )
    monkeypatch.setattr(lifecycle, "collect_archive_submission_group", collect)
    monkeypatch.setattr(
        lifecycle.archive_lifecycle_locks, "acquire_lifecycle_locks", acquire
    )
    monkeypatch.setattr(
        lifecycle.archive_lifecycle_locks,
        "revalidate_lifecycle_membership",
        revalidate,
    )
    db = SimpleNamespace(rollback=AsyncMock())

    result = await acquire_stable_archive_submission_group_locks(
        db,
        archive=archive,
        submission=submission,
    )

    assert result is group
    db.rollback.assert_awaited_once()
    assert acquire.await_count == 2
    plan = acquire.await_args_list[0].args[1]
    assert [
        (resource.resource_class, resource.row_id) for resource in plan.resources
    ] == [
        (LifecycleResourceClass.COURSE, 3),
        (LifecycleResourceClass.ARCHIVE, 7),
        (LifecycleResourceClass.ARCHIVE_SUBMISSION, 11),
    ]
