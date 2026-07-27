"""canonicalize course categories

Revision ID: c9e4f1a7b2d6
Revises: a4c7e9d2f6b1
Create Date: 2026-07-26 19:00:00.000000
"""

from __future__ import annotations

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.course_categories import (
    CANONICAL_COURSE_CATEGORY_KEYS,
    DEFAULT_COURSE_CATEGORY_DEFINITIONS,
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
KNOWN_MATH_NAME_TYPO = "跨群數學系"


def _load_category_rows(connection: sa.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            sa.text(
                """
                SELECT id, key, name
                FROM course_category_configs
                ORDER BY id
                """
            )
        ).mappings()
    ]


def _raise_conflict(
    *,
    canonical_key: str,
    rows: list[dict[str, Any]],
    reason: str,
) -> None:
    raise RuntimeError(
        "Course category canonicalization conflict: "
        f"target canonical key={canonical_key!r}; "
        f"candidate row IDs={[row['id'] for row in rows]}; "
        f"candidate keys={[row['key'] for row in rows]}; "
        f"candidate names={[row['name'] for row in rows]}; "
        f"reason={reason}"
    )


def _canonical_target_for_key(normalized_key: str) -> str:
    return LEGACY_COURSE_CATEGORY_ALIASES.get(
        normalized_key,
        normalized_key
        if normalized_key in CANONICAL_COURSE_CATEGORY_KEYS
        else "database-wide uniqueness",
    )


def _validate_normalized_uniqueness(
    rows: list[dict[str, Any]],
) -> None:
    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_key.setdefault(
            normalize_course_category_key(row["key"]), []
        ).append(row)
        rows_by_name.setdefault(
            normalize_course_category_name(row["name"]), []
        ).append(row)

    for normalized_key, duplicates in rows_by_key.items():
        if len(duplicates) > 1:
            _raise_conflict(
                canonical_key=_canonical_target_for_key(normalized_key),
                rows=duplicates,
                reason="multiple rows have the same normalized key",
            )

    default_key_by_name = {
        normalize_course_category_name(definition.name): definition.key
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    }
    for normalized_name, duplicates in rows_by_name.items():
        if len(duplicates) > 1:
            _raise_conflict(
                canonical_key=default_key_by_name.get(
                    normalized_name,
                    "database-wide uniqueness",
                ),
                rows=duplicates,
                reason="multiple rows have the same normalized name",
            )


def _build_canonicalization_plan(
    rows: list[dict[str, Any]],
) -> list[tuple[Any, dict[str, Any] | None]]:
    _validate_normalized_uniqueness(rows)
    plan: list[tuple[Any, dict[str, Any] | None]] = []

    for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS:
        aliases = {
            alias
            for alias, target in LEGACY_COURSE_CATEGORY_ALIASES.items()
            if target == definition.key
        }
        accepted_keys = {definition.key, *aliases}
        candidates = [
            row
            for row in rows
            if normalize_course_category_key(row["key"]) in accepted_keys
        ]
        if len(candidates) > 1:
            _raise_conflict(
                canonical_key=definition.key,
                rows=candidates,
                reason=(
                    "canonical and legacy rows, or multiple source rows, "
                    "exist for one target"
                ),
            )

        candidate = candidates[0] if candidates else None
        if candidate is None:
            name_conflicts = [
                row
                for row in rows
                if normalize_course_category_name(row["name"])
                == normalize_course_category_name(definition.name)
            ]
            if name_conflicts:
                _raise_conflict(
                    canonical_key=definition.key,
                    rows=name_conflicts,
                    reason=(
                        "the default name is already managed under a "
                        "different key"
                    ),
                )
        elif (
            definition.key == "math-department"
            and candidate["name"] == KNOWN_MATH_NAME_TYPO
        ):
            corrected_name_conflicts = [
                row
                for row in rows
                if row["id"] != candidate["id"]
                and normalize_course_category_name(row["name"])
                == normalize_course_category_name(definition.name)
            ]
            if corrected_name_conflicts:
                _raise_conflict(
                    canonical_key=definition.key,
                    rows=[candidate, *corrected_name_conflicts],
                    reason=(
                        "the known typo cannot be corrected because the "
                        "correct name is already managed by another row"
                    ),
                )

        plan.append((definition, candidate))

    return plan


def _update_legacy_references(
    connection: sa.Connection,
    *,
    legacy_keys: list[str],
    canonical_key: str,
) -> None:
    if not legacy_keys:
        return

    parameters = {
        "canonical_key": canonical_key,
        "legacy_keys": legacy_keys,
    }
    for table_name in ("courses", "course_submissions", "archive_submissions"):
        statement = sa.text(
            f"""
            UPDATE {table_name}
            SET category = :canonical_key
            WHERE lower(btrim(category)) IN :legacy_keys
            """
        ).bindparams(sa.bindparam("legacy_keys", expanding=True))
        connection.execute(statement, parameters)

    requested_statement = sa.text(
        """
        UPDATE archive_submissions
        SET requested_category_key = :canonical_key
        WHERE requested_category_key IS NOT NULL
          AND lower(btrim(requested_category_key)) IN :legacy_keys
        """
    ).bindparams(sa.bindparam("legacy_keys", expanding=True))
    connection.execute(requested_statement, parameters)


def _apply_definition(
    connection: sa.Connection,
    *,
    definition: Any,
    candidate: dict[str, Any] | None,
) -> None:
    aliases = sorted(
        alias
        for alias, target in LEGACY_COURSE_CATEGORY_ALIASES.items()
        if target == definition.key
    )

    if candidate is None:
        connection.execute(
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
        )
    else:
        should_correct_typo = (
            definition.key == "math-department"
            and candidate["name"] == KNOWN_MATH_NAME_TYPO
        )
        if should_correct_typo:
            connection.execute(
                sa.text(
                    """
                    UPDATE course_category_configs
                    SET key = :key,
                        name = :name,
                        updated_at = now()
                    WHERE id = :target_id
                    """
                ),
                {
                    "target_id": candidate["id"],
                    "key": definition.key,
                    "name": definition.name,
                },
            )
        elif candidate["key"] != definition.key:
            connection.execute(
                sa.text(
                    """
                    UPDATE course_category_configs
                    SET key = :key
                    WHERE id = :target_id
                    """
                ),
                {
                    "target_id": candidate["id"],
                    "key": definition.key,
                },
            )

    _update_legacy_references(
        connection,
        legacy_keys=aliases,
        canonical_key=definition.key,
    )


def upgrade() -> None:
    connection = op.get_bind()
    rows = _load_category_rows(connection)
    plan = _build_canonicalization_plan(rows)

    for definition, candidate in plan:
        _apply_definition(
            connection,
            definition=definition,
            candidate=candidate,
        )

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
    # rows would recreate ambiguous category identities.
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
