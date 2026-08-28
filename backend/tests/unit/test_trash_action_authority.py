from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.services import trash
from app.models.models import PermanentDeletionStatus, SubmissionStatus, TrashEntityType


@pytest.mark.parametrize("item_type", list(TrashEntityType))
def test_trash_items_default_to_explicit_available_actions(item_type):
    item = trash._to_trash_item(
        item_type=item_type,
        item_id=1,
        display_name="item",
        deleted_at=datetime.now(UTC),
        deleted_by_id=None,
    )

    assert item.canRestore is True
    assert item.canPermanentDelete is True


def test_trash_action_authority_records_blockers_without_parsing_copy():
    authority = trash._build_trash_action_authority(
        ["display-only dependency text"],
        restore_blocked=True,
        permanent_delete_blocked=True,
    )

    assert authority.dependencies == ("display-only dependency text",)
    assert authority.can_restore is False
    assert authority.can_permanent_delete is False


def test_trash_item_uses_structured_authority_over_legacy_arguments():
    authority = trash._build_trash_action_authority(
        ["relationship"],
        permanent_delete_blocked=True,
    )

    item = trash._to_trash_item(
        item_type=TrashEntityType.COURSE,
        item_id=2,
        display_name="course",
        deleted_at=datetime.now(UTC),
        deleted_by_id=None,
        dependencies=["ignored"],
        can_restore=False,
        can_permanent_delete=True,
        action_authority=authority,
    )

    assert item.dependencies == ["relationship"]
    assert item.canRestore is True
    assert item.canPermanentDelete is False


@pytest.mark.asyncio
async def test_course_trash_temporary_submission_is_not_independently_actionable():
    submission = SimpleNamespace(
        deleted_at=None,
        status=SubmissionStatus.TAKEDOWN,
        lifecycle_reason="course_trashed|previous_status=approved|course_id=7",
    )

    authority = await trash._get_submission_action_authority(
        SimpleNamespace(),
        submission,
    )

    assert authority.can_restore is False
    assert authority.can_permanent_delete is False
    assert authority.dependencies == (
        "阻擋還原：請先還原原課程",
        "隨課程復原：課程復原後回到已通過",
    )


def test_permanent_deletion_projection_separates_operation_from_lifecycle_status():
    accepted_at = datetime(2026, 8, 28, tzinfo=UTC)
    operation = SimpleNamespace(
        id=27,
        root_entity_type=TrashEntityType.ARCHIVE.value,
        root_entity_id=9,
        status=PermanentDeletionStatus.ACCEPTED,
        accepted_at=accepted_at,
        completed_at=None,
        next_attempt_at=accepted_at,
        result_code=None,
    )

    projection = trash._to_permanent_deletion_read(operation, now=accepted_at)

    assert projection.operation_id == 27
    assert projection.status == PermanentDeletionStatus.ACCEPTED
    assert projection.can_retry is True
    assert projection.can_inspect_reason is False
    assert projection.restore_available is False
