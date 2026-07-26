from __future__ import annotations

import os

import pytest
from alembic import command
from sqlalchemy import create_engine, exc, text
from sqlalchemy.engine import Engine, make_url

from app.core.config import settings
from app.db.course_categories import CANONICAL_COURSE_CATEGORIES
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
    monkeypatch.setattr(settings, "DB_HOST", test_url.host)
    monkeypatch.setattr(settings, "DB_PORT", test_url.port)
    monkeypatch.setattr(settings, "DB_USER", test_url.username)
    monkeypatch.setattr(settings, "DB_PASSWORD", test_url.password)
    monkeypatch.setattr(settings, "DB_NAME", target.database_name)
    cleanup_database_settings = {
        "DB_HOST": settings.DB_HOST,
        "DB_PORT": settings.DB_PORT,
        "DB_USER": settings.DB_USER,
        "DB_PASSWORD": settings.DB_PASSWORD,
        "DB_NAME": settings.DB_NAME,
    }

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
        for setting_name, setting_value in cleanup_database_settings.items():
            setattr(settings, setting_name, setting_value)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(cleanup_config, "head")
        engine.dispose()


def _replace_categories(
    engine: Engine,
    rows: list[tuple[str, str]],
) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM course_category_configs"))
        for order_index, (key, name) in enumerate(rows):
            connection.execute(
                text(
                    """
                    INSERT INTO course_category_configs (
                        key, name, label, icon, badge_color, order_index,
                        is_active, created_at, updated_at
                    )
                    VALUES (
                        :key, :name, :name, 'pi pi-fw pi-book', 'blue',
                        :order_index, true, now(), now()
                    )
                    """
                ),
                {"key": key, "name": name, "order_index": order_index},
            )


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
                    requested_category_key, requested_category_name
                )
                VALUES (
                    :subject, :category, :name, 114, 'MIDTERM',
                    'Professor', false, :object_name, 'PENDING',
                    :user_id, false, now(), :category, :requested_name
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
            },
        )
        archive_id = connection.scalar(
            text(
                """
                INSERT INTO archives (
                    name, academic_year, archive_type, professor, has_answers,
                    download_count, object_name, uploader_id, course_id,
                    created_at, updated_at
                )
                VALUES (
                    :name, 114, 'MIDTERM', 'Professor', false, 0,
                    :object_name, :user_id, :course_id, now(), now()
                )
                RETURNING id
                """
            ),
            {
                "name": f"Published {suffix}",
                "object_name": f"test/published-{suffix}.pdf",
                "user_id": user_id,
                "course_id": course_id,
            },
        )
        discussion_id = connection.scalar(
            text(
                """
                INSERT INTO archive_discussion_messages (
                    archive_id, user_id, content, is_pinned, created_at
                )
                VALUES (:archive_id, :user_id, 'Preserved', false, now())
                RETURNING id
                """
            ),
            {"archive_id": archive_id, "user_id": user_id},
        )
        notification_id = connection.scalar(
            text(
                """
                INSERT INTO notifications (
                    title, body, severity, is_active, created_at, updated_at,
                    updated_by_id
                )
                VALUES (
                    'Preserved', 'Preserved', 'INFO', true, now(), now(),
                    :user_id
                )
                RETURNING id
                """
            ),
            {"user_id": user_id},
        )
    return {
        "user": int(user_id),
        "course": int(course_id),
        "course_submission": int(course_submission_id),
        "archive_submission": int(archive_submission_id),
        "archive": int(archive_id),
        "discussion": int(discussion_id),
        "notification": int(notification_id),
    }


def _category_rows(engine: Engine) -> list[tuple[int, str, str]]:
    with engine.connect() as connection:
        return [
            (int(row.id), row.key, row.name)
            for row in connection.execute(
                text(
                    """
                    SELECT id, key, name
                    FROM course_category_configs
                    ORDER BY order_index, id
                    """
                )
            )
        ]


def _upgrade_head() -> None:
    command.upgrade(alembic_config(), "head")


def test_canonical_only_upgrade_is_a_data_noop(
    migration_engine: Engine,
) -> None:
    _replace_categories(
        migration_engine,
        [(item.key, item.name) for item in CANONICAL_COURSE_CATEGORIES],
    )
    ids = _insert_category_references(
        migration_engine,
        category="fundamental",
        suffix="canonical",
    )
    before_categories = _category_rows(migration_engine)

    _upgrade_head()

    assert _category_rows(migration_engine) == before_categories
    with migration_engine.connect() as connection:
        for table_name, row_id in {
            "users": ids["user"],
            "courses": ids["course"],
            "course_submissions": ids["course_submission"],
            "archive_submissions": ids["archive_submission"],
            "archives": ids["archive"],
            "archive_discussion_messages": ids["discussion"],
            "notifications": ids["notification"],
        }.items():
            assert connection.scalar(
                text(f"SELECT count(*) FROM {table_name} WHERE id = :id"),
                {"id": row_id},
            ) == 1


def test_legacy_only_upgrade_preserves_ids_and_references(
    migration_engine: Engine,
) -> None:
    legacy_ids = {
        key: row_id for row_id, key, _ in _category_rows(migration_engine)
    }
    ids = _insert_category_references(
        migration_engine,
        category="freshman",
        suffix="legacy",
    )

    _upgrade_head()

    rows = _category_rows(migration_engine)
    assert len(rows) == 6
    assert {key for _, key, _ in rows} == {
        item.key for item in CANONICAL_COURSE_CATEGORIES
    }
    assert next(row_id for row_id, key, _ in rows if key == "fundamental") == (
        legacy_ids["freshman"]
    )
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
                SELECT category, requested_category_key
                FROM archive_submissions
                WHERE id = :id
                """
            ),
            {"id": ids["archive_submission"]},
        ).one()
        assert tuple(submission) == ("fundamental", "fundamental")
        with pytest.raises(exc.IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO course_category_configs (
                        key, name, label, icon, badge_color, order_index,
                        is_active, created_at, updated_at
                    )
                    VALUES (
                        'freshman', 'Legacy reinsert', 'Legacy',
                        'pi pi-fw pi-book', 'blue', 99, true, now(), now()
                    )
                    """
                )
            )


def test_mixed_upgrade_keeps_canonical_ids_and_all_references(
    migration_engine: Engine,
) -> None:
    with migration_engine.begin() as connection:
        canonical_ids = {}
        for definition in CANONICAL_COURSE_CATEGORIES:
            if definition.key == "graduate":
                continue
            canonical_ids[definition.key] = connection.scalar(
                text(
                    """
                    INSERT INTO course_category_configs (
                        key, name, label, icon, badge_color, order_index,
                        is_active, created_at, updated_at
                    )
                    VALUES (
                        :key, :name, :label, :icon, :badge_color,
                        :order_index, true, now(), now()
                    )
                    RETURNING id
                    """
                ),
                definition.__dict__,
            )
        connection.execute(
            text(
                """
                INSERT INTO course_category_configs (
                    key, name, label, icon, badge_color, order_index,
                    is_active, created_at, updated_at
                )
                VALUES (
                    'GRADUATE', '研究所', 'Duplicate graduate',
                    'pi pi-fw pi-book', 'blue', 99, true, now(), now()
                )
                """
            )
        )
    legacy_refs = _insert_category_references(
        migration_engine,
        category="freshman",
        suffix="mixed-legacy",
    )
    canonical_refs = _insert_category_references(
        migration_engine,
        category="fundamental",
        suffix="mixed-canonical",
    )

    _upgrade_head()

    rows = _category_rows(migration_engine)
    assert len(rows) == 6
    assert {key for _, key, _ in rows} == {
        item.key for item in CANONICAL_COURSE_CATEGORIES
    }
    assert next(row_id for row_id, key, _ in rows if key == "fundamental") == (
        canonical_ids["fundamental"]
    )
    with migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM courses")) == 2
        assert connection.scalar(
            text("SELECT count(*) FROM courses WHERE category='fundamental'")
        ) == 2
        for ids in (legacy_refs, canonical_refs):
            assert connection.scalar(
                text("SELECT count(*) FROM courses WHERE id=:id"),
                {"id": ids["course"]},
            ) == 1
