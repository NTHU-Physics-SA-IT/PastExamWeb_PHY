from __future__ import annotations

import pytest

from app.db.migration_safety import _normalize_predicate


@pytest.mark.parametrize(
    "equivalent",
    [
        "CAST(previous_status AS TEXT) <> 'DELETED'",
        "cast(previous_status as text) <> 'deleted'",
        "previous_status::text <> 'DELETED'::text",
        "(previous_status)::text <> 'DELETED'::text",
        "((CAST(previous_status AS TEXT) <> 'DELETED'))",
        "CAST(\"previous_status\" AS TEXT) <> 'DELETED'",
        "  CAST( previous_status AS TEXT )   <>   'DELETED'  ",
    ],
)
def test_equivalent_postgresql_text_casts_share_one_predicate(
    equivalent: str,
) -> None:
    expected = _normalize_predicate("previous_status <> 'DELETED'")

    assert _normalize_predicate(equivalent) == expected


@pytest.mark.parametrize(
    ("expected", "drifted"),
    [
        (
            "previous_status IS NULL OR previous_status <> 'DELETED'",
            "previous_status IS NULL OR status <> 'DELETED'",
        ),
        (
            "previous_status IS NULL OR previous_status <> 'DELETED'",
            "previous_status IS NULL OR previous_status = 'DELETED'",
        ),
        (
            "previous_status IS NULL OR previous_status <> 'DELETED'",
            "previous_status IS NULL OR previous_status <> 'APPROVED'",
        ),
        (
            "previous_status IS NULL OR previous_status <> 'DELETED'",
            "previous_status IS NULL AND previous_status <> 'DELETED'",
        ),
        (
            "deleted_at IS NOT NULL OR status = 'DELETED' OR previous_status IS NULL",
            "deleted_at IS NOT NULL OR status = 'DELETED'",
        ),
        (
            "deleted_at IS NOT NULL OR status = 'DELETED' OR previous_status IS NULL",
            "deleted_at IS NOT NULL AND status = 'DELETED' OR previous_status IS NULL",
        ),
        (
            "previous_status <> 'DELETED'",
            "previous_status <> CAST('DELETED' AS TEXT)",
        ),
    ],
)
def test_predicate_normalization_preserves_real_schema_drift(
    expected: str,
    drifted: str,
) -> None:
    assert _normalize_predicate(expected) != _normalize_predicate(drifted)
