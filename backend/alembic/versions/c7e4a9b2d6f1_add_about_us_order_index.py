"""add About Us order index

Revision ID: c7e4a9b2d6f1
Revises: f3a7c1e9d5b2
Create Date: 2026-08-22 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e4a9b2d6f1"
down_revision: str | Sequence[str] | None = "f3a7c1e9d5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            f"About Us ordering migration requires reviewed source revision "
            f"{down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    if not inspector.has_table("about_us_entries", schema="public"):
        raise RuntimeError("About Us entries table is missing")
    columns = {column["name"] for column in inspector.get_columns("about_us_entries")}
    if "order_index" in columns:
        raise RuntimeError("About Us order_index already exists")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("About Us ordering migration requires PostgreSQL")
    _verify_source_schema(connection)
    op.add_column(
        "about_us_entries",
        sa.Column("order_index", sa.Integer(), nullable=True),
    )
    connection.execute(
        sa.text("LOCK TABLE about_us_entries IN SHARE ROW EXCLUSIVE MODE")
    )
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        ORDER BY updated_at DESC, id DESC
                    ) - 1 AS order_index
                FROM about_us_entries
            )
            UPDATE about_us_entries AS entry
            SET order_index = ranked.order_index
            FROM ranked
            WHERE entry.id = ranked.id
            """
        )
    )
    missing_count = connection.scalar(
        sa.text("SELECT count(*) FROM about_us_entries WHERE order_index IS NULL")
    )
    if missing_count:
        raise RuntimeError("About Us ordering backfill left null order indexes")
    op.alter_column("about_us_entries", "order_index", nullable=False)
    op.create_index(
        op.f("ix_about_us_entries_order_index"),
        "about_us_entries",
        ["order_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_about_us_entries_order_index"), table_name="about_us_entries"
    )
    op.drop_column("about_us_entries", "order_index")
