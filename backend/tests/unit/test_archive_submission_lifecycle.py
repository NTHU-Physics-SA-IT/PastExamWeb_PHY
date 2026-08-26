from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.services.archive_submission_lifecycle import (
    detach_archive_submission_events,
)


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
