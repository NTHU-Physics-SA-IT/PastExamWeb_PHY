from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException, Response, status

from app.api.services import trash
from app.models.models import (
    PermanentDeletionRead,
    PermanentDeletionStatus,
    TrashEntityType,
    TrashItem,
)


def _projection(
    item_type: TrashEntityType,
    item_id: int,
    operation_id: int,
    operation_status: PermanentDeletionStatus,
) -> PermanentDeletionRead:
    return PermanentDeletionRead(
        operation_id=operation_id,
        root_type=item_type,
        root_id=item_id,
        status=operation_status,
        accepted_at=datetime(2026, 8, 27, 19, 0, tzinfo=UTC),
        completed_at=(
            datetime(2026, 8, 27, 19, 1, tzinfo=UTC)
            if operation_status == PermanentDeletionStatus.COMPLETED
            else None
        ),
        can_retry=operation_status == PermanentDeletionStatus.ACCEPTED,
        restore_available=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("item_type", list(TrashEntityType))
async def test_every_single_item_type_uses_the_canonical_durable_path(
    monkeypatch: pytest.MonkeyPatch,
    item_type: TrashEntityType,
) -> None:
    projection = _projection(
        item_type,
        101,
        operation_id=501,
        operation_status=PermanentDeletionStatus.COMPLETED,
    )
    initiate = AsyncMock(return_value=projection)
    legacy = AsyncMock()
    monkeypatch.setattr(trash, "_initiate_public_permanent_deletion", initiate)
    monkeypatch.setattr(trash, "_permanently_delete_trash_item", legacy)
    response = Response()
    admin = SimpleNamespace(user_id=7, is_admin=True)
    session = SimpleNamespace()

    result = await trash.permanently_delete_trash_item(
        item_type=item_type,
        item_id=101,
        response=response,
        current_user=admin,
        db=session,
    )

    assert result == projection
    assert response.status_code == status.HTTP_200_OK
    initiate.assert_awaited_once_with(
        item_type=item_type,
        item_id=101,
        current_user=admin,
        db=session,
    )
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_rejects_non_admin_before_evaluating_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_items = AsyncMock()
    monkeypatch.setattr(trash, "list_trash_items", list_items)

    with pytest.raises(HTTPException) as error:
        await trash.bulk_permanently_delete_trash_items(
            item_type=None,
            current_user=SimpleNamespace(is_admin=False),
            db=SimpleNamespace(),
        )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    list_items.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_returns_mutually_exclusive_mixed_durable_truth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed_item = TrashItem(
        item_type=TrashEntityType.NOTIFICATION,
        id=101,
        display_name="Completed item",
        deleted_at=datetime.now(UTC),
    )
    pending_item = TrashItem(
        item_type=TrashEntityType.USER,
        id=202,
        display_name="Pending item",
        deleted_at=datetime.now(UTC),
    )
    failed_item = TrashItem(
        item_type=TrashEntityType.COMMENT_REPORT,
        id=303,
        display_name="Failed item",
        deleted_at=datetime.now(UTC),
    )
    completed = _projection(
        completed_item.item_type,
        completed_item.id,
        operation_id=601,
        operation_status=PermanentDeletionStatus.COMPLETED,
    )
    pending = _projection(
        pending_item.item_type,
        pending_item.id,
        operation_id=602,
        operation_status=PermanentDeletionStatus.VERIFICATION_REQUIRED,
    )
    events: list[tuple[str, int]] = []

    async def initiate(*, item_type, item_id, current_user, db):
        assert current_user.is_admin is True
        assert db is session
        events.append((item_type.value, item_id))
        if item_id == completed_item.id:
            return completed
        if item_id == pending_item.id:
            return pending
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "versioning_state_unavailable",
                "message": "永久刪除失敗，請稍後再試",
            },
        )

    session = SimpleNamespace(rollback=AsyncMock())
    monkeypatch.setattr(
        trash,
        "list_trash_items",
        AsyncMock(return_value=[failed_item, pending_item, completed_item]),
    )
    monkeypatch.setattr(
        trash,
        "_initiate_public_permanent_deletion",
        AsyncMock(side_effect=initiate),
    )
    monkeypatch.setattr(
        trash,
        "_proven_covering_permanent_deletion",
        AsyncMock(return_value=None),
    )

    result = await trash.bulk_permanently_delete_trash_items(
        item_type=None,
        current_user=SimpleNamespace(user_id=9, is_admin=True),
        db=session,
    )

    assert result.requested_count == 3
    assert result.completed_count == 1
    assert result.pending_count == 1
    assert result.manual_review_count == 0
    assert result.failed_count == 1
    assert result.skipped_count == 0
    assert [item.outcome.value for item in result.results] == [
        "COMPLETED",
        "PENDING",
        "FAILED",
    ]
    assert result.results[0].operation == completed
    assert result.results[1].operation == pending
    assert result.results[2].operation is None
    assert result.results[2].reason_code == "versioning_state_unavailable"
    assert events == [
        (TrashEntityType.NOTIFICATION.value, completed_item.id),
        (TrashEntityType.USER.value, pending_item.id),
        (TrashEntityType.COMMENT_REPORT.value, failed_item.id),
    ]
    session.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_bulk_reports_manual_review_separately_with_safe_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = TrashItem(
        item_type=TrashEntityType.SYSTEM_ISSUE_REPORT,
        id=404,
        display_name="Manual review item",
        deleted_at=datetime.now(UTC),
    )
    projection = _projection(
        item.item_type,
        item.id,
        operation_id=603,
        operation_status=PermanentDeletionStatus.MANUAL_REVIEW,
    ).model_copy(update={"result_code": "replacement_identity_detected"})
    session = SimpleNamespace(rollback=AsyncMock())
    monkeypatch.setattr(
        trash,
        "list_trash_items",
        AsyncMock(return_value=[item]),
    )
    monkeypatch.setattr(
        trash,
        "_initiate_public_permanent_deletion",
        AsyncMock(return_value=projection),
    )

    result = await trash.bulk_permanently_delete_trash_items(
        item_type=TrashEntityType.SYSTEM_ISSUE_REPORT,
        current_user=SimpleNamespace(user_id=9, is_admin=True),
        db=session,
    )

    assert result.requested_count == 1
    assert result.completed_count == 0
    assert result.pending_count == 0
    assert result.manual_review_count == 1
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.results[0].outcome.value == "MANUAL_REVIEW"
    assert result.results[0].operation == projection
    assert result.results[0].reason_code is None
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_preserves_scope_filter_and_reuses_item_operation_truth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = TrashItem(
        item_type=TrashEntityType.NOTIFICATION,
        id=505,
        display_name="Repeated item",
        deleted_at=datetime.now(UTC),
    )
    projection = _projection(
        item.item_type,
        item.id,
        operation_id=604,
        operation_status=PermanentDeletionStatus.VERIFICATION_REQUIRED,
    )
    list_items = AsyncMock(return_value=[item])
    initiate = AsyncMock(return_value=projection)
    monkeypatch.setattr(trash, "list_trash_items", list_items)
    monkeypatch.setattr(trash, "_initiate_public_permanent_deletion", initiate)
    session = SimpleNamespace(rollback=AsyncMock())
    admin = SimpleNamespace(user_id=9, is_admin=True)

    first = await trash.bulk_permanently_delete_trash_items(
        item_type=TrashEntityType.NOTIFICATION,
        current_user=admin,
        db=session,
    )
    second = await trash.bulk_permanently_delete_trash_items(
        item_type=TrashEntityType.NOTIFICATION,
        current_user=admin,
        db=session,
    )

    assert first.results[0].operation.operation_id == 604
    assert second.results[0].operation.operation_id == 604
    assert first.pending_count == second.pending_count == 1
    assert list_items.await_args_list == [
        call(item_type=TrashEntityType.NOTIFICATION, current_user=admin, db=session),
        call(item_type=TrashEntityType.NOTIFICATION, current_user=admin, db=session),
    ]
    assert initiate.await_count == 2
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_reports_proven_overlapping_root_as_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission_item = TrashItem(
        item_type=TrashEntityType.ARCHIVE_SUBMISSION,
        id=41,
        display_name="Containing submission",
        deleted_at=datetime.now(UTC),
    )
    archive_item = TrashItem(
        item_type=TrashEntityType.ARCHIVE,
        id=42,
        display_name="Covered archive",
        deleted_at=datetime.now(UTC),
    )
    covering = _projection(
        submission_item.item_type,
        submission_item.id,
        operation_id=701,
        operation_status=PermanentDeletionStatus.VERIFICATION_REQUIRED,
    )

    async def initiate(*, item_type, item_id, **_kwargs):
        if item_id == submission_item.id:
            return covering
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "target_reservation_conflict",
                "message": "目前無法接受永久刪除",
            },
        )

    session = SimpleNamespace(rollback=AsyncMock())
    coverage = AsyncMock(return_value=covering)
    monkeypatch.setattr(
        trash,
        "list_trash_items",
        AsyncMock(return_value=[archive_item, submission_item]),
    )
    monkeypatch.setattr(
        trash,
        "_initiate_public_permanent_deletion",
        AsyncMock(side_effect=initiate),
    )
    monkeypatch.setattr(trash, "_proven_covering_permanent_deletion", coverage)

    result = await trash.bulk_permanently_delete_trash_items(
        item_type=None,
        current_user=SimpleNamespace(user_id=9, is_admin=True),
        db=session,
    )

    assert result.requested_count == 2
    assert result.pending_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 0
    assert [item.outcome.value for item in result.results] == ["PENDING", "SKIPPED"]
    assert result.results[1].operation == covering
    assert result.results[1].reason_code == "covered_by_permanent_deletion"
    coverage.assert_awaited_once_with(
        session,
        item_type=TrashEntityType.ARCHIVE,
        item_id=archive_item.id,
        operation_ids=None,
        include_released=False,
    )
