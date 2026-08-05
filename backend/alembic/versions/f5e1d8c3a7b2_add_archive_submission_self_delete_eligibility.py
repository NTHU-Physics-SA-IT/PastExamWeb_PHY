"""persist archive submission owner self-delete eligibility

Revision ID: f5e1d8c3a7b2
Revises: a7c3e9f1b5d2
Create Date: 2026-07-30 18:30:00.000000

"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f5e1d8c3a7b2"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMN_NAME = "owner_self_delete_consumed"
USER_LOCK_SQL = "LOCK TABLE users IN SHARE MODE"
SUBMISSION_LOCK_SQL = "LOCK TABLE archive_submissions IN SHARE ROW EXCLUSIVE MODE"

_CLASSIFICATION_CTE = r"""
WITH base AS (
    SELECT
        submission.*,
        (
            submission.requester_id IS NOT NULL
            AND (
                submission.owner_id IS NULL
                OR submission.owner_id = submission.requester_id
            )
        ) AS ownership_valid,
        EXISTS (
            SELECT 1
            FROM users AS actor
            WHERE actor.id = submission.deleted_by_id
        ) AS deleted_actor_exists,
        EXISTS (
            SELECT 1
            FROM users AS actor
            WHERE actor.id = submission.deleted_by_id
              AND actor.is_admin IS TRUE
        ) AS deleted_by_admin,
        (
            submission.status::text IN ('PENDING', 'APPROVED', 'REJECTED')
            AND submission.lifecycle_reason IS NULL
        ) OR (
            submission.status::text = 'TAKEDOWN'
            AND (
                submission.lifecycle_reason IS NULL
                OR submission.lifecycle_reason = 'archive_trashed'
                OR submission.lifecycle_reason = 'course_trashed'
                OR submission.lifecycle_reason ~
                    '^course_trashed\|previous_status='
                    '(pending|approved|rejected|takedown)'
                    '(\|course_id=[1-9][0-9]*)?'
                    '(\|archive_id=[1-9][0-9]*)?$'
            )
        ) AS active_lifecycle_valid
    FROM archive_submissions AS submission
),
flags AS (
    SELECT
        base.*,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_by_id = requester_id
            AND delete_reason = 'user deleted'
            AND lifecycle_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS owner_self_delete,
        (
            ownership_valid
            AND status::text <> 'DELETED'
            AND active_lifecycle_valid
            AND deleted_at IS NULL
            AND deleted_by_id IS NULL
            AND delete_reason IS NULL
            AND restored_at IS NOT NULL
            AND restored_by_id IS NOT NULL
        ) AS active_restored_unknown,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_by_admin
            AND delete_reason = 'admin deleted'
            AND lifecycle_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS historical_admin_delete,
        (
            ownership_valid
            AND status::text <> 'DELETED'
            AND active_lifecycle_valid
            AND deleted_at IS NULL
            AND deleted_by_id IS NULL
            AND delete_reason IS NULL
            AND restored_at IS NULL
            AND restored_by_id IS NULL
        ) AS clean_active,
        (
            ownership_valid
            AND status::text = 'DELETED'
            AND deleted_at IS NOT NULL
            AND deleted_by_id IS NOT NULL
            AND deleted_actor_exists
            AND restored_at IS NULL
            AND restored_by_id IS NULL
            AND delete_reason = 'linked archive permanently deleted'
            AND lifecycle_reason =
                'linked_archive_permanently_deleted'
        ) AS recognized_system_delete
    FROM base
),
top_level AS (
    SELECT
        flags.*,
        (
            owner_self_delete
            OR active_restored_unknown
            OR historical_admin_delete
            OR recognized_system_delete
        ) AS automatic_true,
        clean_active AS automatic_false,
        (
            NOT ownership_valid
            OR (
                (status::text = 'DELETED')
                <> (deleted_at IS NOT NULL)
            )
            OR (
                (restored_at IS NULL)
                <> (restored_by_id IS NULL)
            )
            OR (
                status::text = 'DELETED'
                AND (
                    restored_at IS NOT NULL
                    OR restored_by_id IS NOT NULL
                )
            )
            OR (
                status::text <> 'DELETED'
                AND (
                    deleted_at IS NOT NULL
                    OR deleted_by_id IS NOT NULL
                    OR delete_reason IS NOT NULL
                )
            )
            OR (
                status::text <> 'DELETED'
                AND NOT active_lifecycle_valid
            )
            OR (
                status::text = 'DELETED'
                AND lifecycle_reason IS NOT NULL
                AND NOT (
                    delete_reason = 'linked archive permanently deleted'
                    AND lifecycle_reason =
                        'linked_archive_permanently_deleted'
                )
            )
            OR (
                ownership_valid
                AND status::text = 'DELETED'
                AND deleted_at IS NOT NULL
                AND restored_at IS NULL
                AND restored_by_id IS NULL
                AND NOT owner_self_delete
                AND NOT historical_admin_delete
                AND NOT recognized_system_delete
            )
        ) AS unsupported
    FROM flags
),
classified AS (
    SELECT
        top_level.*,
        (
            automatic_true::integer
            + automatic_false::integer
            + unsupported::integer
        ) AS bucket_memberships
    FROM top_level
)
"""

_SUMMARY_SQL = (
    _CLASSIFICATION_CTE
    + """
SELECT
    count(*)::bigint AS total,
    count(*) FILTER (WHERE automatic_true)::bigint AS automatic_true,
    count(*) FILTER (WHERE automatic_false)::bigint AS automatic_false,
    count(*) FILTER (WHERE unsupported)::bigint AS unsupported,
    count(*) FILTER (WHERE bucket_memberships = 0)::bigint AS unclassified,
    count(*) FILTER (WHERE bucket_memberships > 1)::bigint AS overlap,
    (
        count(*) FILTER (WHERE automatic_true)
        + count(*) FILTER (WHERE automatic_false)
        + count(*) FILTER (WHERE unsupported)
        + count(*) FILTER (WHERE bucket_memberships = 0)
    )::bigint AS bucket_sum
FROM classified
"""
)

_BACKFILL_SQL = (
    _CLASSIFICATION_CTE
    + f"""
UPDATE archive_submissions AS target
SET {COLUMN_NAME} = true
FROM classified
WHERE target.id = classified.id
  AND classified.automatic_true
"""
)

_POSTFLIGHT_SQL = (
    "/* owner_self_delete_eligibility_postflight */\n"
    + _CLASSIFICATION_CTE
    + f"""
SELECT
    count(*)::bigint AS total,
    count(*) FILTER (
        WHERE submission.{COLUMN_NAME} IS NULL
    )::bigint AS null_count,
    count(*) FILTER (
        WHERE submission.{COLUMN_NAME} IS TRUE
    )::bigint AS stored_true,
    count(*) FILTER (
        WHERE submission.{COLUMN_NAME} IS FALSE
    )::bigint AS stored_false,
    count(*) FILTER (
        WHERE classified.automatic_true
    )::bigint AS expected_true,
    count(*) FILTER (
        WHERE classified.automatic_false
    )::bigint AS expected_false,
    count(*) FILTER (
        WHERE submission.{COLUMN_NAME}
            IS DISTINCT FROM classified.automatic_true
    )::bigint AS value_mismatch
FROM classified
JOIN archive_submissions AS submission
  ON submission.id = classified.id
"""
)


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "ArchiveSubmission eligibility migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )

    inspector = sa.inspect(connection)
    required_tables = {"archive_submissions", "users"}
    missing_tables = required_tables - set(inspector.get_table_names())
    if missing_tables:
        raise RuntimeError(
            "ArchiveSubmission eligibility migration source schema is "
            f"missing tables: {sorted(missing_tables)!r}"
        )

    columns = {
        column["name"]: column
        for column in inspector.get_columns("archive_submissions")
    }
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

    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    is_admin = user_columns.get("is_admin")
    if (
        is_admin is None
        or not isinstance(is_admin["type"], sa.Boolean)
        or is_admin["nullable"] is not False
    ):
        mismatches.append("users.is_admin")

    if mismatches:
        raise RuntimeError(
            "ArchiveSubmission eligibility migration source schema does not "
            f"match the reviewed {down_revision} manifest: {mismatches!r}"
        )


def _summary(connection: sa.Connection) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in connection.execute(sa.text(_SUMMARY_SQL))
        .mappings()
        .one()
        .items()
    }


def _assert_supported(summary: dict[str, int]) -> None:
    difference = summary["total"] - summary["bucket_sum"]
    if (
        summary["unsupported"] != 0
        or summary["unclassified"] != 0
        or summary["overlap"] != 0
        or difference != 0
    ):
        raise RuntimeError(
            "ArchiveSubmission eligibility backfill is not deterministic: "
            f"total={summary['total']}, "
            f"automatic_true={summary['automatic_true']}, "
            f"automatic_false={summary['automatic_false']}, "
            f"unsupported={summary['unsupported']}, "
            f"unclassified={summary['unclassified']}, "
            f"overlap={summary['overlap']}, "
            f"difference={difference}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError(
            "ArchiveSubmission eligibility migration requires PostgreSQL"
        )

    _verify_source_schema(connection)

    # Freeze administrator identity first, then submission lifecycle rows.
    # SHARE blocks user-role writes; SHARE ROW EXCLUSIVE blocks submission
    # inserts/updates/deletes while still permitting ordinary readers.
    op.execute(USER_LOCK_SQL)
    op.execute(SUBMISSION_LOCK_SQL)

    before = _summary(connection)
    _assert_supported(before)

    op.add_column(
        "archive_submissions",
        sa.Column(
            COLUMN_NAME,
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    connection.execute(sa.text(_BACKFILL_SQL))

    after = {
        key: int(value)
        for key, value in connection.execute(sa.text(_POSTFLIGHT_SQL))
        .mappings()
        .one()
        .items()
    }
    if (
        after["total"] != before["total"]
        or after["null_count"] != 0
        or after["expected_true"] != before["automatic_true"]
        or after["expected_false"] != before["automatic_false"]
        or after["stored_true"] != before["automatic_true"]
        or after["stored_false"] != before["automatic_false"]
        or after["value_mismatch"] != 0
    ):
        raise RuntimeError(
            "ArchiveSubmission eligibility backfill postflight failed: "
            f"before={before!r}, after={after!r}"
        )


def downgrade() -> None:
    op.drop_column("archive_submissions", COLUMN_NAME)
