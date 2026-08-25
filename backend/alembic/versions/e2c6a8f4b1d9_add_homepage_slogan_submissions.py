"""add homepage slogan submissions

Revision ID: e2c6a8f4b1d9
Revises: d1f5a9c3e7b2
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2c6a8f4b1d9"
down_revision: str | Sequence[str] | None = "d1f5a9c3e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "homepage_slogan_submissions"


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "Homepage slogan migration requires reviewed source revision "
            f"{down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    if not inspector.has_table("users", schema="public"):
        raise RuntimeError("users table is missing")
    if inspector.has_table(TABLE_NAME, schema="public"):
        raise RuntimeError("homepage_slogan_submissions table already exists")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Homepage slogan migration requires PostgreSQL")
    _verify_source_schema(connection)
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=80), nullable=False),
        sa.Column("submitter_user_id", sa.Integer(), nullable=True),
        sa.Column("submitter_name_snapshot", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "occurrence_level",
            sa.String(length=24),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'enabled', 'disabled')",
            name="ck_homepage_slogan_submissions_status",
        ),
        sa.CheckConstraint(
            "occurrence_level IN "
            "('super_rare', 'rare', 'normal', 'frequent', 'super_frequent')",
            name="ck_homepage_slogan_submissions_occurrence_level",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_homepage_slogan_submissions_reviewer_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitter_user_id"],
            ["users.id"],
            name="fk_homepage_slogan_submissions_submitter_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "created_at",
        "reviewed_at",
        "reviewer_user_id",
        "status",
        "submitter_user_id",
    ):
        op.create_index(
            op.f(f"ix_{TABLE_NAME}_{column_name}"),
            TABLE_NAME,
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_homepage_slogan_submissions_status_created",
        TABLE_NAME,
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table(TABLE_NAME)
