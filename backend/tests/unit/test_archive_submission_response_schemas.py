from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.models import (
    ArchiveSubmissionActionRead,
    ArchiveSubmissionAdminRead,
    ArchiveSubmissionRead,
)


def _submission_payload():
    return {
        "id": 1,
        "subject": "Response schema course",
        "category": "freshman",
        "name": "final",
        "academic_year": 2026,
        "archive_type": "final",
        "professor": "Response Schema Professor",
        "has_answers": False,
        "status": "approved",
        "requester_id": 1,
        "review_revision": f"asr-v1:{'0' * 64}",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


def test_archive_submission_admin_read_adds_only_admin_capabilities():
    response = ArchiveSubmissionAdminRead.model_validate(
        {
            **_submission_payload(),
            "available_actions": ["reject", "takedown", "delete"],
        }
    )

    payload = response.model_dump(mode="json")
    assert payload["available_actions"] == ["reject", "takedown", "delete"]
    assert "changed" not in payload
    assert "available_actions" not in ArchiveSubmissionRead.model_fields
    assert "changed" not in ArchiveSubmissionRead.model_fields


def test_archive_submission_admin_read_distinguishes_current_archive_from_snapshot():
    response = ArchiveSubmissionAdminRead.model_validate(
        {
            **_submission_payload(),
            "subject": "Historical submitted course",
            "requested_course_name": "Historical requested course",
            "current_archive": {
                "id": 11,
                "course_id": 22,
                "course_name": "Current course",
                "course_name_en": "Current course EN",
                "course_category": "freshman",
                "name": "Current exam",
                "academic_year": 2027,
                "archive_type": "quiz",
                "professor": "Current professor",
                "has_answers": True,
                "is_deleted": False,
                "course_is_deleted": False,
            },
            "available_actions": ["reject", "takedown", "delete"],
        }
    )

    payload = response.model_dump(mode="json")
    assert payload["current_archive"]["course_name"] == "Current course"
    assert payload["subject"] == "Historical submitted course"
    assert payload["requested_course_name"] == "Historical requested course"

    unlinked = ArchiveSubmissionAdminRead.model_validate(
        {
            **_submission_payload(),
            "current_archive": None,
            "available_actions": ["reject", "takedown", "delete"],
        }
    )
    assert unlinked.current_archive is None


def test_archive_submission_action_read_keeps_flat_shape_and_requires_changed():
    response = ArchiveSubmissionActionRead.model_validate(
        {
            **_submission_payload(),
            "available_actions": ["reject", "takedown", "delete"],
            "changed": False,
        }
    )

    payload = response.model_dump(mode="json")
    assert payload["id"] == 1
    assert payload["status"] == "approved"
    assert payload["available_actions"] == ["reject", "takedown", "delete"]
    assert payload["changed"] is False
    assert "submission" not in payload

    with pytest.raises(ValidationError):
        ArchiveSubmissionActionRead.model_validate(
            {
                **_submission_payload(),
                "available_actions": ["reject", "takedown", "delete"],
            }
        )


def test_archive_submission_admin_read_requires_available_actions():
    with pytest.raises(ValidationError):
        ArchiveSubmissionAdminRead.model_validate(_submission_payload())
