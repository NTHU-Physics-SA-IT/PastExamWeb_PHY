"""enforce archive submission archive one to one

Revision ID: 6f3a9c2d8e41
Revises: d8f2a6c1b4e7
Create Date: 2026-08-03 18:00:00.000000

"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6f3a9c2d8e41"
down_revision: Union[str, Sequence[str], None] = "d8f2a6c1b4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "archive_submissions"
COLUMN_NAME = "created_archive_id"
CONSTRAINT_NAME = "uq_archive_submissions_created_archive_id"
SUBMISSION_LOCK_SQL = "LOCK TABLE archive_submissions IN SHARE ROW EXCLUSIVE MODE"

DUPLICATE_SUMMARY_SQL = """
WITH duplicate_groups AS (
    SELECT count(*)::bigint AS group_count
    FROM archive_submissions
    WHERE created_archive_id IS NOT NULL
    GROUP BY created_archive_id
    HAVING count(*) > 1
)
SELECT
    count(*)::bigint AS duplicate_groups,
    COALESCE(sum(group_count), 0)::bigint AS affected_rows,
    COALESCE(max(group_count), 0)::bigint AS max_cardinality
FROM duplicate_groups
"""

DANGLING_SUMMARY_SQL = """
SELECT count(*)::bigint AS dangling_links
FROM archive_submissions AS submission
LEFT JOIN archives AS archive
  ON archive.id = submission.created_archive_id
WHERE submission.created_archive_id IS NOT NULL
  AND archive.id IS NULL
"""


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )

    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names(schema="public"))
    if TABLE_NAME not in table_names or "archives" not in table_names:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration source schema is missing "
            "required tables"
        )

    columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE_NAME, schema="public")
    }
    expected_columns: dict[str, tuple[type[Any], bool]] = {
        "id": (sa.Integer, False),
        COLUMN_NAME: (sa.Integer, True),
    }
    mismatches: list[str] = []
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
            "ArchiveSubmission one-to-one migration source schema does not "
            f"match the reviewed {down_revision} manifest: {mismatches!r}"
        )

    matching_foreign_keys = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys(
            TABLE_NAME,
            schema="public",
        )
        if tuple(foreign_key.get("constrained_columns") or ()) == (COLUMN_NAME,)
    ]
    if len(matching_foreign_keys) != 1:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration source schema has an "
            "unexpected created_archive_id foreign-key shape"
        )
    foreign_key = matching_foreign_keys[0]
    if (
        foreign_key.get("referred_table") != "archives"
        or tuple(foreign_key.get("referred_columns") or ()) != ("id",)
        or (foreign_key.get("options") or {}).get("ondelete") is not None
    ):
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration source schema has an "
            "unexpected created_archive_id foreign-key contract"
        )

    unique_constraints = inspector.get_unique_constraints(
        TABLE_NAME,
        schema="public",
    )
    if any(
        item.get("name") == CONSTRAINT_NAME
        or tuple(item.get("column_names") or ()) == (COLUMN_NAME,)
        for item in unique_constraints
    ):
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration source schema already "
            "contains a created_archive_id unique constraint"
        )

    indexes = inspector.get_indexes(TABLE_NAME, schema="public")
    if any(
        tuple(index.get("column_names") or ()) == (COLUMN_NAME,) for index in indexes
    ):
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration source schema contains "
            "an unexpected created_archive_id index"
        )


def _run_data_preflight(connection: sa.Connection) -> None:
    duplicate_summary = {
        key: int(value)
        for key, value in connection.execute(sa.text(DUPLICATE_SUMMARY_SQL))
        .mappings()
        .one()
        .items()
    }
    if duplicate_summary["duplicate_groups"] != 0:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration blocked by duplicate "
            "created_archive_id relationships: "
            f"duplicate_groups={duplicate_summary['duplicate_groups']}, "
            f"affected_rows={duplicate_summary['affected_rows']}, "
            f"max_cardinality={duplicate_summary['max_cardinality']}"
        )

    dangling_links = int(connection.scalar(sa.text(DANGLING_SUMMARY_SQL)) or 0)
    if dangling_links != 0:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration blocked by dangling "
            f"created_archive_id relationships: dangling_links={dangling_links}"
        )


def _validate_postflight(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    constraints = {
        item["name"]: tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(
            TABLE_NAME,
            schema="public",
        )
    }
    if constraints.get(CONSTRAINT_NAME) != (COLUMN_NAME,):
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration postflight did not find "
            "the exact named unique constraint"
        )

    column = {
        item["name"]: item
        for item in inspector.get_columns(TABLE_NAME, schema="public")
    }[COLUMN_NAME]
    if column["nullable"] is not True:
        raise RuntimeError(
            "ArchiveSubmission one-to-one migration changed "
            "created_archive_id nullability"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("ArchiveSubmission one-to-one migration requires PostgreSQL")

    _verify_source_schema(connection)
    op.execute(SUBMISSION_LOCK_SQL)
    _run_data_preflight(connection)
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        [COLUMN_NAME],
    )
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        type_="unique",
    )
