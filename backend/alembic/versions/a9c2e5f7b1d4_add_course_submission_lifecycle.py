"""add CourseSubmission lifecycle independence

Revision ID: a9c2e5f7b1d4
Revises: e8a4c1d7b2f6
Create Date: 2026-08-17 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9c2e5f7b1d4"
down_revision: str | Sequence[str] | None = "e8a4c1d7b2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "course_submissions"
CREATED_COURSE_COLUMN = "created_course_id"
DELETED_AT_INDEX = "ix_course_submissions_deleted_at"
PREVIOUS_STATUS_CHECK = "ck_course_submissions_previous_status_not_deleted"
ACTIVE_STATUS_CHECK = "ck_course_submissions_active_previous_status_null"
TABLE_LOCK_SQL = "LOCK TABLE course_submissions IN SHARE ROW EXCLUSIVE MODE"
MAIN_SIBLING_REVISION = "a9c4e7b2d6f1"
WISH_TABLES = {
    "archive_wishes",
    "archive_wish_hearts",
    "archive_wish_reports",
}

SUBMISSION_STATUS_TYPE = postgresql.ENUM(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "DELETED",
    "TAKEDOWN",
    name="submissionstatus",
    create_type=False,
)


def _source_foreign_key(connection: sa.Connection) -> dict[str, object]:
    matching = [
        foreign_key
        for foreign_key in sa.inspect(connection).get_foreign_keys(
            TABLE_NAME, schema="public"
        )
        if foreign_key["constrained_columns"] == [CREATED_COURSE_COLUMN]
        and foreign_key["referred_table"] == "courses"
        and foreign_key["referred_columns"] == ["id"]
    ]
    if len(matching) != 1 or not matching[0].get("name"):
        raise RuntimeError(
            "CourseSubmission lifecycle migration requires exactly one named "
            "created_course_id foreign key to courses.id"
        )
    return matching[0]


def _versions(connection: sa.Connection) -> list[str]:
    return sorted(
        str(version)
        for version in connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalars()
    )


def _require_category_source_schema(connection: sa.Connection) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(
            "course_category_configs", schema="public"
        )
    }
    if (
        "pre_delete_is_active" not in columns
        or columns["pre_delete_is_active"]["nullable"] is not True
    ):
        raise RuntimeError(
            "CourseSubmission lifecycle Category sibling schema is incomplete"
        )


def _require_main_sibling_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    if not all(inspector.has_table(table, schema="public") for table in WISH_TABLES):
        raise RuntimeError(
            "CourseSubmission lifecycle main-sibling Wish schema is incomplete"
        )
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
                "CourseSubmission lifecycle main-sibling Wish constraints are incomplete"
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
                "CourseSubmission lifecycle main-sibling bilingual schema is incomplete"
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
            "CourseSubmission lifecycle main-sibling source-wish schema is incomplete"
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
            "CourseSubmission lifecycle main-sibling source-wish continuity is incomplete"
        )


def _verify_upgrade_source(connection: sa.Connection) -> str:
    versions = _versions(connection)
    expected_sibling_transition = sorted([str(down_revision), MAIN_SIBLING_REVISION])
    if versions == expected_sibling_transition:
        _require_main_sibling_schema(connection)
    elif versions != [down_revision]:
        raise RuntimeError(
            "CourseSubmission lifecycle migration requires the reviewed source "
            f"revision {down_revision} or exact sibling transition "
            f"{expected_sibling_transition!r}; found {versions!r}"
        )
    _require_category_source_schema(connection)
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    required = {
        "id",
        "status",
        CREATED_COURSE_COLUMN,
        "requester_id",
        "created_at",
    }
    if not required.issubset(columns):
        raise RuntimeError("CourseSubmission lifecycle source schema is incomplete")
    new_columns = {
        "previous_status",
        "deleted_at",
        "deleted_by_id",
        "restored_at",
        "restored_by_id",
    }
    if new_columns.intersection(columns):
        raise RuntimeError("CourseSubmission lifecycle columns already exist")
    foreign_key = _source_foreign_key(connection)
    if (foreign_key.get("options") or {}).get("ondelete") is not None:
        raise RuntimeError(
            "CourseSubmission source created_course_id foreign key unexpectedly "
            "declares an ON DELETE action"
        )
    return str(foreign_key["name"])


def _validate_head(connection: sa.Connection) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    expected_nullable = {
        "previous_status",
        "deleted_at",
        "deleted_by_id",
        "restored_at",
        "restored_by_id",
    }
    if any(
        name not in columns or columns[name]["nullable"] is not True
        for name in expected_nullable
    ):
        raise RuntimeError("CourseSubmission lifecycle head columns are incomplete")
    foreign_key = _source_foreign_key(connection)
    if (foreign_key.get("options") or {}).get("ondelete") != "SET NULL":
        raise RuntimeError(
            "CourseSubmission created_course_id foreign key must use ON DELETE SET NULL"
        )
    invalid = connection.scalar(
        sa.text(
            "SELECT count(*) FROM course_submissions "
            "WHERE previous_status::text = 'DELETED' "
            "OR (deleted_at IS NULL AND status::text <> 'DELETED' "
            "AND previous_status IS NOT NULL)"
        )
    )
    if invalid:
        raise RuntimeError(
            f"CourseSubmission lifecycle validation failed for {invalid} row(s)"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("CourseSubmission lifecycle migration requires PostgreSQL")
    source_foreign_key = _verify_upgrade_source(connection)
    op.execute(TABLE_LOCK_SQL)
    op.add_column(
        TABLE_NAME,
        sa.Column("previous_status", SUBMISSION_STATUS_TYPE, nullable=True),
    )
    for column_name, column_type in (
        ("deleted_at", sa.DateTime(timezone=True)),
        ("deleted_by_id", sa.Integer()),
        ("restored_at", sa.DateTime(timezone=True)),
        ("restored_by_id", sa.Integer()),
    ):
        op.add_column(TABLE_NAME, sa.Column(column_name, column_type, nullable=True))
    op.create_index(DELETED_AT_INDEX, TABLE_NAME, ["deleted_at"], unique=False)
    op.create_check_constraint(
        PREVIOUS_STATUS_CHECK,
        TABLE_NAME,
        "previous_status IS NULL OR CAST(previous_status AS TEXT) <> 'DELETED'",
    )
    op.create_check_constraint(
        ACTIVE_STATUS_CHECK,
        TABLE_NAME,
        "deleted_at IS NOT NULL "
        "OR CAST(status AS TEXT) = 'DELETED' "
        "OR previous_status IS NULL",
    )
    op.drop_constraint(source_foreign_key, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        source_foreign_key,
        TABLE_NAME,
        "courses",
        [CREATED_COURSE_COLUMN],
        ["id"],
        ondelete="SET NULL",
    )
    _validate_head(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("CourseSubmission lifecycle migration requires PostgreSQL")
    _validate_head(connection)
    source_foreign_key = str(_source_foreign_key(connection)["name"])
    op.drop_constraint(source_foreign_key, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        source_foreign_key,
        TABLE_NAME,
        "courses",
        [CREATED_COURSE_COLUMN],
        ["id"],
    )
    op.drop_constraint(ACTIVE_STATUS_CHECK, TABLE_NAME, type_="check")
    op.drop_constraint(PREVIOUS_STATUS_CHECK, TABLE_NAME, type_="check")
    op.drop_index(DELETED_AT_INDEX, table_name=TABLE_NAME)
    for column_name in (
        "restored_by_id",
        "restored_at",
        "deleted_by_id",
        "deleted_at",
        "previous_status",
    ):
        op.drop_column(TABLE_NAME, column_name)
