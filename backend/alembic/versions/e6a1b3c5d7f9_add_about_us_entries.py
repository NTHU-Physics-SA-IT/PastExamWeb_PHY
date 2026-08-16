"""add About Us entries

Revision ID: e6a1b3c5d7f9
Revises: d4b7e2a9c6f1
Create Date: 2026-08-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6a1b3c5d7f9"
down_revision: str | Sequence[str] | None = "d4b7e2a9c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            f"About Us migration requires reviewed source revision {down_revision}; "
            f"found {versions!r}"
        )
    if sa.inspect(connection).has_table("about_us_entries", schema="public"):
        raise RuntimeError("About Us entries table already exists")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("About Us migration requires PostgreSQL")
    _verify_source_schema(connection)
    op.create_table(
        "about_us_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_about_us_entries_updated_at"),
        "about_us_entries",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_about_us_entries_updated_by_id"),
        "about_us_entries",
        ["updated_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_us_entries_updated_by_id"), table_name="about_us_entries")
    op.drop_index(op.f("ix_about_us_entries_updated_at"), table_name="about_us_entries")
    op.drop_table("about_us_entries")
