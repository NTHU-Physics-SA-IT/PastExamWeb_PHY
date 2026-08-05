from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.services.archive_submission_lifecycle import (
    delete_archive_submission_events,
)


@pytest.mark.asyncio
async def test_delete_archive_submission_events_targets_exact_ids() -> None:
    result = SimpleNamespace(rowcount=2)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    deleted = await delete_archive_submission_events(db, {17, 23})

    assert deleted == 2
    statement = db.execute.await_args.args[0]
    assert "DELETE FROM archive_submission_events" in str(statement)
    assert sorted(statement.compile().params["submission_id_1"]) == [17, 23]


@pytest.mark.asyncio
async def test_delete_archive_submission_events_skips_empty_set() -> None:
    db = SimpleNamespace(execute=AsyncMock())

    deleted = await delete_archive_submission_events(db, set())

    assert deleted == 0
    db.execute.assert_not_awaited()
