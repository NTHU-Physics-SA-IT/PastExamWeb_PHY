from copy import deepcopy

import pytest

from app.models.models import ArchiveType
from app.services.archive_submission_review_revision import (
    compute_archive_submission_review_revision,
    review_revision_payload,
)


@pytest.fixture
def submission_content():
    return {
        "id": 41,
        "object_name": "archive-submissions/7/a.pdf",
        "subject": "普通物理（上）",
        "category": "freshman",
        "name": "midterm2",
        "academic_year": 11310,
        "archive_type": ArchiveType.MIDTERM,
        "professor": "王老師",
        "has_answers": True,
        "requested_course_name": None,
        "requested_course_name_en": None,
        "requested_category_key": None,
        "requested_category_name": None,
        "requested_category_name_en": None,
        "requested_category_label": None,
        "requested_category_label_en": None,
        "requested_category_icon": None,
        "source_wish_id": 9,
        "created_archive_id": None,
        "requester_id": 7,
        "owner_id": None,
        "status": "pending",
        "review_note": "reviewer-only",
        "reviewed_at": None,
    }


def test_identical_authoritative_content_has_stable_canonical_revision(
    submission_content,
):
    first = compute_archive_submission_review_revision(submission_content)
    reordered = dict(reversed(list(submission_content.items())))

    assert first == compute_archive_submission_review_revision(reordered)
    assert first.startswith("asr-v1:")
    assert len(first) == len("asr-v1:") + 64
    assert review_revision_payload(submission_content)["effective_approval_target"] == {
        "category": "fundamental",
        "course": "\u666e\u901a\u7269\u7406\u4e0a",
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("professor", "李老師"),
        ("academic_year", 11320),
        ("requested_course_name", "量子力學"),
        ("source_wish_id", 10),
    ],
)
def test_moderation_metadata_changes_revision(
    submission_content, field, replacement
):
    changed = deepcopy(submission_content)
    changed[field] = replacement

    assert compute_archive_submission_review_revision(changed) != (
        compute_archive_submission_review_revision(submission_content)
    )


def test_object_name_changes_revision(submission_content):
    changed = deepcopy(submission_content)
    changed["object_name"] = "archive-submissions/7/b.pdf"

    assert compute_archive_submission_review_revision(changed) != (
        compute_archive_submission_review_revision(submission_content)
    )


def test_reviewer_only_fields_do_not_change_revision(submission_content):
    changed = deepcopy(submission_content)
    changed.update(
        review_note="updated reviewer annotation",
        reviewer_id=99,
        reviewed_at="2026-09-04T00:00:00Z",
        status="approved",
    )

    assert compute_archive_submission_review_revision(changed) == (
        compute_archive_submission_review_revision(submission_content)
    )
