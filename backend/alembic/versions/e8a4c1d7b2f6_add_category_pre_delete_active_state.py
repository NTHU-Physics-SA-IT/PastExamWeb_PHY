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
MAIN_SIBLING_REVISION = "a9c4e7b2d6f1"
WISH_TABLES = {
    "archive_wishes",
    "archive_wish_hearts",
    "archive_wish_reports",
}


def _columns(connection: sa.Connection) -> dict[str, dict[str, object]]:
    return {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }


def _versions(connection: sa.Connection) -> list[str]:
    return sorted(
        str(version)
        for version in connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalars()
    )


def _require_main_sibling_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    if not all(inspector.has_table(table, schema="public") for table in WISH_TABLES):
        raise RuntimeError("Category migration main-sibling Wish schema is incomplete")

    required_unique_columns = {
        "archive_wishes": {("target_key",)},
        "archive_wish_hearts": {("wish_id", "user_id")},
        "archive_wish_reports": {("wish_id", "reporter_user_id")},
    }
    required_indexes = {
        "archive_wishes": {"ix_archive_wishes_course_id", "ix_archive_wishes_creator_id"},
        "archive_wish_hearts": {
            "ix_archive_wish_hearts_wish_id",
            "ix_archive_wish_hearts_user_id",
        },
        "archive_wish_reports": {
            "ix_archive_wish_reports_wish_id",
            "ix_archive_wish_reports_status",
        },
    }
    for table_name in WISH_TABLES:
        unique_columns = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name, schema="public")
        }
        indexes = {
            item["name"]
            for item in inspector.get_indexes(table_name, schema="public")
        }
        if not required_unique_columns[table_name].issubset(
            unique_columns
        ) or not required_indexes[table_name].issubset(indexes):
            raise RuntimeError(
                "Category migration main-sibling Wish constraints are incomplete"
            )

    for table_name, column_names in {
        "notifications": {"title_en", "body_en"},
        "about_us_entries": {"title_en", "body_en"},
    }.items():
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name, schema="public")
        }
        if not column_names.issubset(columns) or any(
            columns[name]["nullable"] is not True for name in column_names
        ):
            raise RuntimeError(
                "Category migration main-sibling bilingual schema is incomplete"
            )

    submission_columns = {
        column["name"]: column
        for column in inspector.get_columns("archive_submissions", schema="public")
    }
    if (
        "source_wish_id" not in submission_columns
        or submission_columns["source_wish_id"]["nullable"] is not True
    ):
        raise RuntimeError(
            "Category migration main-sibling source-wish column is incomplete"
        )
    matching_fks = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "archive_submissions", schema="public"
        )
        if foreign_key["constrained_columns"] == ["source_wish_id"]
        and foreign_key["referred_table"] == "archive_wishes"
        and foreign_key["referred_columns"] == ["id"]
        and (foreign_key.get("options") or {}).get("ondelete") == "SET NULL"
    ]
    indexes = {
        index["name"]
        for index in inspector.get_indexes("archive_submissions", schema="public")
    }
    if len(matching_fks) != 1 or "ix_archive_submissions_source_wish_id" not in indexes:
        raise RuntimeError(
            "Category migration main-sibling source-wish continuity is incomplete"
        )


def _verify_upgrade_source(connection: sa.Connection) -> None:
    versions = _versions(connection)
    if versions == [MAIN_SIBLING_REVISION]:
        _require_main_sibling_schema(connection)
    elif versions != [down_revision]:
        raise RuntimeError(
            "Category state-preservation migration requires the reviewed "
            f"source revision {down_revision} or exact main sibling "
            f"{MAIN_SIBLING_REVISION}; found {versions!r}"
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
