"""Strict input and output schemas for bounded aggregate audits."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditMode(StrEnum):
    ISOLATED_TEST = "isolated-test"
    PERSISTENT_LOCAL = "persistent-local"
    PRODUCTION_AGGREGATE_ONLY = "production-aggregate-only"


class AuditStatus(StrEnum):
    COMPLETE = "complete"
    DATA_BLOCKED = "data_blocked"
    AUDIT_ERROR = "audit_error"
    INCOMPLETE_TRANSPORT = "incomplete_transport"


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str
    audit_version: int = Field(ge=1)
    mode: AuditMode
    expected_ledger: str
    repository_revision: str
    expected_database: str | None = None
    expected_role: str | None = None
    production_authorized: bool = False

    @field_validator("expected_ledger")
    @classmethod
    def validate_revision(cls, value: str) -> str:
        if len(value) != 12 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(
                "expected ledger must be a 12-character lowercase hex revision"
            )
        return value

    @field_validator("repository_revision")
    @classmethod
    def validate_repository_revision(cls, value: str) -> str:
        if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("repository revision must be a 40-character lowercase SHA")
        return value


class ContinuityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only: bool
    identity_ok: bool
    ledger_row_count: int = Field(ge=0)
    actual_ledger: str | None
    ledger_ok: bool
    schema_ok: bool
    enum_count: int = Field(ge=0)
    enum_match: bool


class AggregateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    automatic_true: int = Field(ge=0)
    automatic_false: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    unclassified: int = Field(ge=0)
    overlap: int = Field(ge=0)
    bucket_sum: int = Field(ge=0)
    difference: int


class PreviousStatusAggregateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    active: int = Field(ge=0)
    deleted: int = Field(ge=0)
    previous_status_pending: int = Field(ge=0)
    previous_status_approved: int = Field(ge=0)
    previous_status_rejected: int = Field(ge=0)
    previous_status_takedown: int = Field(ge=0)
    previous_status_null: int = Field(ge=0)
    previous_status_deleted: int = Field(ge=0)
    invalid_previous_status: int = Field(ge=0)
    active_with_previous_status: int = Field(ge=0)
    deleted_with_exact_previous_status: int = Field(ge=0)
    deleted_with_null_previous_status: int = Field(ge=0)
    valid_course_marker: int = Field(ge=0)
    valid_course_marker_with_previous_status: int = Field(ge=0)
    invalid_course_marker: int = Field(ge=0)
    deterministic_owner_delete_candidate: int = Field(ge=0)
    deterministic_backfilled: int = Field(ge=0)
    ambiguous_admin_archive_group: int = Field(ge=0)
    permanent: int = Field(ge=0)
    unknown_deleted_provenance: int = Field(ge=0)
    owner_self_delete_consumed_true: int = Field(ge=0)
    owner_self_delete_consumed_false: int = Field(ge=0)
    shared_created_archive_groups: int = Field(ge=0)
    shared_created_archive_submissions: int = Field(ge=0)
    automatic_true: int = Field(ge=0)
    automatic_false: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    unclassified: int = Field(ge=0)
    overlap: int = Field(ge=0)
    bucket_sum: int = Field(ge=0)
    difference: int


class OneToOneAggregateCounts(PreviousStatusAggregateCounts):
    created_archive_id_null: int = Field(ge=0)
    created_archive_id_non_null: int = Field(ge=0)
    distinct_created_archive_ids: int = Field(ge=0)
    max_created_archive_cardinality: int = Field(ge=0)
    dangling_created_archive_links: int = Field(ge=0)
    course_category_configs_total: int = Field(ge=0)
    users_total: int = Field(ge=0)
    courses_total: int = Field(ge=0)
    archives_total: int = Field(ge=0)
    created_archive_link_checksum: str = Field(pattern=r"^[0-9a-f]{32}$")
    submission_state_checksum: str = Field(pattern=r"^[0-9a-f]{32}$")


class ArchiveReportUniquenessAggregateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    active_pending: int = Field(ge=0)
    trashed_pending: int = Field(ge=0)
    active_pending_duplicate_groups: int = Field(ge=0)
    active_pending_duplicate_rows: int = Field(ge=0)
    active_and_trashed_scopes: int = Field(ge=0)
    candidate_restore_conflict_scopes: int = Field(ge=0)
    detached_reporter_identity: int = Field(ge=0)
    detached_archive_identity: int = Field(ge=0)
    index_contract_mismatch: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    unclassified: int = Field(ge=0)
    overlap: int = Field(ge=0)
    bucket_sum: int = Field(ge=0)
    difference: int


class FlagCombination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flags: list[str] = Field(min_length=1, max_length=16)
    count: int = Field(ge=1)


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    audit_version: int
    mode: AuditMode
    expected_ledger: str
    repository_revision: str
    status: AuditStatus
    error_code: str | None
    continuity: ContinuityResult | None
    aggregates: (
        AggregateCounts
        | PreviousStatusAggregateCounts
        | OneToOneAggregateCounts
        | ArchiveReportUniquenessAggregateCounts
        | None
    )
    combinations: list[FlagCombination] = Field(default_factory=list, max_length=20)
    mutual_exclusivity: bool | None
    conservation: bool | None
    explicit_rollback: bool
    completion_sentinel: bool

    def to_human_summary(self) -> str:
        lines = [
            f"audit={self.audit_id}@{self.audit_version}",
            f"mode={self.mode.value}",
            f"status={self.status.value}",
            f"expected_ledger={self.expected_ledger}",
            f"explicit_rollback={str(self.explicit_rollback).lower()}",
        ]
        if self.continuity is not None:
            lines.append(
                "continuity="
                f"identity:{self.continuity.identity_ok},"
                f"ledger:{self.continuity.ledger_ok},"
                f"schema:{self.continuity.schema_ok},"
                f"enum:{self.continuity.enum_match}"
            )
        if self.aggregates is not None:
            lines.append(
                "aggregates="
                + ",".join(
                    f"{key}:{value}"
                    for key, value in self.aggregates.model_dump().items()
                )
            )
        if self.error_code:
            lines.append(f"error_code={self.error_code}")
        return "\n".join(lines)
