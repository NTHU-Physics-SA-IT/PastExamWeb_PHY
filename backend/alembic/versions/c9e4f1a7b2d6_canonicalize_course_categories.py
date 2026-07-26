"""canonicalize course categories

Revision ID: c9e4f1a7b2d6
Revises: a4c7e9d2f6b1
Create Date: 2026-07-26 19:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.course_categories import (
    CANONICAL_COURSE_CATEGORIES,
    LEGACY_COURSE_CATEGORY_ALIASES,
    normalize_course_category_key,
    normalize_course_category_name,
)


revision: str = "c9e4f1a7b2d6"
down_revision: Union[str, Sequence[str], None] = "a4c7e9d2f6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NORMALIZED_NAME_INDEX = "uq_course_category_configs_normalized_name"
NORMALIZED_KEY_INDEX = "uq_course_category_configs_normalized_key"
NO_LEGACY_KEY_CHECK = "ck_course_category_configs_no_legacy_key"


def _candidate_rows(
    connection: sa.Connection,
    *,
    canonical_key: str,
    canonical_name: str,
) -> list[dict]:
    aliases = [
        alias
        for alias, target in LEGACY_COURSE_CATEGORY_ALIASES.items()
        if target == canonical_key
    ]
    normalized_keys = [canonical_key, *aliases]
    statement = sa.text(
        """
        SELECT id, key, name
        FROM course_category_configs
        WHERE lower(btrim(key)) IN :keys
           OR lower(btrim(name)) = :name
        ORDER BY id
        """
    ).bindparams(sa.bindparam("keys", expanding=True))
    return [
        dict(row)
        for row in connection.execute(
            statement,
            {
                "keys": normalized_keys,
                "name": normalize_course_category_name(canonical_name),
            },
        ).mappings()
    ]


def _update_category_references(
    connection: sa.Connection,
    *,
    source_keys: list[str],
    canonical_key: str,
    canonical_name: str,
    canonical_label: str,
    canonical_icon: str,
) -> None:
    if not source_keys:
        return
    for table_name in ("courses", "course_submissions", "archive_submissions"):
        statement = sa.text(
            f"""
            UPDATE {table_name}
            SET category = :canonical_key
            WHERE lower(btrim(category)) IN :source_keys
            """
        ).bindparams(sa.bindparam("source_keys", expanding=True))
        connection.execute(
            statement,
            {
                "canonical_key": canonical_key,
                "source_keys": source_keys,
            },
        )

    requested_statement = sa.text(
        """
        UPDATE archive_submissions
        SET requested_category_key = :canonical_key,
            requested_category_name = :canonical_name,
            requested_category_label = :canonical_label,
            requested_category_icon = :canonical_icon
        WHERE requested_category_key IS NOT NULL
          AND lower(btrim(requested_category_key)) IN :source_keys
        """
    ).bindparams(sa.bindparam("source_keys", expanding=True))
    connection.execute(
        requested_statement,
        {
            "canonical_key": canonical_key,
            "canonical_name": canonical_name,
            "canonical_label": canonical_label,
            "canonical_icon": canonical_icon,
            "source_keys": source_keys,
        },
    )


def _canonicalize_definition(
    connection: sa.Connection,
    definition,
) -> None:
    rows = _candidate_rows(
        connection,
        canonical_key=definition.key,
        canonical_name=definition.name,
    )
    if rows:
        target = min(
            rows,
            key=lambda row: (
                row["key"] != definition.key,
                normalize_course_category_key(row["key"]) != definition.key,
                row["id"],
            ),
        )
        target_id = target["id"]
    else:
        target_id = connection.execute(
            sa.text(
                """
                INSERT INTO course_category_configs (
                    key, name, label, icon, badge_color, order_index,
                    is_active, created_at, updated_at
                )
                VALUES (
                    :key, :name, :label, :icon, :badge_color, :order_index,
                    true, now(), now()
                )
                RETURNING id
                """
            ),
            {
                "key": definition.key,
                "name": definition.name,
                "label": definition.label,
                "icon": definition.icon,
                "badge_color": definition.badge_color,
                "order_index": definition.order_index,
            },
        ).scalar_one()
        rows = [
            {
                "id": target_id,
                "key": definition.key,
                "name": definition.name,
            }
        ]

    source_keys = sorted(
        {
            normalize_course_category_key(row["key"])
            for row in rows
        }
    )
    _update_category_references(
        connection,
        source_keys=source_keys,
        canonical_key=definition.key,
        canonical_name=definition.name,
        canonical_label=definition.label,
        canonical_icon=definition.icon,
    )

    duplicate_ids = [row["id"] for row in rows if row["id"] != target_id]
    if duplicate_ids:
        connection.execute(
            sa.text(
                "DELETE FROM course_category_configs WHERE id IN :duplicate_ids"
            ).bindparams(sa.bindparam("duplicate_ids", expanding=True)),
            {"duplicate_ids": duplicate_ids},
        )

    connection.execute(
        sa.text(
            """
            UPDATE course_category_configs
            SET key = :key,
                name = :name,
                label = :label,
                icon = :icon,
                badge_color = :badge_color,
                order_index = :order_index,
                is_active = true,
                deleted_at = NULL,
                deleted_by_id = NULL,
                updated_at = now()
            WHERE id = :target_id
              AND (
                key IS DISTINCT FROM :key
                OR name IS DISTINCT FROM :name
                OR label IS DISTINCT FROM :label
                OR icon IS DISTINCT FROM :icon
                OR badge_color IS DISTINCT FROM :badge_color
                OR order_index IS DISTINCT FROM :order_index
                OR is_active IS DISTINCT FROM true
                OR deleted_at IS NOT NULL
                OR deleted_by_id IS NOT NULL
              )
            """
        ),
        {
            "target_id": target_id,
            "key": definition.key,
            "name": definition.name,
            "label": definition.label,
            "icon": definition.icon,
            "badge_color": definition.badge_color,
            "order_index": definition.order_index,
        },
    )


def upgrade() -> None:
    connection = op.get_bind()
    for definition in CANONICAL_COURSE_CATEGORIES:
        _canonicalize_definition(connection, definition)

    remaining_legacy = connection.scalar(
        sa.text(
            """
            SELECT count(*)
            FROM course_category_configs
            WHERE lower(btrim(key)) IN :legacy_keys
            """
        ).bindparams(
            sa.bindparam(
                "legacy_keys",
                value=list(LEGACY_COURSE_CATEGORY_ALIASES),
                expanding=True,
            )
        )
    )
    if remaining_legacy:
        raise RuntimeError("Legacy course category keys remain after migration")

    duplicate_names = connection.execute(
        sa.text(
            """
            SELECT lower(btrim(name))
            FROM course_category_configs
            GROUP BY lower(btrim(name))
            HAVING count(*) > 1
            """
        )
    ).scalars().all()
    if duplicate_names:
        raise RuntimeError(
            "Duplicate normalized course category names remain after migration"
        )

    op.create_index(
        NORMALIZED_NAME_INDEX,
        "course_category_configs",
        [sa.text("lower(btrim(name))")],
        unique=True,
    )
    op.create_index(
        NORMALIZED_KEY_INDEX,
        "course_category_configs",
        [sa.text("lower(btrim(key))")],
        unique=True,
    )
    op.create_check_constraint(
        NO_LEGACY_KEY_CHECK,
        "course_category_configs",
        "lower(btrim(key)) NOT IN "
        "('freshman', 'sophomore', 'junior', 'senior', 'interdisciplinary')",
    )


def downgrade() -> None:
    # Alias consolidation is intentionally irreversible: restoring legacy
    # rows would recreate the duplicate categories this migration removes.
    op.drop_constraint(
        NO_LEGACY_KEY_CHECK,
        "course_category_configs",
        type_="check",
    )
    op.drop_index(
        NORMALIZED_KEY_INDEX,
        table_name="course_category_configs",
    )
    op.drop_index(
        NORMALIZED_NAME_INDEX,
        table_name="course_category_configs",
    )
