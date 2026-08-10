"""add NTHU OAuth identity uniqueness

Revision ID: 9f1c2a7e4b63
Revises: 6f3a9c2d8e41
Create Date: 2026-08-09 15:00:00.000000

"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9f1c2a7e4b63"
down_revision: Union[str, Sequence[str], None] = "6f3a9c2d8e41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "users"
PROVIDER_COLUMN = "oauth_provider"
SUBJECT_COLUMN = "oauth_sub"
CONSTRAINT_NAME = "uq_users_oauth_provider_sub"
USER_LOCK_SQL = "LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"

DUPLICATE_SUMMARY_SQL = """
WITH duplicate_groups AS (
    SELECT count(*)::bigint AS group_count
    FROM users
    WHERE oauth_provider IS NOT NULL
      AND oauth_sub IS NOT NULL
    GROUP BY oauth_provider, oauth_sub
    HAVING count(*) > 1
)
SELECT
    count(*)::bigint AS duplicate_groups,
    COALESCE(sum(group_count), 0)::bigint AS affected_rows,
    COALESCE(max(group_count), 0)::bigint AS max_cardinality
FROM duplicate_groups
"""


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "NTHU OAuth identity migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )

    inspector = sa.inspect(connection)
    if TABLE_NAME not in set(inspector.get_table_names(schema="public")):
        raise RuntimeError(
            "NTHU OAuth identity migration source users table is missing"
        )

    columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE_NAME, schema="public")
    }
    expected_columns: dict[str, tuple[type[Any], bool]] = {
        "id": (sa.Integer, False),
        PROVIDER_COLUMN: (sa.String, True),
        SUBJECT_COLUMN: (sa.String, True),
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
            "NTHU OAuth identity migration source schema does not match the "
            f"reviewed {down_revision} manifest: {mismatches!r}"
        )

    constraints = inspector.get_unique_constraints(TABLE_NAME, schema="public")
    if any(
        item.get("name") == CONSTRAINT_NAME
        or tuple(item.get("column_names") or ()) == (PROVIDER_COLUMN, SUBJECT_COLUMN)
        for item in constraints
    ):
        raise RuntimeError(
            "NTHU OAuth identity migration source schema already contains "
            "the provider identity constraint"
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
            "NTHU OAuth identity migration blocked by duplicate provider "
            "identities: "
            f"duplicate_groups={duplicate_summary['duplicate_groups']}, "
            f"affected_rows={duplicate_summary['affected_rows']}, "
            f"max_cardinality={duplicate_summary['max_cardinality']}"
        )


def _validate_postflight(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    constraints = {
        item["name"]: tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(TABLE_NAME, schema="public")
    }
    if constraints.get(CONSTRAINT_NAME) != (PROVIDER_COLUMN, SUBJECT_COLUMN):
        raise RuntimeError(
            "NTHU OAuth identity migration postflight did not find the exact "
            "named unique constraint"
        )

    columns = {
        item["name"]: item
        for item in inspector.get_columns(TABLE_NAME, schema="public")
    }
    if (
        columns[PROVIDER_COLUMN]["nullable"] is not True
        or columns[SUBJECT_COLUMN]["nullable"] is not True
    ):
        raise RuntimeError(
            "NTHU OAuth identity migration changed OAuth column nullability"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NTHU OAuth identity migration requires PostgreSQL")

    _verify_source_schema(connection)
    op.execute(USER_LOCK_SQL)
    _run_data_preflight(connection)
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        [PROVIDER_COLUMN, SUBJECT_COLUMN],
    )
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="unique")
