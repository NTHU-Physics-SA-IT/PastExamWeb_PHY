"""Executable governance rules for milestone and task boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class CompletionLayer(StrEnum):
    REPOSITORY = "repository"
    ENVIRONMENT = "environment"
    HUMAN = "human"
    MERGE = "merge"


class EvidenceStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class MilestoneKind(StrEnum):
    SCHEMA_CHANGE = "schema_change"
    MIGRATION_AUDIT_TOOLING = "migration_audit_tooling"
    APPLICATION_BEHAVIOR = "application_behavior"
    LOCALIZED_NON_SCHEMA = "localized_non_schema"


class TaskKind(StrEnum):
    REPOSITORY_CODE = "repository_code"
    DATA_REMEDIATION = "data_remediation"
    OPERATIONS = "operations"


@dataclass(frozen=True)
class Evidence:
    name: str
    required: bool
    status: EvidenceStatus


@dataclass(frozen=True)
class TaskBoundary:
    task_kind: TaskKind
    repository_modified: bool
    data_mutated: bool
    containers_mutated: bool


_REQUIRED_LAYERS = {
    MilestoneKind.SCHEMA_CHANGE: frozenset(CompletionLayer),
    MilestoneKind.MIGRATION_AUDIT_TOOLING: frozenset(
        {
            CompletionLayer.REPOSITORY,
            CompletionLayer.ENVIRONMENT,
            CompletionLayer.MERGE,
        }
    ),
    MilestoneKind.APPLICATION_BEHAVIOR: frozenset(
        {
            CompletionLayer.REPOSITORY,
            CompletionLayer.HUMAN,
            CompletionLayer.MERGE,
        }
    ),
    MilestoneKind.LOCALIZED_NON_SCHEMA: frozenset(
        {
            CompletionLayer.REPOSITORY,
            CompletionLayer.MERGE,
        }
    ),
}


def required_layers(kind: MilestoneKind) -> frozenset[CompletionLayer]:
    return _REQUIRED_LAYERS[kind]


def layer_is_green(evidence: Sequence[Evidence]) -> bool:
    required = [item for item in evidence if item.required]
    return bool(required) and all(
        item.status is EvidenceStatus.PASSED for item in required
    )


def milestone_is_merge_ready(
    kind: MilestoneKind,
    layers: Mapping[CompletionLayer, Sequence[Evidence]],
    *,
    backend_healthy: bool,
) -> bool:
    if not backend_healthy and CompletionLayer.ENVIRONMENT in required_layers(kind):
        return False
    return all(layer_is_green(layers.get(layer, ())) for layer in required_layers(kind))


def validate_task_boundary(boundary: TaskBoundary) -> None:
    valid = {
        TaskKind.REPOSITORY_CODE: (
            boundary.repository_modified
            and not boundary.data_mutated
            and not boundary.containers_mutated
        ),
        TaskKind.DATA_REMEDIATION: (
            not boundary.repository_modified
            and boundary.data_mutated
            and not boundary.containers_mutated
        ),
        TaskKind.OPERATIONS: (
            not boundary.repository_modified
            and not boundary.data_mutated
            and boundary.containers_mutated
        ),
    }
    if not valid[boundary.task_kind]:
        raise ValueError("task boundary mixes repository, data, or operations work")
