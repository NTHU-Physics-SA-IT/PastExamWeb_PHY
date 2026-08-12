"""add persisted NTHU student ID

Revision ID: b7e3d9a1c5f2
Revises: 9f1c2a7e4b63
Create Date: 2026-08-11 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7e3d9a1c5f2"
down_revision: Union[str, Sequence[str], None] = "9f1c2a7e4b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "users"
COLUMN_NAME = "student_id"


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "NTHU student ID migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )

    inspector = sa.inspect(connection)
    if TABLE_NAME not in set(inspector.get_table_names(schema="public")):
        raise RuntimeError("NTHU student ID migration source users table is missing")
    columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE_NAME, schema="public")
    }
    if COLUMN_NAME in columns:
        raise RuntimeError(
            "NTHU student ID migration source already contains users.student_id"
        )
    for required_column in ("id", "oauth_provider", "oauth_sub"):
        if required_column not in columns:
            raise RuntimeError(
                "NTHU student ID migration source schema is missing "
                f"users.{required_column}"
            )


def _validate_postflight(connection: sa.Connection) -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns(TABLE_NAME, schema="public")
    }
    student_id = columns.get(COLUMN_NAME)
    if student_id is None:
        raise RuntimeError("NTHU student ID migration did not add users.student_id")
    if (
        not isinstance(student_id["type"], sa.String)
        or student_id["type"].length != 255
    ):
        raise RuntimeError("users.student_id has an unexpected type")
    if student_id["nullable"] is not True:
        raise RuntimeError("users.student_id must remain nullable for local accounts")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NTHU student ID migration requires PostgreSQL")

    _verify_source_schema(connection)
    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, sa.String(length=255), nullable=True),
    )
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_column(TABLE_NAME, COLUMN_NAME)
