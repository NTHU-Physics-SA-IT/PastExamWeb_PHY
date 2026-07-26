"""align models and category indexes

Revision ID: e3b7c1d9f5a2
Revises: c9e4f1a7b2d6
Create Date: 2026-07-26 23:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e3b7c1d9f5a2"
down_revision: Union[str, Sequence[str], None] = "c9e4f1a7b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY_INDEXES = (
    ("ix_courses_category", "courses"),
    ("ix_course_submissions_category", "course_submissions"),
    ("ix_archive_submissions_category", "archive_submissions"),
)


def upgrade() -> None:
    for index_name, table_name in CATEGORY_INDEXES:
        op.create_index(index_name, table_name, ["category"], unique=False)

    # b6f1e2d9a4c7 converted every category column to varchar. The former enum
    # has no remaining dependants and is not part of the application contract.
    op.execute("DROP TYPE IF EXISTS coursecategory")


def downgrade() -> None:
    # Recreate only the structural contract expected by c9e4f1a7b2d6. This
    # does not recreate any retired legacy category rows.
    course_category = sa.Enum(
        "FRESHMAN",
        "SOPHOMORE",
        "JUNIOR",
        "SENIOR",
        "GRADUATE",
        "INTERDISCIPLINARY",
        "GENERAL",
        name="coursecategory",
    )
    course_category.create(op.get_bind(), checkfirst=True)

    for index_name, table_name in reversed(CATEGORY_INDEXES):
        op.drop_index(index_name, table_name=table_name)
