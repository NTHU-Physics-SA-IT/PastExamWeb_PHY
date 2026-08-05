import pytest
from pydantic import ValidationError

from app.models.models import SubmissionDecision, SubmissionStatus


def test_submission_decision_allows_missing_or_null_expected_status_during_staging():
    assert SubmissionDecision().expected_status is None
    assert SubmissionDecision(expected_status=None).expected_status is None


@pytest.mark.parametrize("status", list(SubmissionStatus))
def test_submission_decision_parses_valid_expected_status(status):
    decision = SubmissionDecision(expected_status=status.value)

    assert decision.expected_status == status


def test_submission_decision_rejects_unknown_expected_status():
    with pytest.raises(ValidationError):
        SubmissionDecision(expected_status="unknown")


def test_submission_decision_preserves_note_and_extra_field_behavior():
    decision = SubmissionDecision(
        note="existing note",
        expected_status="pending",
        existing_unknown_field="ignored",
    )

    assert decision.note == "existing note"
    assert decision.expected_status == SubmissionStatus.PENDING
    assert not hasattr(decision, "existing_unknown_field")
