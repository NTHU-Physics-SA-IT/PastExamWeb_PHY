from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.core.config import settings
from app.db.course_categories import (
    CANONICAL_COURSE_CATEGORY_KEYS,
    DEFAULT_COURSE_CATEGORY_BY_KEY,
    DEFAULT_COURSE_CATEGORY_DEFINITIONS,
)
from app.db.migration_safety import alembic_config
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)


PREVIOUS_REVISION = "a4c7e9d2f6b1"


@pytest.fixture()
def migration_engine(monkeypatch: pytest.MonkeyPatch) -> Engine:
    test_url = make_url(os.environ["TEST_DATABASE_URL"])
    runtime_url = alembic_config().get_main_option("sqlalchemy.url")
    target = validate_test_database_target(
        test_database_url=os.environ["TEST_DATABASE_URL"],
        runtime_database_url=runtime_url,
        isolation_confirmed=os.environ.get("PASTEXAM_TEST_DATABASE_ISOLATED"),
        allowed_hosts=os.environ.get(
            "TEST_DATABASE_ALLOWED_HOSTS",
            "127.0.0.1,localhost,db",
        ).split(","),
    )
    original_settings = {
        "DB_HOST": settings.DB_HOST,
        "DB_PORT": settings.DB_PORT,
        "DB_USER": settings.DB_USER,
        "DB_PASSWORD": settings.DB_PASSWORD,
        "DB_NAME": settings.DB_NAME,
    }
    monkeypatch.setattr(settings, "DB_HOST", test_url.host)
    monkeypatch.setattr(settings, "DB_PORT", test_url.port)
    monkeypatch.setattr(settings, "DB_USER", test_url.username)
    monkeypatch.setattr(settings, "DB_PASSWORD", test_url.password)
    monkeypatch.setattr(settings, "DB_NAME", target.database_name)

    cleanup_config = alembic_config()
    engine = create_engine(cleanup_config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        (
            actual_database_name,
            actual_user_name,
            actual_database_owner,
            is_superuser,
            can_create_database,
            can_create_role,
        ) = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "pg_get_userbyid(database.datdba), "
                "role.rolsuper, role.rolcreatedb, role.rolcreaterole "
                "FROM pg_database AS database "
                "JOIN pg_roles AS role ON role.rolname = current_user "
                "WHERE database.datname = current_database()"
            )
        ).one()
        validate_connected_test_database(
            actual_database_name=actual_database_name,
            actual_user_name=actual_user_name,
            actual_database_owner=actual_database_owner,
            is_superuser=is_superuser,
            can_create_database=can_create_database,
            can_create_role=can_create_role,
            target=target,
        )
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), PREVIOUS_REVISION)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(cleanup_config, "head")
        for setting_name, setting_value in original_settings.items():
            setattr(settings, setting_name, setting_value)
        engine.dispose()


def _default_row(
    definition_key: str,
    **overrides: Any,
) -> dict[str, Any]:
    definition = DEFAULT_COURSE_CATEGORY_BY_KEY[definition_key]
    row = {
        "key": definition.key,
        "name": definition.name,
        "label": definition.label,
        "icon": definition.icon,
        "badge_color": definition.badge_color,
        "order_index": definition.order_index,
        "is_active": True,
        "deleted_at": None,
        "deleted_by_id": None,
        "restored_at": None,
        "restored_by_id": None,
        "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _replace_categories(
    engine: Engine,
    rows: list[dict[str, Any]],
) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM course_category_configs"))
        for row in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO course_category_configs (
                        key, name, label, icon, badge_color, order_index,
                        is_active, created_at, updated_at, deleted_at,
                        deleted_by_id, restored_at, restored_by_id
                    )
                    VALUES (
                        :key, :name, :label, :icon, :badge_color, :order_index,
                        :is_active, now(), :updated_at, :deleted_at,
                        :deleted_by_id, :restored_at, :restored_by_id
                    )
                    """
                ),
                row,
            )


def _canonical_rows(**overrides_by_key: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _default_row(
            definition.key,
            **overrides_by_key.get(definition.key, {}),
        )
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    ]


def _category(engine: Engine, key: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, key, name, label, icon, badge_color, order_index,
                       is_active, created_at, updated_at, deleted_at,
                       deleted_by_id, restored_at, restored_by_id
                FROM course_category_configs
                WHERE key = :key
                """
            ),
            {"key": key},
        ).mappings().one()
    return dict(row)


def _all_categories(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT id, key, name, label, icon, badge_color, order_index,
                           is_active, created_at, updated_at, deleted_at,
                           deleted_by_id, restored_at, restored_by_id
                    FROM course_category_configs
                    ORDER BY id
                    """
                )
            ).mappings()
        ]


def _table_signatures(
    engine: Engine,
    table_names: tuple[str, ...],
) -> dict[str, tuple[int, int | None, int | None]]:
    with engine.connect() as connection:
        return {
            table_name: tuple(
                connection.execute(
                    text(
                        f"SELECT count(*), min(id), max(id) FROM {table_name}"
                    )
                ).one()
            )
            for table_name in table_names
        }


def _insert_category_references(
    engine: Engine,
    *,
    category: str,
    suffix: str,
) -> dict[str, int]:
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                """
                INSERT INTO users (email, name, is_admin, is_local)
                VALUES (:email, :name, false, true)
                RETURNING id
                """
            ),
            {
                "email": f"{suffix}@example.invalid",
                "name": f"user-{suffix}",
            },
        )
        course_id = connection.scalar(
            text(
                """
                INSERT INTO courses (name, category, order_index)
                VALUES (:name, :category, 0)
                RETURNING id
                """
            ),
            {"name": f"Course {suffix}", "category": category},
        )
        course_submission_id = connection.scalar(
            text(
                """
                INSERT INTO course_submissions (
                    name, category, status, requester_id, created_at
                )
                VALUES (:name, :category, 'PENDING', :user_id, now())
                RETURNING id
                """
            ),
            {
                "name": f"Course request {suffix}",
                "category": category,
                "user_id": user_id,
            },
        )
        archive_submission_id = connection.scalar(
            text(
                """
                INSERT INTO archive_submissions (
                    subject, category, name, academic_year, archive_type,
                    professor, has_answers, object_name, status,
                    requester_id, is_admin_upload, created_at,
                    requested_category_key, requested_category_name,
                    requested_category_label, requested_category_icon
                )
                VALUES (
                    :subject, :category, :name, 114, 'MIDTERM',
                    'Professor', false, :object_name, 'PENDING',
                    :user_id, false, now(), :category, :requested_name,
                    :requested_label, :requested_icon
                )
                RETURNING id
                """
            ),
            {
                "subject": f"Subject {suffix}",
                "category": category,
                "name": f"Exam {suffix}",
                "object_name": f"test/{suffix}.pdf",
                "user_id": user_id,
                "requested_name": f"Requested {suffix}",
                "requested_label": f"Snapshot label {suffix}",
                "requested_icon": f"snapshot-icon-{suffix}",
            },
        )
    return {
        "user": int(user_id),
        "course": int(course_id),
        "course_submission": int(course_submission_id),
        "archive_submission": int(archive_submission_id),
    }


def _upgrade_head() -> None:
    command.upgrade(alembic_config(), "head")


def test_fresh_database_creates_six_canonical_defaults(
    migration_engine: Engine,
) -> None:
    _upgrade_head()

    rows = _all_categories(migration_engine)
    assert len(rows) == 6
    assert {row["key"] for row in rows} == CANONICAL_COURSE_CATEGORY_KEYS
    assert {
        row["key"]: row["order_index"] for row in rows
    } == {
        "fundamental": 1,
        "required": 2,
        "optional": 3,
        "experience": 4,
        "graduate": 5,
        "math-department": 6,
    }
    math_category = next(
        row for row in rows if row["key"] == "math-department"
    )
    assert math_category["name"] == "戳戳數學系"
    assert math_category["label"] == "數學"


@pytest.mark.parametrize("managed_name", ["戳戳數學系", "自訂數學分類"])
def test_existing_canonical_metadata_and_soft_delete_are_preserved(
    migration_engine: Engine,
    managed_name: str,
) -> None:
    deleted_at = datetime(2025, 2, 3, tzinfo=timezone.utc)
    restored_at = datetime(2025, 2, 4, tzinfo=timezone.utc)
    _replace_categories(
        migration_engine,
        _canonical_rows(
            **{
                "math-department": {
                    "name": managed_name,
                    "label": "管理員標籤",
                    "icon": "custom-icon",
                    "badge_color": "violet",
                    "order_index": 42,
                    "is_active": False,
                    "deleted_at": deleted_at,
                    "deleted_by_id": 101,
                    "restored_at": restored_at,
                    "restored_by_id": 102,
                }
            }
        ),
    )
    before = _category(migration_engine, "math-department")

    _upgrade_head()

    assert _category(migration_engine, "math-department") == before


def test_existing_canonical_course_order_is_preserved(
    migration_engine: Engine,
) -> None:
    _replace_categories(
        migration_engine,
        _canonical_rows(
            optional={"order_index": 81},
            experience={"order_index": 82},
        ),
    )
    before_optional = _category(migration_engine, "optional")
    before_experience = _category(migration_engine, "experience")

    _upgrade_head()

    assert _category(migration_engine, "optional") == before_optional
    assert _category(migration_engine, "experience") == before_experience


def test_known_math_typo_only_updates_name_and_timestamp(
    migration_engine: Engine,
) -> None:
    _replace_categories(
        migration_engine,
        _canonical_rows(
            **{
                "math-department": {
                    "name": "跨群數學系",
                    "label": "管理員標籤",
                    "icon": "custom-icon",
                    "badge_color": "amber",
                    "order_index": 73,
                    "is_active": False,
                    "deleted_at": datetime(2025, 3, 1, tzinfo=timezone.utc),
                    "deleted_by_id": 201,
                    "restored_at": datetime(2025, 3, 2, tzinfo=timezone.utc),
                    "restored_by_id": 202,
                }
            }
        ),
    )
    before = _category(migration_engine, "math-department")

    _upgrade_head()

    after = _category(migration_engine, "math-department")
    assert after["name"] == "戳戳數學系"
    assert after["updated_at"] > before["updated_at"]
    assert {
        key: value
        for key, value in after.items()
        if key not in {"name", "updated_at"}
    } == {
        key: value
        for key, value in before.items()
        if key not in {"name", "updated_at"}
    }


def test_existing_canonical_row_updates_legacy_references_only(
    migration_engine: Engine,
) -> None:
    _replace_categories(migration_engine, _canonical_rows())
    before = _category(migration_engine, "fundamental")
    ids = _insert_category_references(
        migration_engine,
        category="freshman",
        suffix="canonical-with-legacy-reference",
    )

    _upgrade_head()

    assert _category(migration_engine, "fundamental") == before
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT category FROM courses WHERE id = :id"),
            {"id": ids["course"]},
        ) == "fundamental"
        assert connection.scalar(
            text("SELECT category FROM course_submissions WHERE id = :id"),
            {"id": ids["course_submission"]},
        ) == "fundamental"
        submission = connection.execute(
            text(
                """
                SELECT category, requested_category_key,
                       requested_category_name, requested_category_label,
                       requested_category_icon
                FROM archive_submissions
                WHERE id = :id
                """
            ),
            {"id": ids["archive_submission"]},
        ).one()
        assert tuple(submission) == (
            "fundamental",
            "fundamental",
            "Requested canonical-with-legacy-reference",
            "Snapshot label canonical-with-legacy-reference",
            "snapshot-icon-canonical-with-legacy-reference",
        )


def test_custom_category_and_its_references_are_untouched(
    migration_engine: Engine,
) -> None:
    custom = _default_row(
        "fundamental",
        key="web-development",
        name="網站架設",
        label="網站",
        icon="custom-web-icon",
        badge_color="forest",
        order_index=99,
        is_active=False,
        deleted_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
        deleted_by_id=301,
        restored_at=datetime(2025, 4, 2, tzinfo=timezone.utc),
        restored_by_id=302,
    )
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO course_category_configs (
                    key, name, label, icon, badge_color, order_index,
                    is_active, created_at, updated_at, deleted_at,
                    deleted_by_id, restored_at, restored_by_id
                )
                VALUES (
                    :key, :name, :label, :icon, :badge_color, :order_index,
                    :is_active, now(), :updated_at, :deleted_at,
                    :deleted_by_id, :restored_at, :restored_by_id
                )
                """
            ),
            custom,
        )
    ids = _insert_category_references(
        migration_engine,
        category="web-development",
        suffix="custom",
    )
    before = _category(migration_engine, "web-development")
    before_signatures = _table_signatures(
        migration_engine,
        ("users", "courses", "course_submissions", "archive_submissions"),
    )

    _upgrade_head()

    assert _category(migration_engine, "web-development") == before
    assert _table_signatures(
        migration_engine,
        ("users", "courses", "course_submissions", "archive_submissions"),
    ) == before_signatures
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT category FROM courses WHERE id = :id"),
            {"id": ids["course"]},
        ) == "web-development"
        assert connection.scalar(
            text("SELECT category FROM course_submissions WHERE id = :id"),
            {"id": ids["course_submission"]},
        ) == "web-development"
        submission = connection.execute(
            text(
                """
                SELECT category, requested_category_key,
                       requested_category_name, requested_category_label,
                       requested_category_icon
                FROM archive_submissions
                WHERE id = :id
                """
            ),
            {"id": ids["archive_submission"]},
        ).one()
        assert tuple(submission) == (
            "web-development",
            "web-development",
            "Requested custom",
            "Snapshot label custom",
            "snapshot-icon-custom",
        )


def test_legacy_only_row_keeps_id_metadata_and_updates_only_keys(
    migration_engine: Engine,
) -> None:
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE course_category_configs
                SET name = '管理員數學分類',
                    label = '管理員標籤',
                    icon = 'legacy-custom-icon',
                    badge_color = 'burgundy',
                    order_index = 77,
                    is_active = false,
                    deleted_at = '2025-05-01T00:00:00+00:00',
                    deleted_by_id = 401,
                    restored_at = '2025-05-02T00:00:00+00:00',
                    restored_by_id = 402,
                    updated_at = '2025-01-01T00:00:00+00:00'
                WHERE key = 'interdisciplinary'
                """
            )
        )
    before = _category(migration_engine, "interdisciplinary")
    ids = _insert_category_references(
        migration_engine,
        category="interdisciplinary",
        suffix="legacy",
    )

    _upgrade_head()

    after = _category(migration_engine, "math-department")
    assert after["id"] == before["id"]
    assert after["order_index"] == 77
    assert {
        key: value for key, value in after.items() if key != "key"
    } == {
        key: value for key, value in before.items() if key != "key"
    }
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT category FROM courses WHERE id = :id"),
            {"id": ids["course"]},
        ) == "math-department"
        assert connection.scalar(
            text("SELECT category FROM course_submissions WHERE id = :id"),
            {"id": ids["course_submission"]},
        ) == "math-department"
        submission = connection.execute(
            text(
                """
                SELECT category, requested_category_key,
                       requested_category_name, requested_category_label,
                       requested_category_icon
                FROM archive_submissions
                WHERE id = :id
                """
            ),
            {"id": ids["archive_submission"]},
        ).one()
        assert tuple(submission) == (
            "math-department",
            "math-department",
            "Requested legacy",
            "Snapshot label legacy",
            "snapshot-icon-legacy",
        )


def test_canonical_and_legacy_collision_fails_and_rolls_back(
    migration_engine: Engine,
) -> None:
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO course_category_configs (
                    key, name, label, icon, badge_color, order_index,
                    is_active, created_at, updated_at
                )
                VALUES (
                    'math-department', '管理員 canonical 數學', '數學',
                    'canonical-icon', 'slate', 88, true, now(), now()
                )
                """
            )
        )
    before = _all_categories(migration_engine)

    with pytest.raises(
        RuntimeError,
        match="target canonical key='math-department'.*candidate row IDs",
    ):
        _upgrade_head()

    assert _all_categories(migration_engine) == before
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == PREVIOUS_REVISION


def test_duplicate_normalized_name_fails_without_deleting_rows(
    migration_engine: Engine,
) -> None:
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO course_category_configs (
                    key, name, label, icon, badge_color, order_index,
                    is_active, created_at, updated_at
                )
                VALUES
                    ('web-development', '網站架設', '網站', 'web-icon',
                     'forest', 90, true, now(), now()),
                    ('web-operations', '  網站架設  ', '維運', 'ops-icon',
                     'amber', 91, true, now(), now())
                """
            )
        )
    before = _all_categories(migration_engine)

    with pytest.raises(
        RuntimeError,
        match="multiple rows have the same normalized name",
    ):
        _upgrade_head()

    assert _all_categories(migration_engine) == before


def test_missing_canonical_with_default_name_on_custom_key_fails_closed(
    migration_engine: Engine,
) -> None:
    rows = _canonical_rows()
    rows = [
        row for row in rows if row["key"] != "math-department"
    ]
    rows.append(
        _default_row(
            "math-department",
            key="custom-math",
            name="戳戳數學系",
        )
    )
    _replace_categories(migration_engine, rows)
    before = _all_categories(migration_engine)

    with pytest.raises(
        RuntimeError,
        match="default name is already managed under a different key",
    ):
        _upgrade_head()

    assert _all_categories(migration_engine) == before
