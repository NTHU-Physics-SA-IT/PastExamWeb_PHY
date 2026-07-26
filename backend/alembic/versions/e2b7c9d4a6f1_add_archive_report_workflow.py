"""add archive report workflow

Revision ID: e2b7c9d4a6f1
Revises: a4c7e9d2f6b1
Create Date: 2026-07-26 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2b7c9d4a6f1"
down_revision: Union[str, Sequence[str], None] = "a4c7e9d2f6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "archive_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporter_user_id", sa.Integer(), nullable=False),
        sa.Column("archive_id", sa.Integer(), nullable=True),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("archive_submission_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=60), nullable=False),
        sa.Column("custom_message", sa.Text(), nullable=True),
        sa.Column("archive_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("course_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("academic_year_snapshot", sa.Integer(), nullable=False),
        sa.Column("archive_type_snapshot", sa.String(length=30), nullable=False),
        sa.Column("professor_snapshot", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archive_taken_down",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'upheld', 'dismissed')",
            name="ck_archive_reports_status",
        ),
        sa.ForeignKeyConstraint(
            ["archive_id"], ["archives.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["archive_submission_id"],
            ["archive_submissions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "reporter_user_id",
        "archive_id",
        "course_id",
        "archive_submission_id",
        "reason",
        "status",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    ):
        op.create_index(
            op.f(f"ix_archive_reports_{column}"),
            "archive_reports",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_archive_reports_status_created",
        "archive_reports",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_archive_reports_active_reporter_archive_reason",
        "archive_reports",
        ["reporter_user_id", "archive_id", "reason"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("archive_reports")
