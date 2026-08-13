from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from inspect import iscoroutinefunction, signature
from itertools import product

import pytest
from fastapi import HTTPException

from app.models.models import ArchiveSubmissionAdminAction, SubmissionStatus
from app.services.archive_submission_status import (
    ArchiveSubmissionExpectedStateClassification,
    ArchiveSubmissionReviewAction,
    ArchiveSubmissionTransitionClassification,
    available_archive_submission_admin_actions,
    build_submission_status_notification_dedupe_key,
    classify_archive_submission_expected_state,
    classify_archive_submission_review_transition,
    resolve_archive_submission_actual_status,
    resolve_archive_submission_delete_source_status,
)

POLICY_MATRIX = [
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.REJECT,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.TAKEDOWN,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.REPUBLISH,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.PENDING,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.REJECT,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.REPUBLISH,
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.REJECT,
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.REJECTED,
        ArchiveSubmissionReviewAction.REPUBLISH,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.REJECTED,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.REJECT,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.TAKEDOWN,
        ArchiveSubmissionTransitionClassification.NO_OP,
        SubmissionStatus.TAKEDOWN,
    ),
    (
        SubmissionStatus.TAKEDOWN,
        ArchiveSubmissionReviewAction.REPUBLISH,
        ArchiveSubmissionTransitionClassification.TRANSITION,
        SubmissionStatus.APPROVED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.APPROVE,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.REJECT,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.TAKEDOWN,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
    (
        SubmissionStatus.DELETED,
        ArchiveSubmissionReviewAction.REPUBLISH,
        ArchiveSubmissionTransitionClassification.ILLEGAL,
        SubmissionStatus.DELETED,
    ),
]


ADMIN_ACTION_MATRIX = [
    (
        SubmissionStatus.PENDING,
        (
            ArchiveSubmissionAdminAction.APPROVE,
            ArchiveSubmissionAdminAction.REJECT,
            ArchiveSubmissionAdminAction.TAKEDOWN,
            ArchiveSubmissionAdminAction.DELETE,
        ),
    ),
    (
        SubmissionStatus.APPROVED,
        (
            ArchiveSubmissionAdminAction.REJECT,
            ArchiveSubmissionAdminAction.TAKEDOWN,
            ArchiveSubmissionAdminAction.DELETE,
        ),
    ),
    (
        SubmissionStatus.REJECTED,
        (
            ArchiveSubmissionAdminAction.APPROVE,
            ArchiveSubmissionAdminAction.DELETE,
        ),
    ),
    (
        SubmissionStatus.TAKEDOWN,
        (
            ArchiveSubmissionAdminAction.REPUBLISH,
            ArchiveSubmissionAdminAction.DELETE,
        ),
    ),
    (SubmissionStatus.DELETED, ()),
]


@pytest.mark.parametrize(
    ("source_status", "action", "classification", "resulting_status"),
    POLICY_MATRIX,
)
def test_archive_submission_review_policy_covers_canonical_matrix(
    source_status,
    action,
    classification,
    resulting_status,
):
    result = classify_archive_submission_review_transition(source_status, action)

    assert result.action == action
    assert result.source_status == source_status
    assert (
        result.target_status
        == {
            ArchiveSubmissionReviewAction.APPROVE: SubmissionStatus.APPROVED,
            ArchiveSubmissionReviewAction.REJECT: SubmissionStatus.REJECTED,
            ArchiveSubmissionReviewAction.TAKEDOWN: SubmissionStatus.TAKEDOWN,
            ArchiveSubmissionReviewAction.REPUBLISH: SubmissionStatus.APPROVED,
        }[action]
    )
    assert result.classification == classification
    assert result.resulting_status == resulting_status


def test_archive_submission_review_policy_matrix_is_exhaustive_and_balanced():
    combinations = {
        (source_status, action) for source_status, action, _, _ in POLICY_MATRIX
    }
    expected_combinations = set(
        product(SubmissionStatus, ArchiveSubmissionReviewAction)
    )
    classification_counts = Counter(
        classify_archive_submission_review_transition(
            source_status, action
        ).classification
        for source_status, action in expected_combinations
    )

    assert len(POLICY_MATRIX) == 20
    assert len(combinations) == 20
    assert combinations == expected_combinations
    assert classification_counts == {
        ArchiveSubmissionTransitionClassification.TRANSITION: 7,
        ArchiveSubmissionTransitionClassification.NO_OP: 4,
        ArchiveSubmissionTransitionClassification.ILLEGAL: 9,
    }


def test_archive_submission_review_policy_result_is_immutable_and_synchronous():
    result = classify_archive_submission_review_transition(
        SubmissionStatus.PENDING,
        ArchiveSubmissionReviewAction.APPROVE,
    )

    assert not iscoroutinefunction(classify_archive_submission_review_transition)
    assert tuple(
        signature(classify_archive_submission_review_transition).parameters
    ) == (
        "source_status",
        "action",
    )
    with pytest.raises(FrozenInstanceError):
        result.resulting_status = SubmissionStatus.REJECTED


@pytest.mark.parametrize(("status", "expected_actions"), ADMIN_ACTION_MATRIX)
def test_archive_submission_admin_actions_follow_canonical_projection(
    status,
    expected_actions,
):
    actions = available_archive_submission_admin_actions(status)

    assert actions == expected_actions
    assert len(actions) == len(set(actions))


def test_archive_submission_admin_actions_are_pure_and_keep_delete_outside_review_matrix():
    assert not iscoroutinefunction(available_archive_submission_admin_actions)
    assert tuple(signature(available_archive_submission_admin_actions).parameters) == (
        "status",
    )
    assert ArchiveSubmissionAdminAction.DELETE.value not in {
        action.value for action in ArchiveSubmissionReviewAction
    }


@pytest.mark.parametrize("status", list(SubmissionStatus))
def test_archive_submission_actual_status_normalization_preserves_active_status(status):
    assert resolve_archive_submission_actual_status(status, deleted_at=None) == status


@pytest.mark.parametrize(
    "raw_status",
    [
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
        "rejected",
        " takedown ",
    ],
)
def test_archive_submission_actual_status_normalization_prioritizes_deleted_at(
    raw_status,
):
    assert (
        resolve_archive_submission_actual_status(
            raw_status,
            deleted_at=object(),
        )
        == SubmissionStatus.DELETED
    )


def test_archive_submission_actual_status_normalization_rejects_unknown_status():
    assert resolve_archive_submission_actual_status("unknown", deleted_at=None) is None


def test_archive_submission_delete_source_status_rejects_static_corruption(
    caplog,
):
    with pytest.raises(HTTPException) as exc_info:
        resolve_archive_submission_delete_source_status(
            "private-invalid-status",
            operation="unit_test",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Internal Server Error"
    assert "archive_submission_delete_static_invariant" in caplog.text
    assert "operation=unit_test" in caplog.text
    assert "private-invalid-status" not in caplog.text


@pytest.mark.parametrize("status", list(SubmissionStatus))
def test_expected_state_matches_equal_status(status):
    assert (
        classify_archive_submission_expected_state(status, status)
        == ArchiveSubmissionExpectedStateClassification.MATCH
    )


@pytest.mark.parametrize(
    ("expected_status", "actual_status"),
    [
        (SubmissionStatus.PENDING, SubmissionStatus.APPROVED),
        (SubmissionStatus.PENDING, SubmissionStatus.REJECTED),
        (SubmissionStatus.PENDING, SubmissionStatus.TAKEDOWN),
        (SubmissionStatus.APPROVED, SubmissionStatus.REJECTED),
        (SubmissionStatus.REJECTED, SubmissionStatus.APPROVED),
        (SubmissionStatus.TAKEDOWN, SubmissionStatus.APPROVED),
        (SubmissionStatus.APPROVED, SubmissionStatus.DELETED),
    ],
)
def test_expected_state_classifies_different_status_as_stale(
    expected_status,
    actual_status,
):
    assert (
        classify_archive_submission_expected_state(expected_status, actual_status)
        == ArchiveSubmissionExpectedStateClassification.STALE
    )


def test_missing_expected_state_is_not_a_match():
    assert (
        classify_archive_submission_expected_state(None, SubmissionStatus.PENDING)
        == ArchiveSubmissionExpectedStateClassification.MISSING
    )


def test_stale_approve_precedes_same_target_policy_classification():
    precondition = classify_archive_submission_expected_state(
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
    )
    same_target_policy = classify_archive_submission_review_transition(
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.APPROVE,
    )

    assert precondition == ArchiveSubmissionExpectedStateClassification.STALE
    assert (
        same_target_policy.classification
        == ArchiveSubmissionTransitionClassification.NO_OP
    )


def test_stale_reject_precedes_new_legal_transition_classification():
    precondition = classify_archive_submission_expected_state(
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
    )
    latest_state_policy = classify_archive_submission_review_transition(
        SubmissionStatus.APPROVED,
        ArchiveSubmissionReviewAction.REJECT,
    )

    assert precondition == ArchiveSubmissionExpectedStateClassification.STALE
    assert (
        latest_state_policy.classification
        == ArchiveSubmissionTransitionClassification.TRANSITION
    )


def test_status_only_precondition_treats_aba_return_as_match():
    assert (
        classify_archive_submission_expected_state(
            SubmissionStatus.APPROVED,
            SubmissionStatus.APPROVED,
        )
        == ArchiveSubmissionExpectedStateClassification.MATCH
    )


def test_status_notification_key_is_stable_for_same_source_generation():
    generation = datetime(2026, 8, 13, 9, 30, tzinfo=UTC)

    first = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    retry = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert retry == first


def test_status_notification_key_changes_for_new_source_generation():
    first = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=datetime(2026, 8, 13, 9, 30, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    later_cycle = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert later_cycle != first


def test_status_notification_key_separates_target_statuses():
    generation = datetime(2026, 8, 13, 9, 30, tzinfo=UTC)
    approved = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    rejected = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.REJECTED,
        reviewed_at=generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert rejected != approved


def test_status_notification_key_uses_created_at_for_initial_generation():
    created_at = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    first = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=None,
        created_at=created_at,
    )
    retry = build_submission_status_notification_dedupe_key(
        submission_id=42,
        new_status=SubmissionStatus.APPROVED,
        reviewed_at=None,
        created_at=created_at,
    )

    assert retry == first


def test_status_notification_key_is_timezone_normalized_and_safe():
    utc_generation = datetime(2026, 8, 13, 1, 30, tzinfo=UTC)
    taipei_generation = datetime(
        2026,
        8,
        13,
        9,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    utc_key = build_submission_status_notification_dedupe_key(
        submission_id=9_223_372_036_854_775_807,
        new_status=SubmissionStatus.TAKEDOWN,
        reviewed_at=utc_generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    taipei_key = build_submission_status_notification_dedupe_key(
        submission_id=9_223_372_036_854_775_807,
        new_status=SubmissionStatus.TAKEDOWN,
        reviewed_at=taipei_generation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert taipei_key == utc_key
    assert tuple(
        signature(build_submission_status_notification_dedupe_key).parameters
    ) == ("submission_id", "new_status", "reviewed_at", "created_at")
    assert utc_key.startswith("archive_submission_status:v2:")
    assert len(utc_key) <= 160
    assert "private notification copy" not in utc_key
    assert "private course name" not in utc_key
    assert "private object name" not in utc_key
