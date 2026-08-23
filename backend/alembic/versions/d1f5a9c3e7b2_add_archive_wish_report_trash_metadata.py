"""add ArchiveWishReport trash metadata

Revision ID: d1f5a9c3e7b2
Revises: c8e4a1f7b2d9
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1f5a9c3e7b2"
down_revision: str | Sequence[str] | None = "c8e4a1f7b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "archive_wish_reports"


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "ArchiveWishReport trash migration requires reviewed source revision "
            f"{down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    if not inspector.has_table(TABLE_NAME, schema="public"):
        raise RuntimeError("archive_wish_reports table is missing")
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    unexpected = {"deleted_at", "deleted_by_id"} & columns
    if unexpected:
        raise RuntimeError(
            "ArchiveWishReport trash columns already exist: "
            f"{sorted(unexpected)!r}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("ArchiveWishReport trash migration requires PostgreSQL")
    _verify_source_schema(connection)
    op.add_column(
        TABLE_NAME,
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_archive_wish_reports_deleted_at"),
        TABLE_NAME,
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_archive_wish_reports_deleted_by_id"),
        TABLE_NAME,
        ["deleted_by_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_archive_wish_reports_deleted_by_id_users",
        TABLE_NAME,
        "users",
        ["deleted_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_archive_wish_reports_deleted_by_id_users",
        TABLE_NAME,
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_archive_wish_reports_deleted_by_id"), table_name=TABLE_NAME
    )
    op.drop_index(op.f("ix_archive_wish_reports_deleted_at"), table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "deleted_by_id")
    op.drop_column(TABLE_NAME, "deleted_at")
