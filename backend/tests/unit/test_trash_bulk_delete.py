from datetime import UTC, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from app.api.services import trash
from app.models.models import TrashEntityType, TrashItem


@pytest.mark.asyncio
async def test_bulk_permanent_delete_commits_successes_and_reports_item_failures(
    monkeypatch,
):
    item_a = TrashItem(
        item_type=TrashEntityType.NOTIFICATION,
        id=101,
        display_name="Item A",
        deleted_at=datetime.now(UTC),
    )
    item_b = TrashItem(
        item_type=TrashEntityType.USER,
        id=202,
        display_name="Item B",
        deleted_at=datetime.now(UTC),
    )
    events = []

    async def permanently_delete(*, item_type, item_id, db, warnings):
        assert db is session
        assert warnings == []
        events.append(("delete", item_type.value, item_id))
        if item_id == item_b.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Item B has blocking dependencies"},
            )
        return {
            "deleted": 1,
            "details": [
                {
                    "type": item_type.value,
                    "id": item_id,
                    "name": item_a.display_name,
                }
            ],
        }

    async def commit():
        events.append(("commit",))

    async def rollback():
        events.append(("rollback",))

    session = SimpleNamespace(
        commit=AsyncMock(side_effect=commit),
        rollback=AsyncMock(side_effect=rollback),
    )
    list_items = AsyncMock(return_value=[item_b, item_a])
    delete_item = AsyncMock(side_effect=permanently_delete)
    admin = SimpleNamespace(is_admin=True)
    monkeypatch.setattr(trash, "list_trash_items", list_items)
    monkeypatch.setattr(trash, "_permanently_delete_trash_item", delete_item)

    result = await trash.bulk_permanently_delete_trash_items(
        item_type=None,
        current_user=admin,
        db=session,
    )

    list_items.assert_awaited_once_with(
        item_type=None,
        current_user=admin,
        db=session,
    )
    assert delete_item.await_count == 2
    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    assert events == [
        ("delete", TrashEntityType.NOTIFICATION.value, item_a.id),
        ("commit",),
        ("delete", TrashEntityType.USER.value, item_b.id),
        ("rollback",),
    ]
    assert result["deleted"] == 1
    assert result["deleted_count"] == 1
    assert result["failed"] == 1
    assert result["failed_count"] == 1
    assert result["details"] == [
        {
            "type": TrashEntityType.NOTIFICATION.value,
            "id": item_a.id,
            "name": item_a.display_name,
        }
    ]
    assert result["failures"] == [
        {
            "type": TrashEntityType.USER.value,
            "id": item_b.id,
            "name": item_b.display_name,
            "reason": "Item B has blocking dependencies",
            "blockingDependencies": [],
        }
    ]
