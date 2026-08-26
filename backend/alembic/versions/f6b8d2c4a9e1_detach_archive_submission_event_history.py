"""detach archive submission event history

Revision ID: f6b8d2c4a9e1
Revises: e2c6a8f4b1d9
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6b8d2c4a9e1"
down_revision: str | Sequence[str] | None = "e2c6a8f4b1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "archive_submission_events"
COLUMN_NAME = "submission_id"


def _verify_source_schema(connection: sa.Connection, *, nullable: bool) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    expected = [down_revision if not nullable else revision]
    if versions != expected:
        raise RuntimeError(
            "Archive submission event detachment migration requires reviewed "
            f"source revision {expected[0]}; found {versions!r}"
        )
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    if COLUMN_NAME not in columns or columns[COLUMN_NAME]["nullable"] is not nullable:
        raise RuntimeError(
            "archive_submission_events.submission_id nullability drifted from "
            f"the reviewed source contract nullable={nullable}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Archive submission event detachment requires PostgreSQL")
    _verify_source_schema(connection, nullable=False)
    op.alter_column(
        TABLE_NAME,
        COLUMN_NAME,
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Archive submission event detachment requires PostgreSQL")
    _verify_source_schema(connection, nullable=True)
    detached_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM archive_submission_events WHERE submission_id IS NULL"
        )
    ).scalar_one()
    if detached_count:
        raise RuntimeError(
            "Cannot restore required event links while detached retained-history "
            "rows exist"
        )
    op.alter_column(
        TABLE_NAME,
        COLUMN_NAME,
        existing_type=sa.Integer(),
        nullable=False,
    )
