"""add bilingual managed content and persisted wish pool

Revision ID: a9c4e7b2d6f1
Revises: e6a1b3c5d7f9
Create Date: 2026-08-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9c4e7b2d6f1"
down_revision: str | Sequence[str] | None = "e6a1b3c5d7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            f"Wish Pool migration requires reviewed source revision {down_revision}; "
            f"found {versions!r}"
        )
    inspector = sa.inspect(connection)
    unexpected = {
        table
        for table in ("archive_wishes", "archive_wish_hearts", "archive_wish_reports")
        if inspector.has_table(table, schema="public")
    }
    if unexpected:
        raise RuntimeError(f"Wish Pool tables already exist: {sorted(unexpected)!r}")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Wish Pool migration requires PostgreSQL")
    _verify_source_schema(connection)

    op.add_column("notifications", sa.Column("title_en", sa.String(150), nullable=True))
    op.add_column("notifications", sa.Column("body_en", sa.Text(), nullable=True))
    op.add_column(
        "about_us_entries", sa.Column("title_en", sa.String(150), nullable=True)
    )
    op.add_column("about_us_entries", sa.Column("body_en", sa.Text(), nullable=True))

    op.create_table(
        "archive_wishes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("target_key", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column(
            "archive_type",
            postgresql.ENUM(
                "QUIZ",
                "MIDTERM",
                "FINAL",
                "OTHER",
                name="archivetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("professor", sa.String(200), nullable=False),
        sa.Column("requested_course_name", sa.String(), nullable=True),
        sa.Column("requested_course_name_en", sa.String(), nullable=True),
        sa.Column("requested_category_key", sa.String(), nullable=True),
        sa.Column("requested_category_name", sa.String(), nullable=True),
        sa.Column("requested_category_name_en", sa.String(), nullable=True),
        sa.Column("requested_category_label", sa.String(), nullable=True),
        sa.Column("requested_category_label_en", sa.String(), nullable=True),
        sa.Column("requested_category_icon", sa.String(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_key", name="uq_archive_wishes_target_key"),
    )
    op.create_index("ix_archive_wishes_course_id", "archive_wishes", ["course_id"])
    op.create_index("ix_archive_wishes_category", "archive_wishes", ["category"])
    op.create_index(
        "ix_archive_wishes_academic_year", "archive_wishes", ["academic_year"]
    )
    op.create_index(
        "ix_archive_wishes_archive_type", "archive_wishes", ["archive_type"]
    )
    op.create_index("ix_archive_wishes_professor", "archive_wishes", ["professor"])
    op.create_index("ix_archive_wishes_creator_id", "archive_wishes", ["creator_id"])
    op.create_index("ix_archive_wishes_created_at", "archive_wishes", ["created_at"])
    op.create_index(
        "ix_archive_wishes_created_id", "archive_wishes", ["created_at", "id"]
    )

    op.create_table(
        "archive_wish_hearts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wish_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wish_id"], ["archive_wishes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "wish_id", "user_id", name="uq_archive_wish_hearts_wish_user"
        ),
    )
    op.create_index(
        "ix_archive_wish_hearts_wish_id", "archive_wish_hearts", ["wish_id"]
    )
    op.create_index(
        "ix_archive_wish_hearts_user_id", "archive_wish_hearts", ["user_id"]
    )
    op.create_index(
        "ix_archive_wish_hearts_wish_created",
        "archive_wish_hearts",
        ["wish_id", "created_at"],
    )

    op.create_table(
        "archive_wish_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wish_id", sa.Integer(), nullable=True),
        sa.Column("reporter_user_id", sa.Integer(), nullable=True),
        sa.Column("wish_title_snapshot", sa.String(150), nullable=False),
        sa.Column("target_summary_snapshot", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("custom_message", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(30), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
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
            "status IN ('pending', 'upheld', 'dismissed')",
            name="ck_archive_wish_reports_status",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["wish_id"], ["archive_wishes.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "wish_id", "reporter_user_id", name="uq_archive_wish_reports_wish_reporter"
        ),
    )
    for column in (
        "wish_id",
        "reporter_user_id",
        "reason",
        "status",
        "reviewed_by",
        "created_at",
    ):
        op.create_index(
            f"ix_archive_wish_reports_{column}", "archive_wish_reports", [column]
        )
    op.create_index(
        "ix_archive_wish_reports_status_created",
        "archive_wish_reports",
        ["status", "created_at"],
    )

    op.add_column(
        "archive_submissions", sa.Column("source_wish_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_archive_submissions_source_wish_id_archive_wishes",
        "archive_submissions",
        "archive_wishes",
        ["source_wish_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_archive_submissions_source_wish_id",
        "archive_submissions",
        ["source_wish_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archive_submissions_source_wish_id", table_name="archive_submissions"
    )
    op.drop_constraint(
        "fk_archive_submissions_source_wish_id_archive_wishes",
        "archive_submissions",
        type_="foreignkey",
    )
    op.drop_column("archive_submissions", "source_wish_id")
    op.drop_table("archive_wish_reports")
    op.drop_table("archive_wish_hearts")
    op.drop_table("archive_wishes")
    op.drop_column("about_us_entries", "body_en")
    op.drop_column("about_us_entries", "title_en")
    op.drop_column("notifications", "body_en")
    op.drop_column("notifications", "title_en")
