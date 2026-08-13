from datetime import UTC, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.services import trash
from app.models.models import TrashEntityType

HARD_DELETE_CASES = (
    (TrashEntityType.COURSE_CATEGORY, "_hard_delete_category"),
    (TrashEntityType.COURSE, "_hard_delete_course"),
    (TrashEntityType.ARCHIVE, "_hard_delete_archive"),
    (TrashEntityType.ARCHIVE_SUBMISSION, "_hard_delete_submission"),
    (TrashEntityType.USER, "_hard_delete_user"),
    (TrashEntityType.NOTIFICATION, None),
    (TrashEntityType.SYSTEM_ISSUE_REPORT, None),
    (TrashEntityType.COMMENT_REPORT, None),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("item_type", "helper_name"), HARD_DELETE_CASES)
async def test_every_materialized_trash_type_dispatches_to_hard_delete(
    monkeypatch, item_type, helper_name
):
    entity = SimpleNamespace(
        id=17,
        deleted_at=datetime.now(UTC),
        name="測試項目",
        title="測試項目",
        subject="測試科目",
        reason="other",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=entity), delete=AsyncMock())

    helper = None
    if helper_name:
        helper = AsyncMock(return_value={"deleted": 1})
        monkeypatch.setattr(trash, helper_name, helper)
    if item_type == TrashEntityType.ARCHIVE:
        monkeypatch.setattr(
            trash,
            "_get_deleted_submission_parent_for_archive",
            AsyncMock(return_value=None),
        )

    result = await trash._permanently_delete_trash_item(
        item_type=item_type,
        item_id=entity.id,
        db=db,
        warnings=[],
    )

    assert result["deleted"] == 1
    if helper is None:
        db.delete.assert_awaited_once_with(entity)
    else:
        helper.assert_awaited_once()


def test_reserved_archive_report_filter_has_no_fake_delete_dispatch():
    materialized_types = {case[0] for case in HARD_DELETE_CASES}

    assert materialized_types == set(TrashEntityType) - {
        TrashEntityType.ARCHIVE_REPORT
    }
