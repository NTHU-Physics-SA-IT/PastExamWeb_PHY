"""add bilingual archive submission snapshot fields

Revision ID: d4b7e2a9c6f1
Revises: c2a8e4f6b9d1
Create Date: 2026-08-13 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4b7e2a9c6f1"
down_revision: Union[str, Sequence[str], None] = "c2a8e4f6b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SNAPSHOT_COLUMNS = (
    "requested_course_name_en",
    "requested_category_name_en",
    "requested_category_label_en",
)


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "Bilingual submission snapshot migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )
    columns = {
        column["name"]
        for column in sa.inspect(connection).get_columns(
            "archive_submissions", schema="public"
        )
    }
    required = {
        "requested_course_name",
        "requested_category_name",
        "requested_category_label",
    }
    if not required.issubset(columns):
        raise RuntimeError("ArchiveSubmission snapshot source schema is incomplete")
    if set(SNAPSHOT_COLUMNS) & columns:
        raise RuntimeError("Bilingual ArchiveSubmission snapshot fields already exist")


def _validate_postflight(connection: sa.Connection) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(
            "archive_submissions", schema="public"
        )
    }
    for name in SNAPSHOT_COLUMNS:
        if name not in columns or columns[name]["nullable"] is not True:
            raise RuntimeError(f"ArchiveSubmission snapshot column {name} must be nullable")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Bilingual submission snapshot migration requires PostgreSQL")
    _verify_source_schema(connection)
    op.add_column(
        "archive_submissions",
        sa.Column("requested_course_name_en", sa.String(), nullable=True),
    )
    op.add_column(
        "archive_submissions",
        sa.Column("requested_category_name_en", sa.String(), nullable=True),
    )
    op.add_column(
        "archive_submissions",
        sa.Column("requested_category_label_en", sa.String(), nullable=True),
    )
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_column("archive_submissions", "requested_category_label_en")
    op.drop_column("archive_submissions", "requested_category_name_en")
    op.drop_column("archive_submissions", "requested_course_name_en")
