"""add bilingual announcement and system report content

Revision ID: f6a1c2d3e4b5
Revises: d4b7e2a9c6f1
Create Date: 2026-08-14 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a1c2d3e4b5"
down_revision: str | Sequence[str] | None = "d4b7e2a9c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CONTENT_COLUMNS = {
    "notifications": {
        "title_en": sa.String(length=150),
        "body_en": sa.Text(),
    },
    "system_issue_reports": {
        "title_en": sa.String(length=100),
        "description_en": sa.Text(),
    },
}


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "Bilingual announcement/report migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    required = {
        "notifications": {"title", "body"},
        "system_issue_reports": {"title", "description"},
    }
    for table_name, required_columns in required.items():
        columns = {
            column["name"]
            for column in inspector.get_columns(table_name, schema="public")
        }
        if not required_columns.issubset(columns):
            raise RuntimeError(f"{table_name} canonical content schema is incomplete")
        if set(CONTENT_COLUMNS[table_name]) & columns:
            raise RuntimeError(f"{table_name} bilingual content fields already exist")


def _validate_postflight(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    for table_name, expected_columns in CONTENT_COLUMNS.items():
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name, schema="public")
        }
        for column_name in expected_columns:
            if column_name not in columns or columns[column_name]["nullable"] is not True:
                raise RuntimeError(f"{table_name}.{column_name} must be nullable")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Bilingual announcement/report migration requires PostgreSQL")
    _verify_source_schema(connection)
    for table_name, columns in CONTENT_COLUMNS.items():
        for column_name, column_type in columns.items():
            op.add_column(
                table_name,
                sa.Column(column_name, column_type, nullable=True),
            )
    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_column("system_issue_reports", "description_en")
    op.drop_column("system_issue_reports", "title_en")
    op.drop_column("notifications", "body_en")
    op.drop_column("notifications", "title_en")
