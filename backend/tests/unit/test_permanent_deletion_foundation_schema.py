from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.db.migration_safety import metadata_for_revision
from app.db.schema_manifests import HEAD_SCHEMA_REVISION
from app.db.schema_manifests.registry import PREVIOUS_HEAD_SCHEMA_REVISION
from app.models.models import (
    PermanentDeletionIdentityScheme,
    PermanentDeletionObject,
    PermanentDeletionObjectState,
    PermanentDeletionOperation,
    PermanentDeletionStatus,
    PermanentDeletionTarget,
    SubmissionStatus,
)

NEW_HEAD = "a5f7c9d2e4b6"
PREVIOUS_HEAD = "f6b8d2c4a9e1"


def _constraint_names(table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
        and constraint.name is not None
    }


def test_permanent_deletion_state_namespace_is_independent_and_sealed() -> None:
    assert tuple(status.value for status in PermanentDeletionStatus) == (
        "ACCEPTED",
        "PROCESSING",
        "VERIFICATION_REQUIRED",
        "RETRYABLE_FAILED",
        "MANUAL_REVIEW",
        "COMPLETED",
    )
    assert "PENDING" not in PermanentDeletionStatus.__members__
    assert PermanentDeletionStatus is not SubmissionStatus
    assert PermanentDeletionOperation.model_fields["status"].default == (
        PermanentDeletionStatus.ACCEPTED
    )


def test_exact_storage_identity_and_object_state_are_explicit() -> None:
    assert tuple(scheme.value for scheme in PermanentDeletionIdentityScheme) == (
        "MINIO_VERSION_ID_V1",
    )
    assert tuple(state.value for state in PermanentDeletionObjectState) == (
        "CAPTURED",
        "DELETE_IN_PROGRESS",
        "VERIFICATION_REQUIRED",
        "RETRYABLE_FAILED",
        "MANUAL_REVIEW",
        "VERIFIED_ABSENT",
    )
    assert PermanentDeletionObject.model_fields["version_id"].is_required()
    assert PermanentDeletionObject.model_fields["identity_scheme"].default == (
        PermanentDeletionIdentityScheme.MINIO_VERSION_ID_V1
    )


def test_models_define_reservation_recovery_and_retention_constraints() -> None:
    operation_names = _constraint_names(PermanentDeletionOperation.__table__)
    target_names = _constraint_names(PermanentDeletionTarget.__table__)
    object_names = _constraint_names(PermanentDeletionObject.__table__)

    assert {
        "ck_permanent_deletion_operations_attempt_budget",
        "ck_permanent_deletion_operations_retry_window",
        "ck_permanent_deletion_operations_lease_pair",
        "ck_permanent_deletion_operations_completion",
        "ck_permanent_deletion_operations_audit_retention",
        "uq_permanent_deletion_operations_idempotency_key",
    } <= operation_names
    assert {
        "uq_permanent_deletion_targets_operation_entity",
        "uq_permanent_deletion_targets_id_operation",
        "ck_permanent_deletion_targets_membership_pair",
    } <= target_names
    assert {
        "uq_permanent_deletion_objects_exact_identity",
        "ck_permanent_deletion_objects_nonempty_identity",
        "ck_permanent_deletion_objects_verified_absence",
    } <= object_names

    active_reservation = next(
        index
        for index in PermanentDeletionTarget.__table__.indexes
        if index.name == "uq_permanent_deletion_targets_active_reservation"
    )
    assert active_reservation.unique is True
    assert active_reservation.dialect_options["postgresql"]["where"] is not None


def test_schema_manifest_authority_advances_one_head() -> None:
    assert PREVIOUS_HEAD_SCHEMA_REVISION == PREVIOUS_HEAD
    assert HEAD_SCHEMA_REVISION == NEW_HEAD

    previous = metadata_for_revision(PREVIOUS_HEAD)
    head = metadata_for_revision(NEW_HEAD)
    assert previous is not None
    assert head is not None
    assert (
        not {
            "permanent_deletion_operations",
            "permanent_deletion_targets",
            "permanent_deletion_objects",
        }
        & previous.tables.keys()
    )
    assert {
        "permanent_deletion_operations",
        "permanent_deletion_targets",
        "permanent_deletion_objects",
    } <= head.tables.keys()
