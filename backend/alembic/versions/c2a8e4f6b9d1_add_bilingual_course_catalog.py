"""add bilingual course catalog fields

Revision ID: c2a8e4f6b9d1
Revises: b7e3d9a1c5f2
Create Date: 2026-08-13 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c2a8e4f6b9d1"
down_revision: Union[str, Sequence[str], None] = "b7e3d9a1c5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CATEGORY_TRANSLATIONS = (
    ("fundamental", "Foundation Courses", "Foundation"),
    ("required", "Required Major Courses", "Required"),
    ("optional", "Major Electives", "Elective"),
    ("experience", "Laboratory Courses", "Laboratory"),
    ("graduate", "Graduate Courses", "Graduate"),
    ("math-department", "Mathematics Courses", "Mathematics"),
)

COURSE_TRANSLATIONS = (
    ("fundamental", "普通化學(一)", "General Chemistry (I)"),
    ("fundamental", "普通化學(二)", "General Chemistry (II)"),
    ("fundamental", "普通物理(一)", "General Physics (I)"),
    ("fundamental", "普通物理(二)", "General Physics (II)"),
    ("fundamental", "微積分(一)", "Calculus (I)"),
    ("fundamental", "微積分(二)", "Calculus (II)"),
    ("fundamental", "應用數學(一)", "Applied Mathematics (I)"),
    ("fundamental", "應用數學(二)", "Applied Mathematics (II)"),
    ("required", "電磁學(一)", "Electromagnetism (I)"),
    ("required", "電磁學(二)", "Electromagnetism (II)"),
    ("required", "理論力學(一)", "Theoretical Mechanics (I)"),
    ("required", "理論力學(二)", "Theoretical Mechanics (II)"),
    ("required", "量子物理(一)", "Quantum Physics (I)"),
    ("required", "量子物理(二)", "Quantum Physics (II)"),
    ("required", "熱統計物理(一)", "Thermal and Statistical Physics (I)"),
    ("required", "熱統計物理(二)", "Thermal and Statistical Physics (II)"),
    ("required", "應用電子學(一)", "Applied Electronics (I)"),
    ("required", "應用電子學(二)", "Applied Electronics (II)"),
    ("required", "光學(一)", "Optics (I)"),
    ("required", "光學(二)", "Optics (II)"),
    ("required", "光電物理專論", "Introduction to Optoelectronics"),
    ("experience", "普通化學實驗(一)", "General Chemistry Laboratory (I)"),
    ("experience", "普通化學實驗(二)", "General Chemistry Laboratory (II)"),
    ("experience", "普通物理實驗(一)", "General Physics Laboratory (I)"),
    ("experience", "普通物理實驗(二)", "General Physics Laboratory (II)"),
    ("experience", "物理實驗技術", "Experimental Technique in Physics"),
    ("experience", "實驗物理", "Experimental Physics"),
    ("experience", "應用電子學實驗", "Applied Electronics Lab."),
    ("experience", "近代物理實驗", "Modern Physics Lab."),
    ("experience", "光學實驗", "Optics Laboratory"),
    ("optional", "基礎天文觀測", "Fundamentals of Observational Astronomy"),
    ("optional", "黑洞天文導論", "Introduction to Black Hole Astrophysics"),
    ("optional", "基本粒子物理導論", "Intro. Elementary Particle Physics"),
    ("optional", "相對論導論(一)", "Introduction to Relativity (I)"),
    ("optional", "相對論導論(二)", "Introduction to Relativity (II)"),
    ("optional", "普通天文學(一)", "General Astronomy (I)"),
    ("optional", "普通天文學(二)", "General Astronomy (II)"),
    ("optional", "計算物理概論", "Computation for Physics"),
    ("optional", "數值分析", "Numerical Analysis"),
    ("optional", "量子資訊導論", "Introduction to Quantum Information"),
    ("optional", "物理數學", "Mathematical Methods for Physicists"),
    ("graduate", "電動力學(一)", "Electrodynamics (I)"),
    ("graduate", "電動力學(二)", "Electrodynamics (II)"),
    ("graduate", "古典力學", "Classical Mechanics"),
    ("graduate", "量子力學(一)", "Quantum Mechanics (I)"),
    ("graduate", "量子力學(二)", "Quantum Mechanics (II)"),
    ("graduate", "統計力學(一)", "Statistical Mechanics (I)"),
    ("graduate", "統計力學(二)", "Statistical Mechanics (II)"),
    ("graduate", "凝態物理", "Condensed Matter Physics"),
    ("graduate", "固態物理導論", "Introduction to Solid-State Physics"),
    ("graduate", "流體力學", "Fluid Dynamics"),
    ("graduate", "半導體物理", "Semiconductor Physics"),
    ("graduate", "量子場論(一)", "Quantum Field Theory (I)"),
    ("graduate", "量子場論(二)", "Quantum Field Theory (II)"),
    ("math-department", "數學導論", "Introduction to Mathematics"),
    ("math-department", "線性代數(一)", "Linear Algebra (I)"),
    ("math-department", "線性代數(二)", "Linear Algebra (II)"),
    ("math-department", "幾何(一)", "Geometry (I)"),
    ("math-department", "幾何(二)", "Geometry (II)"),
    ("math-department", "代數(一)", "Algebra (I)"),
    ("math-department", "代數(二)", "Algebra (II)"),
    ("math-department", "高等微積分(一)", "Advanced Calculus (I)"),
    ("math-department", "高等微積分(二)", "Advanced Calculus (II)"),
    ("math-department", "機率論", "Probability Theory"),
    ("math-department", "統計學", "Statistics"),
    ("math-department", "離散數學", "Discrete Mathematics"),
    ("math-department", "微分方程", "Differential Equations"),
    (
        "math-department",
        "偏微分方程導論",
        "Introduction to Partial Differential Equations",
    ),
    ("math-department", "拓撲學導論", "Introduction to Topology"),
    ("math-department", "高等線性代數", "Advanced Linear Algebra"),
    ("math-department", "微分幾何", "Differential Geometry"),
)


def _verify_source_schema(connection: sa.Connection) -> None:
    versions = list(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [down_revision]:
        raise RuntimeError(
            "Bilingual catalog migration requires the reviewed "
            f"source revision {down_revision}; found {versions!r}"
        )
    inspector = sa.inspect(connection)
    expected = {
        "courses": {"id", "name", "category"},
        "course_category_configs": {"id", "key", "name", "label"},
    }
    for table, required_columns in expected.items():
        columns = {
            column["name"] for column in inspector.get_columns(table, schema="public")
        }
        if not required_columns.issubset(columns):
            raise RuntimeError(
                f"Bilingual catalog migration source {table} is incomplete"
            )
        if {"name_en", "label_en"} & columns:
            raise RuntimeError(f"Bilingual catalog fields already exist on {table}")


def _validate_postflight(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    course_columns = {
        column["name"]: column
        for column in inspector.get_columns("courses", schema="public")
    }
    category_columns = {
        column["name"]: column
        for column in inspector.get_columns("course_category_configs", schema="public")
    }
    for columns, names in (
        (course_columns, ("name_en",)),
        (category_columns, ("name_en", "label_en")),
    ):
        for name in names:
            if name not in columns or columns[name]["nullable"] is not True:
                raise RuntimeError(f"Bilingual catalog column {name} must be nullable")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Bilingual catalog migration requires PostgreSQL")
    _verify_source_schema(connection)

    op.add_column("courses", sa.Column("name_en", sa.String(), nullable=True))
    op.add_column(
        "course_category_configs", sa.Column("name_en", sa.String(), nullable=True)
    )
    op.add_column(
        "course_category_configs", sa.Column("label_en", sa.String(), nullable=True)
    )

    for key, name_en, label_en in CATEGORY_TRANSLATIONS:
        result = connection.execute(
            sa.text(
                "UPDATE course_category_configs "
                "SET name_en = :name_en, label_en = :label_en WHERE key = :key"
            ),
            {"key": key, "name_en": name_en, "label_en": label_en},
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Bilingual catalog backfill expected one canonical category for {key}"
            )
    course_count = connection.scalar(sa.text("SELECT count(*) FROM courses"))
    if course_count:
        for category, name, name_en in COURSE_TRANSLATIONS:
            result = connection.execute(
                sa.text(
                    "UPDATE courses SET name_en = :name_en "
                    "WHERE category = :category AND name = :name"
                ),
                {"category": category, "name": name, "name_en": name_en},
            )
            if result.rowcount < 1:
                raise RuntimeError(
                    "Bilingual catalog backfill is missing canonical course "
                    f"{category}/{name}"
                )

    _validate_postflight(connection)


def downgrade() -> None:
    op.drop_column("course_category_configs", "label_en")
    op.drop_column("course_category_configs", "name_en")
    op.drop_column("courses", "name_en")
