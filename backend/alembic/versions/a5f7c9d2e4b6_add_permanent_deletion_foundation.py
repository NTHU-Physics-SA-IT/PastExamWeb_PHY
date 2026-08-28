"""add permanent deletion foundation

Revision ID: a5f7c9d2e4b6
Revises: f6b8d2c4a9e1
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a5f7c9d2e4b6"
down_revision: str | Sequence[str] | None = "f6b8d2c4a9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPERATION_TABLE = "permanent_deletion_operations"
TARGET_TABLE = "permanent_deletion_targets"
OBJECT_TABLE = "permanent_deletion_objects"

PERMANENT_DELETION_STATUS = postgresql.ENUM(
    "ACCEPTED",
    "PROCESSING",
    "VERIFICATION_REQUIRED",
    "RETRYABLE_FAILED",
    "MANUAL_REVIEW",
    "COMPLETED",
    name="permanent_deletion_status",
    create_type=False,
)
PERMANENT_DELETION_IDENTITY_SCHEME = postgresql.ENUM(
    "MINIO_VERSION_ID_V1",
    name="permanent_deletion_identity_scheme",
    create_type=False,
)
PERMANENT_DELETION_OBJECT_STATE = postgresql.ENUM(
    "CAPTURED",
    "DELETE_IN_PROGRESS",
    "VERIFICATION_REQUIRED",
    "RETRYABLE_FAILED",
    "MANUAL_REVIEW",
    "VERIFIED_ABSENT",
    name="permanent_deletion_object_state",
    create_type=False,
)


def _ledger(connection: sa.Connection) -> list[str]:
    return list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )


def _verify_upgrade_source(connection: sa.Connection) -> None:
    versions = _ledger(connection)
    if versions != [down_revision]:
        raise RuntimeError(
            "Permanent deletion foundation requires reviewed source revision "
            f"{down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    if not inspector.has_table("users", schema="public"):
        raise RuntimeError("users table is missing")
    unexpected_tables = [
        table_name
        for table_name in (OPERATION_TABLE, TARGET_TABLE, OBJECT_TABLE)
        if inspector.has_table(table_name, schema="public")
    ]
    if unexpected_tables:
        raise RuntimeError(
            f"Permanent deletion foundation tables already exist: {unexpected_tables!r}"
        )
    existing_enum_names = {
        str(row[0])
        for row in connection.execute(
            sa.text(
                "SELECT typname FROM pg_type "
                "JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace "
                "WHERE pg_namespace.nspname = 'public' AND typname IN "
                "('permanent_deletion_status', "
                "'permanent_deletion_identity_scheme', "
                "'permanent_deletion_object_state')"
            )
        )
    }
    if existing_enum_names:
        raise RuntimeError(
            "Permanent deletion foundation enum types already exist: "
            f"{sorted(existing_enum_names)!r}"
        )


def _verify_downgrade_source(connection: sa.Connection) -> None:
    versions = _ledger(connection)
    if versions != [revision]:
        raise RuntimeError(
            "Permanent deletion foundation downgrade requires reviewed source "
            f"revision {revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    missing_tables = [
        table_name
        for table_name in (OPERATION_TABLE, TARGET_TABLE, OBJECT_TABLE)
        if not inspector.has_table(table_name, schema="public")
    ]
    if missing_tables:
        raise RuntimeError(
            "Permanent deletion foundation downgrade found missing tables: "
            f"{missing_tables!r}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Permanent deletion foundation requires PostgreSQL")
    _verify_upgrade_source(connection)

    PERMANENT_DELETION_STATUS.create(connection, checkfirst=False)
    PERMANENT_DELETION_IDENTITY_SCHEME.create(connection, checkfirst=False)
    PERMANENT_DELETION_OBJECT_STATE.create(connection, checkfirst=False)

    op.create_table(
        OPERATION_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("root_entity_type", sa.String(length=64), nullable=False),
        sa.Column("root_entity_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            PERMANENT_DELETION_STATUS,
            server_default=sa.text("'ACCEPTED'"),
            nullable=False,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "automatic_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("retry_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column("audit_purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(root_entity_type) <> '' AND root_entity_id > 0",
            name="ck_permanent_deletion_operations_root_identity",
        ),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_permanent_deletion_operations_idempotency_key",
        ),
        sa.CheckConstraint(
            "automatic_attempt_count BETWEEN 0 AND 10",
            name="ck_permanent_deletion_operations_attempt_budget",
        ),
        sa.CheckConstraint(
            "retry_deadline_at IS NULL OR "
            "(retry_deadline_at >= accepted_at AND "
            "retry_deadline_at <= accepted_at + INTERVAL '24 hours')",
            name="ck_permanent_deletion_operations_retry_window",
        ),
        sa.CheckConstraint(
            "next_attempt_at IS NULL OR "
            "(retry_deadline_at IS NOT NULL AND next_attempt_at <= retry_deadline_at)",
            name="ck_permanent_deletion_operations_next_attempt",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND btrim(lease_token) <> '' "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_permanent_deletion_operations_lease_pair",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status <> 'COMPLETED' AND completed_at IS NULL)",
            name="ck_permanent_deletion_operations_completion",
        ),
        sa.CheckConstraint(
            "(completed_at IS NULL AND audit_purge_after IS NULL) OR "
            "(completed_at IS NOT NULL AND audit_purge_after IS NOT NULL AND "
            "audit_purge_after >= completed_at + INTERVAL '180 days')",
            name="ck_permanent_deletion_operations_audit_retention",
        ),
        sa.CheckConstraint(
            "result_code IS NULL OR btrim(result_code) <> ''",
            name="ck_permanent_deletion_operations_result_code",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_permanent_deletion_operations_requested_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_permanent_deletion_operations_idempotency_key",
        ),
    )
    op.create_index(
        "ix_permanent_deletion_operations_requested_by_user_id",
        OPERATION_TABLE,
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_permanent_deletion_operations_due",
        OPERATION_TABLE,
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_permanent_deletion_operations_lease_expiry",
        OPERATION_TABLE,
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_permanent_deletion_operations_audit_purge",
        OPERATION_TABLE,
        ["audit_purge_after"],
        unique=False,
    )

    op.create_table(
        TARGET_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("target_role", sa.String(length=32), nullable=True),
        sa.Column("membership_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("membership_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reservation_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(entity_type) <> '' AND entity_id > 0",
            name="ck_permanent_deletion_targets_entity_identity",
        ),
        sa.CheckConstraint(
            "target_role IS NULL OR btrim(target_role) <> ''",
            name="ck_permanent_deletion_targets_role",
        ),
        sa.CheckConstraint(
            "(membership_fingerprint IS NULL AND membership_captured_at IS NULL) OR "
            "(membership_fingerprint IS NOT NULL AND "
            "btrim(membership_fingerprint) <> '' AND "
            "membership_captured_at IS NOT NULL)",
            name="ck_permanent_deletion_targets_membership_pair",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            [f"{OPERATION_TABLE}.id"],
            name="fk_permanent_deletion_targets_operation_id_operations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "operation_id",
            name="uq_permanent_deletion_targets_id_operation",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "entity_type",
            "entity_id",
            name="uq_permanent_deletion_targets_operation_entity",
        ),
    )
    op.create_index(
        "ix_permanent_deletion_targets_operation",
        TARGET_TABLE,
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        "uq_permanent_deletion_targets_active_reservation",
        TARGET_TABLE,
        ["entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("reservation_released_at IS NULL"),
    )

    op.create_table(
        OBJECT_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("bucket_name", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column(
            "identity_scheme",
            PERMANENT_DELETION_IDENTITY_SCHEME,
            server_default=sa.text("'MINIO_VERSION_ID_V1'"),
            nullable=False,
        ),
        sa.Column("version_id", sa.String(length=1024), nullable=False),
        sa.Column(
            "state",
            PERMANENT_DELETION_OBJECT_STATE,
            server_default=sa.text("'CAPTURED'"),
            nullable=False,
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "delete_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_delete_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_unknown_outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_absent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(bucket_name) <> '' AND btrim(object_key) <> ''",
            name="ck_permanent_deletion_objects_storage_location",
        ),
        sa.CheckConstraint(
            "version_id IS NOT NULL AND btrim(version_id) <> ''",
            name="ck_permanent_deletion_objects_nonempty_identity",
        ),
        sa.CheckConstraint(
            "delete_attempt_count BETWEEN 0 AND 10",
            name="ck_permanent_deletion_objects_attempt_budget",
        ),
        sa.CheckConstraint(
            "result_code IS NULL OR btrim(result_code) <> ''",
            name="ck_permanent_deletion_objects_result_code",
        ),
        sa.CheckConstraint(
            "(state = 'VERIFIED_ABSENT' AND verified_absent_at IS NOT NULL) OR "
            "(state <> 'VERIFIED_ABSENT' AND verified_absent_at IS NULL)",
            name="ck_permanent_deletion_objects_verified_absence",
        ),
        sa.ForeignKeyConstraint(
            ["target_id", "operation_id"],
            [f"{TARGET_TABLE}.id", f"{TARGET_TABLE}.operation_id"],
            name="fk_permanent_deletion_objects_target_operation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "bucket_name",
            "object_key",
            "identity_scheme",
            "version_id",
            name="uq_permanent_deletion_objects_exact_identity",
        ),
    )
    op.create_index(
        "ix_permanent_deletion_objects_operation_state",
        OBJECT_TABLE,
        ["operation_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_permanent_deletion_objects_target",
        OBJECT_TABLE,
        ["target_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Permanent deletion foundation requires PostgreSQL")
    _verify_downgrade_source(connection)
    row_counts = connection.execute(
        sa.text(
            f"SELECT "
            f"(SELECT count(*) FROM {OPERATION_TABLE}) AS operations, "
            f"(SELECT count(*) FROM {TARGET_TABLE}) AS targets, "
            f"(SELECT count(*) FROM {OBJECT_TABLE}) AS objects"
        )
    ).one()
    if any(int(count) for count in row_counts):
        raise RuntimeError(
            "Cannot downgrade permanent deletion foundation while operation or "
            "recovery data exists"
        )

    op.drop_table(OBJECT_TABLE)
    op.drop_table(TARGET_TABLE)
    op.drop_table(OPERATION_TABLE)
    PERMANENT_DELETION_OBJECT_STATE.drop(connection, checkfirst=False)
    PERMANENT_DELETION_IDENTITY_SCHEME.drop(connection, checkfirst=False)
    PERMANENT_DELETION_STATUS.drop(connection, checkfirst=False)
