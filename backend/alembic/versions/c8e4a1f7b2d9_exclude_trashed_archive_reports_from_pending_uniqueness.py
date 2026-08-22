"""exclude trashed ArchiveReports from active-pending uniqueness

Revision ID: c8e4a1f7b2d9
Revises: c7e4a9b2d6f1
Create Date: 2026-08-22 18:00:00.000000
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8e4a1f7b2d9"
down_revision: str | Sequence[str] | None = "c7e4a9b2d6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "archive_reports"
INDEX_NAME = "uq_archive_reports_pending_reporter_archive"
INDEX_COLUMNS = ("reporter_user_id", "archive_id")
OLD_PREDICATE = "status = 'pending'"
NEW_PREDICATE = "status = 'pending' AND deleted_at IS NULL"

_INDEX_STATE_SQL = sa.text(
    """
    SELECT
        index_state.indisunique,
        array_agg(attribute.attname ORDER BY key_column.ordinality) AS columns,
        pg_get_expr(index_state.indpred, index_state.indrelid) AS predicate
    FROM pg_class AS table_state
    JOIN pg_namespace AS namespace
      ON namespace.oid = table_state.relnamespace
    JOIN pg_index AS index_state
      ON index_state.indrelid = table_state.oid
    JOIN pg_class AS index_relation
      ON index_relation.oid = index_state.indexrelid
    JOIN LATERAL unnest(index_state.indkey)
      WITH ORDINALITY AS key_column(attnum, ordinality)
      ON TRUE
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = table_state.oid
     AND attribute.attnum = key_column.attnum
    WHERE namespace.nspname = 'public'
      AND table_state.relname = :table_name
      AND index_relation.relname = :index_name
    GROUP BY index_state.indisunique, index_state.indpred, index_state.indrelid
    """
)


def _normalized_predicate(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.lower().replace("::text", "")
    return re.sub(r'[\s()"]+', "", normalized)


def _require_ledger(connection: sa.Connection, expected: str) -> None:
    versions = list(
        connection.execute(
            sa.text("SELECT version_num FROM alembic_version ORDER BY version_num")
        ).scalars()
    )
    if versions != [expected]:
        raise RuntimeError(
            f"ArchiveReport uniqueness migration requires {expected}; "
            f"found {versions!r}"
        )


def _require_columns(connection: sa.Connection) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    expected = {
        "reporter_user_id": (sa.Integer, True),
        "archive_id": (sa.Integer, True),
        "status": (sa.String, False),
        "deleted_at": (sa.DateTime, True),
    }
    for name, (column_type, nullable) in expected.items():
        column = columns.get(name)
        if (
            column is None
            or not isinstance(column["type"], column_type)
            or column["nullable"] is not nullable
        ):
            raise RuntimeError(
                f"ArchiveReport uniqueness source column {name!r} is not reviewed"
            )


def _index_state(connection: sa.Connection) -> tuple[bool, tuple[str, ...], str]:
    row = (
        connection.execute(
            _INDEX_STATE_SQL,
            {"table_name": TABLE_NAME, "index_name": INDEX_NAME},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RuntimeError("ArchiveReport pending uniqueness index is missing")
    return (
        bool(row["indisunique"]),
        tuple(row["columns"]),
        _normalized_predicate(row["predicate"]),
    )


def _require_index(connection: sa.Connection, predicate: str) -> None:
    unique, columns, actual_predicate = _index_state(connection)
    if (
        not unique
        or columns != INDEX_COLUMNS
        or actual_predicate != _normalized_predicate(predicate)
    ):
        raise RuntimeError(
            "ArchiveReport pending uniqueness index source schema is not reviewed"
        )


def _duplicate_scope_count(
    connection: sa.Connection,
    *,
    include_trashed: bool,
) -> int:
    deleted_filter = "" if include_trashed else "AND deleted_at IS NULL"
    return int(
        connection.scalar(
            sa.text(
                f"""
                SELECT count(*)
                FROM (
                    SELECT reporter_user_id, archive_id
                    FROM archive_reports
                    WHERE status = 'pending'
                      AND reporter_user_id IS NOT NULL
                      AND archive_id IS NOT NULL
                      {deleted_filter}
                    GROUP BY reporter_user_id, archive_id
                    HAVING count(*) > 1
                ) AS duplicate_scope
                """
            )
        )
        or 0
    )


def _replace_index(predicate: str) -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        list(INDEX_COLUMNS),
        unique=True,
        postgresql_where=sa.text(predicate),
    )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("ArchiveReport uniqueness migration requires PostgreSQL")
    _require_ledger(connection, str(down_revision))
    _require_columns(connection)
    _require_index(connection, OLD_PREDICATE)
    connection.execute(
        sa.text("LOCK TABLE archive_reports IN SHARE ROW EXCLUSIVE MODE")
    )
    duplicate_scopes = _duplicate_scope_count(
        connection,
        include_trashed=False,
    )
    if duplicate_scopes:
        raise RuntimeError(
            "ArchiveReport active pending uniqueness has "
            f"{duplicate_scopes} duplicate scope(s)"
        )
    _replace_index(NEW_PREDICATE)
    _require_index(connection, NEW_PREDICATE)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("ArchiveReport uniqueness migration requires PostgreSQL")
    _require_ledger(connection, revision)
    _require_columns(connection)
    _require_index(connection, NEW_PREDICATE)
    connection.execute(
        sa.text("LOCK TABLE archive_reports IN SHARE ROW EXCLUSIVE MODE")
    )
    duplicate_scopes = _duplicate_scope_count(
        connection,
        include_trashed=True,
    )
    if duplicate_scopes:
        raise RuntimeError(
            "Cannot restore the previous ArchiveReport uniqueness predicate while "
            f"{duplicate_scopes} active/trashed pending scope(s) conflict"
        )
    _replace_index(OLD_PREDICATE)
    _require_index(connection, OLD_PREDICATE)
