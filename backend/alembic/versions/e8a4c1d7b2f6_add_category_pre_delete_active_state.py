"""add Category pre-delete active-state snapshot

Revision ID: e8a4c1d7b2f6
Revises: e6a1b3c5d7f9
Create Date: 2026-08-15 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a4c1d7b2f6"
down_revision: str | Sequence[str] | None = "e6a1b3c5d7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "course_category_configs"
SNAPSHOT_COLUMN = "pre_delete_is_active"


def _columns(connection: sa.Connection) -> dict[str, dict[str, object]]:
    return {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }


def _verify_upgrade_source(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "Category state-preservation migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )
    columns = _columns(connection)
    if not {"id", "is_active", "deleted_at"}.issubset(columns):
        raise RuntimeError("Category state-preservation source schema is incomplete")
    if columns["is_active"]["nullable"] is not False:
        raise RuntimeError("Category is_active must be non-null before migration")
    if SNAPSHOT_COLUMN in columns:
        raise RuntimeError("Category pre-delete active-state snapshot already exists")


def _validate_lifecycle_rows(connection: sa.Connection) -> None:
    invalid_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM course_category_configs "
            "WHERE (deleted_at IS NULL AND pre_delete_is_active IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND "
            "(pre_delete_is_active IS NULL OR is_active IS TRUE))"
        )
    )
    if invalid_count:
        raise RuntimeError(
            f"Category lifecycle snapshot validation failed for {invalid_count} row(s)"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Category state-preservation migration requires PostgreSQL")
    _verify_upgrade_source(connection)
    op.add_column(
        TABLE_NAME,
        sa.Column(SNAPSHOT_COLUMN, sa.Boolean(), nullable=True),
    )
    connection.execute(
        sa.text(
            "UPDATE course_category_configs "
            "SET pre_delete_is_active = is_active, is_active = FALSE "
            "WHERE deleted_at IS NOT NULL"
        )
    )
    columns = _columns(connection)
    if (
        SNAPSHOT_COLUMN not in columns
        or columns[SNAPSHOT_COLUMN]["nullable"] is not True
    ):
        raise RuntimeError("Category pre-delete active-state snapshot must be nullable")
    _validate_lifecycle_rows(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Category state-preservation migration requires PostgreSQL")
    columns = _columns(connection)
    if SNAPSHOT_COLUMN not in columns:
        raise RuntimeError("Category pre-delete active-state snapshot is missing")
    _validate_lifecycle_rows(connection)
    connection.execute(
        sa.text(
            "UPDATE course_category_configs "
            "SET is_active = pre_delete_is_active "
            "WHERE deleted_at IS NOT NULL"
        )
    )
    op.drop_column(TABLE_NAME, SNAPSHOT_COLUMN)
