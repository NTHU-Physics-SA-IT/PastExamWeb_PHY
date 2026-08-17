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


def _verify_upgrade_source(connection: sa.Connection) -> str:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "CourseSubmission lifecycle migration requires the reviewed source "
            f"revision {down_revision}; found {versions!r}"
        )
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
