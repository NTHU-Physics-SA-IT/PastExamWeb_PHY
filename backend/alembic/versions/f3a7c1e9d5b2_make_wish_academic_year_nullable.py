"""make Wish academic year nullable

Revision ID: f3a7c1e9d5b2
Revises: b4d6f8a2c1e3
Create Date: 2026-08-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a7c1e9d5b2"
down_revision: str | Sequence[str] | None = "b4d6f8a2c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "archive_wishes"
COLUMN_NAME = "academic_year"


def _column(connection: sa.Connection) -> dict:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    column = columns.get(COLUMN_NAME)
    if column is None or not isinstance(column["type"], sa.Integer):
        raise RuntimeError("Wish academic year migration source column is missing or invalid")
    return column


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Wish academic year migration requires PostgreSQL")
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            f"Wish academic year migration requires {down_revision}; found {versions!r}"
        )
    source = _column(connection)
    if source["nullable"] is not False or source.get("default") is not None:
        raise RuntimeError("Wish academic year migration source schema is not reviewed")
    op.alter_column(
        TABLE_NAME,
        COLUMN_NAME,
        existing_type=sa.Integer(),
        nullable=True,
    )
    if _column(connection)["nullable"] is not True:
        raise RuntimeError("archive_wishes.academic_year must be nullable after upgrade")


def downgrade() -> None:
    connection = op.get_bind()
    null_count = connection.scalar(
        sa.text("SELECT count(*) FROM archive_wishes WHERE academic_year IS NULL")
    )
    if null_count:
        raise RuntimeError(
            "Cannot downgrade Wish academic year while Any Semester wishes exist"
        )
    op.alter_column(
        TABLE_NAME,
        COLUMN_NAME,
        existing_type=sa.Integer(),
        nullable=False,
    )
