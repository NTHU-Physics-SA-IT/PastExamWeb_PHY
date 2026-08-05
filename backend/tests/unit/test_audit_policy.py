from __future__ import annotations

import pytest

from app.db.audit.policy import (
    CompletionLayer,
    Evidence,
    EvidenceStatus,
    MilestoneKind,
    TaskBoundary,
    TaskKind,
    layer_is_green,
    milestone_is_merge_ready,
    required_layers,
    validate_task_boundary,
)


def _passed(name: str) -> Evidence:
    return Evidence(name=name, required=True, status=EvidenceStatus.PASSED)


def test_schema_changing_milestones_require_all_four_completion_layers() -> None:
    assert required_layers(MilestoneKind.SCHEMA_CHANGE) == frozenset(
        {
            CompletionLayer.REPOSITORY,
            CompletionLayer.ENVIRONMENT,
            CompletionLayer.HUMAN,
            CompletionLayer.MERGE,
        }
    )
    assert required_layers(MilestoneKind.MIGRATION_AUDIT_TOOLING) == frozenset(
        {
            CompletionLayer.REPOSITORY,
            CompletionLayer.ENVIRONMENT,
            CompletionLayer.MERGE,
        }
    )


@pytest.mark.parametrize(
    "status",
    [
        EvidenceStatus.FAILED,
        EvidenceStatus.SKIPPED,
        EvidenceStatus.UNAVAILABLE,
        EvidenceStatus.NOT_APPLICABLE,
    ],
)
def test_required_evidence_cannot_be_replaced(status: EvidenceStatus) -> None:
    assert (
        layer_is_green(
            [
                _passed("exact-sha-ci"),
                Evidence(name="persistent-local", required=True, status=status),
            ]
        )
        is False
    )


def test_backend_unhealthy_cannot_be_merge_ready() -> None:
    layers = {
        CompletionLayer.REPOSITORY: [_passed("branch-ci")],
        CompletionLayer.ENVIRONMENT: [_passed("local-rehearsal")],
        CompletionLayer.HUMAN: [_passed("manual-verification")],
        CompletionLayer.MERGE: [_passed("merge-ci")],
    }

    assert (
        milestone_is_merge_ready(
            MilestoneKind.SCHEMA_CHANGE,
            layers,
            backend_healthy=False,
        )
        is False
    )


@pytest.mark.parametrize(
    "boundary",
    [
        TaskBoundary(
            task_kind=TaskKind.REPOSITORY_CODE,
            repository_modified=True,
            data_mutated=True,
            containers_mutated=False,
        ),
        TaskBoundary(
            task_kind=TaskKind.DATA_REMEDIATION,
            repository_modified=True,
            data_mutated=True,
            containers_mutated=False,
        ),
        TaskBoundary(
            task_kind=TaskKind.OPERATIONS,
            repository_modified=True,
            data_mutated=False,
            containers_mutated=True,
        ),
    ],
)
def test_code_data_and_operations_boundaries_cannot_be_mixed(
    boundary: TaskBoundary,
) -> None:
    with pytest.raises(ValueError, match="task boundary"):
        validate_task_boundary(boundary)
