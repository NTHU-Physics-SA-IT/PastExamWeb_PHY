"""persist archive submission previous status

Revision ID: d8f2a6c1b4e7
Revises: f5e1d8c3a7b2
Create Date: 2026-08-03 12:00:00.000000

"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d8f2a6c1b4e7"
down_revision: Union[str, Sequence[str], None] = "f5e1d8c3a7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMN_NAME = "previous_status"
NOT_DELETED_CONSTRAINT = "ck_archive_submissions_previous_status_not_deleted"
ACTIVE_NULL_CONSTRAINT = "ck_archive_submissions_active_previous_status_null"
SUBMISSION_LOCK_SQL = "LOCK TABLE archive_submissions IN SHARE ROW EXCLUSIVE MODE"

SUBMISSION_STATUS_TYPE = postgresql.ENUM(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "DELETED",
    "TAKEDOWN",
    name="submissionstatus",
    create_type=False,
)

OWNER_DELETE_PREDICATE = r"""
submission.requester_id IS NOT NULL
AND (
    submission.owner_id IS NULL
    OR submission.owner_id = submission.requester_id
)
AND submission.status::text = 'DELETED'
AND submission.deleted_at IS NOT NULL
AND submission.deleted_by_id IS NOT NULL
AND submission.deleted_by_id = submission.requester_id
AND submission.delete_reason = 'user deleted'
AND submission.lifecycle_reason IS NULL
AND submission.restored_at IS NULL
AND submission.restored_by_id IS NULL
"""

VALID_COURSE_MARKER_PREDICATE = r"""
submission.status::text = 'TAKEDOWN'
AND submission.deleted_at IS NULL
AND submission.lifecycle_reason ~
    '^course_trashed\|previous_status='
    '(pending|approved|rejected|takedown)'
    '(\|course_id=[1-9][0-9]*)?'
    '(\|archive_id=[1-9][0-9]*)?$'
"""

BACKFILL_SQL = f"""
UPDATE archive_submissions AS submission
SET {COLUMN_NAME} = 'APPROVED'::submissionstatus
WHERE {OWNER_DELETE_PREDICATE}
"""

POSTFLIGHT_SQL = f"""
SELECT
    count(*)::bigint AS total,
    count(*) FILTER (
        WHERE submission.deleted_at IS NULL
          AND submission.status::text <> 'DELETED'
          AND submission.{COLUMN_NAME} IS NOT NULL
    )::bigint AS active_with_previous_status,
    count(*) FILTER (
        WHERE submission.{COLUMN_NAME}::text = 'DELETED'
    )::bigint AS deleted_prior_status,
    count(*) FILTER (
        WHERE ({VALID_COURSE_MARKER_PREDICATE})
          AND submission.{COLUMN_NAME} IS NOT NULL
    )::bigint AS course_marker_with_previous_status,
    count(*) FILTER (
        WHERE submission.lifecycle_reason =
                  'linked_archive_permanently_deleted'
          AND submission.{COLUMN_NAME} IS NOT NULL
    )::bigint AS permanent_with_previous_status,
    count(*) FILTER (
        WHERE ({OWNER_DELETE_PREDICATE})
    )::bigint AS deterministic_owner_delete_candidate,
    count(*) FILTER (
        WHERE ({OWNER_DELETE_PREDICATE})
          AND submission.{COLUMN_NAME}::text = 'APPROVED'
    )::bigint AS deterministic_backfilled,
    count(*) FILTER (
        WHERE NOT ({OWNER_DELETE_PREDICATE})
          AND submission.{COLUMN_NAME} IS NOT NULL
    )::bigint AS non_target_backfilled
FROM archive_submissions AS submission
"""


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "ArchiveSubmission previous-status migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )

    inspector = sa.inspect(connection)
    if "archive_submissions" not in inspector.get_table_names():
        raise RuntimeError(
            "ArchiveSubmission previous-status migration source schema is "
            "missing archive_submissions"
        )

    columns = {
        column["name"]: column
        for column in inspector.get_columns("archive_submissions")
    }
    if COLUMN_NAME in columns:
        raise RuntimeError(
            "ArchiveSubmission previous-status migration source schema already "
            f"contains {COLUMN_NAME}"
        )

    expected_columns: dict[str, tuple[type[Any], bool]] = {
        "id": (sa.Integer, False),
        "requester_id": (sa.Integer, False),
        "owner_id": (sa.Integer, True),
        "status": (sa.Enum, False),
        "deleted_at": (sa.DateTime, True),
        "deleted_by_id": (sa.Integer, True),
        "delete_reason": (sa.Text, True),
        "lifecycle_reason": (sa.String, True),
        "restored_at": (sa.DateTime, True),
        "restored_by_id": (sa.Integer, True),
        "created_archive_id": (sa.Integer, True),
        "owner_self_delete_consumed": (sa.Boolean, False),
    }
    mismatches = []
    for name, (expected_type, expected_nullable) in expected_columns.items():
        column = columns.get(name)
        if column is None:
            mismatches.append(f"{name}:missing")
            continue
        if not isinstance(column["type"], expected_type):
            mismatches.append(f"{name}:type")
        if column["nullable"] is not expected_nullable:
            mismatches.append(f"{name}:nullability")
    if mismatches:
        raise RuntimeError(
            "ArchiveSubmission previous-status migration source schema does not "
            f"match the reviewed {down_revision} manifest: {mismatches!r}"
        )


def _validate_postflight(connection: sa.Connection) -> None:
    summary = {
        key: int(value)
        for key, value in connection.execute(sa.text(POSTFLIGHT_SQL))
        .mappings()
        .one()
        .items()
    }
    if (
        summary["active_with_previous_status"] != 0
        or summary["deleted_prior_status"] != 0
        or summary["course_marker_with_previous_status"] != 0
        or summary["permanent_with_previous_status"] != 0
        or summary["deterministic_backfilled"]
        != summary["deterministic_owner_delete_candidate"]
        or summary["non_target_backfilled"] != 0
    ):
        raise RuntimeError(
            f"ArchiveSubmission previous-status backfill postflight failed: {summary!r}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError(
            "ArchiveSubmission previous-status migration requires PostgreSQL"
        )

    _verify_source_schema(connection)
    op.execute(SUBMISSION_LOCK_SQL)
    op.add_column(
        "archive_submissions",
        sa.Column(
            COLUMN_NAME,
            SUBMISSION_STATUS_TYPE,
            nullable=True,
        ),
    )
    op.create_check_constraint(
        NOT_DELETED_CONSTRAINT,
        "archive_submissions",
        "previous_status IS NULL OR previous_status::text <> 'DELETED'",
    )
    op.create_check_constraint(
        ACTIVE_NULL_CONSTRAINT,
        "archive_submissions",
        "deleted_at IS NOT NULL OR status::text = 'DELETED' OR previous_status IS NULL",
    )
    connection.execute(sa.text(BACKFILL_SQL))
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_constraint(
        ACTIVE_NULL_CONSTRAINT,
        "archive_submissions",
        type_="check",
    )
    op.drop_constraint(
        NOT_DELETED_CONSTRAINT,
        "archive_submissions",
        type_="check",
    )
    op.drop_column("archive_submissions", COLUMN_NAME)
