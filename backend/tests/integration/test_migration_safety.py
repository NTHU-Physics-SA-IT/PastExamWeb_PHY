from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine, make_url

import migrate
from alembic import command
from app.core.config import settings
from app.db.migration_safety import (
    alembic_config,
    database_url,
    inspect_database,
    migration_advisory_lock,
    revision_graph,
    safe_error,
)
from app.db.test_database_guard import (
    validate_connected_test_database,
    validate_test_database_target,
)

MERGED_HEAD = "b4d6f8a2c1e3"
CURRENT_HEAD = "f3a7c1e9d5b2"
E6_REVISION = "e6a1b3c5d7f9"
E8_REVISION = "e8a4c1d7b2f6"
COORDINATION_SIBLING = "a9c2e5f7b1d4"
MAIN_SIBLING = "a9c4e7b2d6f1"


def _load_revision_module(revision: str, filename: str):
    path = Path(__file__).parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"revision_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_public_schema(monkeypatch: pytest.MonkeyPatch) -> Engine:
    test_database_url = os.environ["TEST_DATABASE_URL"]
    test_url = make_url(test_database_url)
    runtime_url = database_url().render_as_string(hide_password=False)
    target = validate_test_database_target(
        test_database_url=test_database_url,
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


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def head_revision() -> str:
    _, heads = revision_graph()
    assert len(heads) == 1
    return heads[0]


def drop_ledger(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))


def insert_course(engine: Engine, name: str = "Migration safety marker") -> int:
    with engine.begin() as connection:
        return int(
            connection.scalar(
                text(
                    "INSERT INTO courses (name, category, order_index) "
                    "VALUES (:name, 'FRESHMAN', 0) RETURNING id"
                ),
                {"name": name},
            )
        )


def _ledger(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return sorted(
            str(value)
            for value in connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
        )


def _schema_signature(engine: Engine) -> dict[str, tuple[str, ...]]:
    inspector = sa_inspect(engine)
    return {
        table_name: tuple(
            column["name"]
            for column in inspector.get_columns(table_name, schema="public")
        )
        for table_name in sorted(inspector.get_table_names(schema="public"))
        if table_name != "alembic_version"
    }


@pytest.mark.parametrize(
    "source_revision",
    [None, E6_REVISION, COORDINATION_SIBLING, MAIN_SIBLING],
    ids=("empty", "e6", "coordination-a9c2", "main-a9c4"),
)
def test_known_sibling_baselines_converge_to_current_head(
    clean_public_schema: Engine,
    source_revision: str | None,
) -> None:
    if source_revision is not None:
        upgrade(source_revision)
        with clean_public_schema.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO about_us_entries "
                    "(title, body, created_at, updated_at, updated_by_id) "
                    "VALUES ('sibling convergence sentinel', :body, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)"
                ),
                {"body": source_revision},
            )

    command.upgrade(alembic_config(), CURRENT_HEAD)

    assert _ledger(clean_public_schema) == [CURRENT_HEAD]
    assert inspect_database().schema_matches_head is True
    if source_revision is not None:
        with clean_public_schema.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT body FROM about_us_entries "
                    "WHERE title = 'sibling convergence sentinel'"
                )
            ) == source_revision


def test_merge_revision_upgrade_and_downgrade_are_schema_no_ops(
    clean_public_schema: Engine,
) -> None:
    upgrade(MERGED_HEAD)
    before = _schema_signature(clean_public_schema)
    revision = _load_revision_module(
        MERGED_HEAD,
        "b4d6f8a2c1e3_merge_stage5d_and_wish_pool_heads.py",
    )

    assert revision.down_revision == (COORDINATION_SIBLING, MAIN_SIBLING)
    revision.downgrade()
    revision.upgrade()

    assert _ledger(clean_public_schema) == [MERGED_HEAD]
    assert _schema_signature(clean_public_schema) == before


def test_optional_wish_semester_upgrade_preserves_values_and_allows_null(
    clean_public_schema: Engine,
) -> None:
    upgrade(MERGED_HEAD)
    with clean_public_schema.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email, name, is_admin, is_local) "
                "VALUES ('wish-migration@example.invalid', 'wish migration', false, true) "
                "RETURNING id"
            )
        )
        wish_id = connection.scalar(
            text(
                "INSERT INTO archive_wishes "
                "(title, target_key, subject, category, name, academic_year, "
                "archive_type, professor, creator_id) VALUES "
                "('specified', :key, 'Physics', 'required', 'midterm1', 1141, "
                "'MIDTERM', 'Professor', :creator_id) RETURNING id"
            ),
            {"key": "a" * 64, "creator_id": user_id},
        )

    command.upgrade(alembic_config(), CURRENT_HEAD)
    columns = {
        column["name"]: column
        for column in sa_inspect(clean_public_schema).get_columns(
            "archive_wishes", schema="public"
        )
    }
    assert columns["academic_year"]["nullable"] is True
    with clean_public_schema.begin() as connection:
        assert connection.scalar(
            text("SELECT academic_year FROM archive_wishes WHERE id = :id"),
            {"id": wish_id},
        ) == 1141
        connection.execute(
            text(
                "INSERT INTO archive_wishes "
                "(title, target_key, subject, category, name, academic_year, "
                "archive_type, professor, creator_id) VALUES "
                "('any', :key, 'Physics', 'required', 'midterm1', NULL, "
                "'MIDTERM', 'Professor', :creator_id)"
            ),
            {"key": "b" * 64, "creator_id": user_id},
        )

    with pytest.raises(RuntimeError, match="Any Semester wishes exist"):
        command.downgrade(alembic_config(), MERGED_HEAD)


def test_main_sibling_requires_complete_coordination_schema(
    clean_public_schema: Engine,
) -> None:
    upgrade(COORDINATION_SIBLING)
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_course_submissions_deleted_at"))
        revision = _load_revision_module(
            MAIN_SIBLING,
            "a9c4e7b2d6f1_add_bilingual_content_and_wish_pool.py",
        )
        with pytest.raises(RuntimeError, match="continuity is incomplete"):
            revision._verify_source_schema(connection)


def test_category_transition_requires_complete_main_sibling_schema(
    clean_public_schema: Engine,
) -> None:
    upgrade(MAIN_SIBLING)
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_archive_wishes_course_id"))
        revision = _load_revision_module(
            E8_REVISION,
            "e8a4c1d7b2f6_add_category_pre_delete_active_state.py",
        )
        with pytest.raises(RuntimeError, match="Wish constraints are incomplete"):
            revision._verify_upgrade_source(connection)


def test_coordination_transition_requires_complete_main_sibling_schema(
    clean_public_schema: Engine,
) -> None:
    upgrade(MAIN_SIBLING)
    command.upgrade(alembic_config(), E8_REVISION)
    assert _ledger(clean_public_schema) == sorted([E8_REVISION, MAIN_SIBLING])
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP TABLE archive_wish_reports"))
        revision = _load_revision_module(
            COORDINATION_SIBLING,
            "a9c2e5f7b1d4_add_course_submission_lifecycle.py",
        )
        with pytest.raises(RuntimeError, match="Wish schema is incomplete"):
            revision._verify_upgrade_source(connection)


def test_unknown_sibling_ledger_fails_closed(clean_public_schema: Engine) -> None:
    upgrade(E6_REVISION)
    with clean_public_schema.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = 'unknown_sibling'")
        )
        revision = _load_revision_module(
            E8_REVISION,
            "e8a4c1d7b2f6_add_category_pre_delete_active_state.py",
        )
        with pytest.raises(RuntimeError, match=r"found \['unknown_sibling'\]"):
            revision._verify_upgrade_source(connection)


def test_empty_database_upgrade_is_idempotent() -> None:
    report = inspect_database()
    assert report.database_empty is True
    assert report.upgrade_allowed is True

    assert migrate.main(["upgrade", "--json"]) == 0
    assert inspect_database().current_revision == head_revision()
    assert migrate.main(["upgrade", "--json"]) == 0
    assert inspect_database().upgrade_allowed is True


def _default_bilingual_courses() -> list[dict[str, str]]:
    category_keys = {
        "FRESHMAN": "fundamental",
        "SOPHOMORE": "required",
        "JUNIOR": "experience",
        "SENIOR": "optional",
        "GRADUATE": "graduate",
        "INTERDISCIPLINARY": "math-department",
    }
    seed_path = Path(__file__).parents[2] / "app" / "db" / "seed_data.yaml"
    seed = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
    return [
        {
            "name": row["name"],
            "name_en": row["name_en"],
            "category": category_keys[row["category"]],
        }
        for row in seed["courses"]
    ]


def _insert_default_courses(engine: Engine, *, omit_last: bool = False) -> None:
    rows = _default_bilingual_courses()
    if omit_last:
        rows = rows[:-1]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO courses (name, category, order_index) "
                "VALUES (:name, :category, 0)"
            ),
            [{"name": row["name"], "category": row["category"]} for row in rows],
        )


def test_bilingual_catalog_backfills_defaults_and_preserves_custom_rows(
    clean_public_schema: Engine,
) -> None:
    previous_revision = "b7e3d9a1c5f2"
    catalog_revision = "c2a8e4f6b9d1"
    upgrade(previous_revision)
    defaults = _default_bilingual_courses()
    assert len(defaults) == 71
    _insert_default_courses(clean_public_schema)
    with clean_public_schema.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO course_category_configs (key, name, label) "
                "VALUES ('custom-category', 'Custom Category', 'Custom')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO courses (name, category, order_index) "
                "VALUES ('Custom Course', 'custom-category', 99)"
            )
        )
        canonical_before = connection.execute(
            text(
                "SELECT key, name, label FROM course_category_configs "
                "WHERE key = 'fundamental'"
            )
        ).one()

    command.upgrade(alembic_config(), catalog_revision)

    with clean_public_schema.connect() as connection:
        actual_defaults = {
            (row.category, row.name): row.name_en
            for row in connection.execute(
                text(
                    "SELECT category, name, name_en FROM courses "
                    "WHERE name != 'Custom Course'"
                )
            )
        }
        assert actual_defaults == {
            (row["category"], row["name"]): row["name_en"] for row in defaults
        }
        assert connection.execute(
            text(
                "SELECT name, category, name_en FROM courses "
                "WHERE name = 'Custom Course'"
            )
        ).one() == ("Custom Course", "custom-category", None)
        assert connection.execute(
            text(
                "SELECT key, name, label, name_en, label_en "
                "FROM course_category_configs WHERE key = 'custom-category'"
            )
        ).one() == (
            "custom-category",
            "Custom Category",
            "Custom",
            None,
            None,
        )
        assert {
            row.key: (row.name_en, row.label_en)
            for row in connection.execute(
                text(
                    "SELECT key, name_en, label_en "
                    "FROM course_category_configs WHERE key != 'custom-category'"
                )
            )
        } == {
            "fundamental": ("Foundation Courses", "Foundation"),
            "required": ("Required Major Courses", "Required"),
            "optional": ("Major Electives", "Elective"),
            "experience": ("Laboratory Courses", "Laboratory"),
            "graduate": ("Graduate Courses", "Graduate"),
            "math-department": ("Mathematics Courses", "Mathematics"),
        }
        assert (
            connection.execute(
                text(
                    "SELECT key, name, label FROM course_category_configs "
                    "WHERE key = 'fundamental'"
                )
            ).one()
            == canonical_before
        )

    command.downgrade(alembic_config(), previous_revision)
    inspector = sa_inspect(clean_public_schema)
    assert "name_en" not in {
        column["name"] for column in inspector.get_columns("courses", schema="public")
    }
    assert {"name_en", "label_en"}.isdisjoint(
        column["name"]
        for column in inspector.get_columns("course_category_configs", schema="public")
    )
    with clean_public_schema.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM courses")) == 72
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM course_category_configs "
                    "WHERE key = 'custom-category'"
                )
            )
            == 1
        )

    command.upgrade(alembic_config(), "head")
    snapshot_columns = {
        column["name"]: column
        for column in sa_inspect(clean_public_schema).get_columns(
            "archive_submissions", schema="public"
        )
    }
    for column_name in (
        "requested_course_name_en",
        "requested_category_name_en",
        "requested_category_label_en",
    ):
        assert snapshot_columns[column_name]["nullable"] is True


def test_bilingual_catalog_nonempty_partial_defaults_fail_closed(
    clean_public_schema: Engine,
) -> None:
    previous_revision = "b7e3d9a1c5f2"
    upgrade(previous_revision)
    _insert_default_courses(clean_public_schema, omit_last=True)

    with pytest.raises(RuntimeError, match="missing canonical course"):
        command.upgrade(alembic_config(), "c2a8e4f6b9d1")

    inspector = sa_inspect(clean_public_schema)
    assert "name_en" not in {
        column["name"] for column in inspector.get_columns("courses", schema="public")
    }
    with clean_public_schema.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            previous_revision
        )


def test_head_database_preflight_is_read_only(clean_public_schema: Engine) -> None:
    upgrade()
    course_id = insert_course(clean_public_schema)

    before = inspect_database().to_dict()
    assert migrate.main(["preflight", "--json"]) == 0
    after = inspect_database().to_dict()

    assert before == after
    with clean_public_schema.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM courses WHERE id = :course_id"),
                {"course_id": course_id},
            )
            == 1
        )


def test_head_schema_matches_sqlmodel_autogenerate_contract() -> None:
    upgrade()

    command.check(alembic_config())


def test_head_schema_accepts_equivalent_postgresql_check_reflection(
    clean_public_schema: Engine,
) -> None:
    upgrade()

    with clean_public_schema.connect() as connection:
        reflected = {
            item["name"]: item["sqltext"]
            for item in sa_inspect(connection).get_check_constraints(
                "archive_submissions",
                schema="public",
            )
        }

    previous_status_check = reflected[
        "ck_archive_submissions_previous_status_not_deleted"
    ]
    active_status_check = reflected[
        "ck_archive_submissions_active_previous_status_null"
    ]
    assert "previous_status::text" in previous_status_check
    assert "status::text" in active_status_check
    assert "cast(" not in previous_status_check.lower()
    assert "cast(" not in active_status_check.lower()

    report = inspect_database()
    check = next(
        item
        for item in report.schema_checks
        if item.name == "archive_submissions.check_constraints"
    )
    assert check.passed is True


def test_missing_ledger_reports_candidate_but_never_stamps(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    course_id = insert_course(clean_public_schema)
    drop_ledger(clean_public_schema)

    assert migrate.main(["upgrade", "--json"]) == 2
    assert migrate.main(["reconcile", "--check", "--json"]) == 2
    report = inspect_database()

    assert report.schema_matches_head is True
    assert report.schema_candidate_revision == head_revision()
    assert report.upgrade_allowed is False
    with clean_public_schema.connect() as connection:
        assert "alembic_version" not in sa_inspect(connection).get_table_names()
        assert (
            connection.scalar(
                text("SELECT count(*) FROM courses WHERE id = :course_id"),
                {"course_id": course_id},
            )
            == 1
        )


def test_missing_ledger_with_drift_fails_without_mutation(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    drop_ledger(clean_public_schema)
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_users_deleted_by_id"))

    report = inspect_database()
    assert report.upgrade_allowed is False
    assert report.schema_matches_head is False
    assert any(
        not check.passed and check.name == "users.indexes"
        for check in report.schema_checks
    )
    with clean_public_schema.connect() as connection:
        assert "alembic_version" not in sa_inspect(connection).get_table_names()
        assert not connection.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_indexes "
                "WHERE schemaname='public' AND indexname='ix_users_deleted_by_id'"
                ")"
            )
        )


def test_unknown_and_multiple_ledger_revisions_fail(
    clean_public_schema: Engine,
) -> None:
    upgrade()
    with clean_public_schema.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num='unknown_revision'")
        )
    unknown = inspect_database()
    assert unknown.current_revision_known is False
    assert unknown.upgrade_allowed is False

    with clean_public_schema.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES (:head), ('unexpected_second_revision')"
            ),
            {"head": head_revision()},
        )
    multiple = inspect_database()
    assert len(multiple.alembic_versions) == 2
    assert multiple.upgrade_allowed is False
    assert any("exactly one revision" in error for error in multiple.errors)


def test_known_non_head_revision_has_validated_forward_upgrade() -> None:
    script, _ = revision_graph()
    assert script.get_revision(head_revision()).down_revision == MERGED_HEAD
    merge_parents = script.get_revision(MERGED_HEAD).down_revision
    assert merge_parents == (COORDINATION_SIBLING, MAIN_SIBLING)
    previous_revision = MAIN_SIBLING
    upgrade(previous_revision)

    before = inspect_database()
    assert before.alembic_versions == [previous_revision]
    assert before.upgrade_allowed is True
    assert migrate.main(["upgrade", "--json"]) == 0
    after = inspect_database()
    assert after.current_revision == head_revision()
    assert after.schema_matches_head is True


@pytest.mark.parametrize(
    "source_revision",
    [
        "a4c7e9d2f6b1",
        "c9e4f1a7b2d6",
        "e3b7c1d9f5a2",
        "a7c3e9f1b5d2",
    ],
)
def test_model_derived_reviewed_sources_have_validated_forward_upgrade(
    source_revision: str,
) -> None:
    upgrade(source_revision)

    before = inspect_database()
    assert before.alembic_versions == [source_revision]
    assert before.upgrade_allowed is True
    assert migrate.main(["upgrade", "--json"]) == 0

    after = inspect_database()
    assert after.current_revision == head_revision()
    assert after.schema_matches_head is True


def test_archive_report_revision_is_additive_and_reversible(
    clean_public_schema: Engine,
) -> None:
    previous_revision = "e3b7c1d9f5a2"
    new_revision = "a7c3e9f1b5d2"
    config = alembic_config()
    upgrade(previous_revision)

    def schema_signature() -> dict[str, tuple[str, ...]]:
        with clean_public_schema.connect() as connection:
            inspector = sa_inspect(connection)
            return {
                table_name: tuple(
                    column["name"]
                    for column in inspector.get_columns(table_name, schema="public")
                )
                for table_name in inspector.get_table_names(schema="public")
                if table_name != "alembic_version"
            }

    baseline = schema_signature()
    assert "archive_reports" not in baseline

    command.upgrade(config, new_revision)
    upgraded = schema_signature()
    assert set(upgraded) == {*baseline, "archive_reports"}
    assert all(upgraded[name] == columns for name, columns in baseline.items())
    assert {
        "reporter_user_id",
        "archive_id",
        "archive_submission_id",
        "archive_id_snapshot",
        "status",
        "archive_taken_down",
        "deleted_at",
    }.issubset(upgraded["archive_reports"])

    command.downgrade(config, previous_revision)
    assert schema_signature() == baseline

    command.upgrade(config, new_revision)
    assert schema_signature() == upgraded
    _, heads = revision_graph(config)
    assert heads == [head_revision()]
    with clean_public_schema.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == new_revision
        )


def test_category_state_preservation_revision_backfills_and_fails_closed(
    clean_public_schema: Engine,
) -> None:
    baseline_revision = "d4b7e2a9c6f1"
    previous_revision = "e6a1b3c5d7f9"
    new_revision = "e8a4c1d7b2f6"
    config = alembic_config()
    upgrade(baseline_revision)

    rows = (
        ("d1-live-active", True, None),
        ("d1-live-inactive", False, None),
        ("d1-deleted-active", True, "2026-08-15T00:00:00+00:00"),
        ("d1-deleted-inactive", False, "2026-08-15T00:00:00+00:00"),
    )
    with clean_public_schema.begin() as connection:
        for order_index, (key, is_active, deleted_at) in enumerate(rows):
            connection.execute(
                text(
                    "INSERT INTO course_category_configs "
                    "(key, name, label, icon, badge_color, order_index, "
                    "is_active, deleted_at) "
                    "VALUES (:key, :name, '', 'pi pi-book', 'blue', "
                    ":order_index, :is_active, :deleted_at)"
                ),
                {
                    "key": key,
                    "name": key,
                    "order_index": order_index,
                    "is_active": is_active,
                    "deleted_at": deleted_at,
                },
            )

    command.upgrade(config, new_revision)
    with clean_public_schema.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == new_revision
        )
        assert sa_inspect(connection).has_table("about_us_entries", schema="public")
        migrated = {
            row.key: (row.is_active, row.pre_delete_is_active)
            for row in connection.execute(
                text(
                    "SELECT key, is_active, pre_delete_is_active "
                    "FROM course_category_configs WHERE key LIKE 'd1-%'"
                )
            )
        }
    assert migrated == {
        "d1-live-active": (True, None),
        "d1-live-inactive": (False, None),
        "d1-deleted-active": (False, True),
        "d1-deleted-inactive": (False, False),
    }

    with clean_public_schema.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO about_us_entries "
                "(title, body, created_at, updated_at, updated_by_id) "
                "VALUES ('D1 migration sentinel', 'preserve across downgrade', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)"
            )
        )

    command.downgrade(config, previous_revision)
    with clean_public_schema.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == previous_revision
        )
        inspector = sa_inspect(connection)
        assert inspector.has_table("about_us_entries", schema="public")
        assert "pre_delete_is_active" not in {
            column["name"]
            for column in inspector.get_columns(
                "course_category_configs", schema="public"
            )
        }
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM about_us_entries "
                    "WHERE title = 'D1 migration sentinel'"
                )
            )
            == 1
        )
        downgraded = {
            row.key: row.is_active
            for row in connection.execute(
                text(
                    "SELECT key, is_active FROM course_category_configs "
                    "WHERE key LIKE 'd1-%'"
                )
            )
        }
    assert downgraded == {key: is_active for key, is_active, _ in rows}
    source_report = inspect_database()
    assert source_report.current_revision == previous_revision
    assert source_report.schema_candidate_revision == previous_revision
    assert source_report.upgrade_allowed is True

    command.upgrade(config, new_revision)
    with clean_public_schema.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM about_us_entries "
                    "WHERE title = 'D1 migration sentinel'"
                )
            )
            == 1
        )
    with clean_public_schema.begin() as connection:
        connection.execute(
            text(
                "UPDATE course_category_configs SET pre_delete_is_active = NULL "
                "WHERE key = 'd1-deleted-active'"
            )
        )
    with pytest.raises(RuntimeError, match="snapshot validation failed"):
        command.downgrade(config, previous_revision)


def test_course_submission_lifecycle_revision_is_additive_and_reversible(
    clean_public_schema: Engine,
) -> None:
    previous_revision = "e8a4c1d7b2f6"
    new_revision = "a9c2e5f7b1d4"
    config = alembic_config()
    upgrade(previous_revision)

    def lifecycle_shape(connection) -> tuple[set[str], str | None]:
        inspector = sa_inspect(connection)
        columns = {
            column["name"]
            for column in inspector.get_columns("course_submissions", schema="public")
        }
        matching_foreign_keys = [
            foreign_key
            for foreign_key in inspector.get_foreign_keys(
                "course_submissions", schema="public"
            )
            if foreign_key["constrained_columns"] == ["created_course_id"]
            and foreign_key["referred_table"] == "courses"
        ]
        assert len(matching_foreign_keys) == 1
        return columns, (matching_foreign_keys[0].get("options") or {}).get("ondelete")

    lifecycle_columns = {
        "previous_status",
        "deleted_at",
        "deleted_by_id",
        "restored_at",
        "restored_by_id",
    }
    with clean_public_schema.connect() as connection:
        source_columns, source_ondelete = lifecycle_shape(connection)
    assert lifecycle_columns.isdisjoint(source_columns)
    assert source_ondelete is None

    command.upgrade(config, new_revision)
    with clean_public_schema.connect() as connection:
        upgraded_columns, upgraded_ondelete = lifecycle_shape(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            new_revision
        )
    assert lifecycle_columns.issubset(upgraded_columns)
    assert upgraded_ondelete == "SET NULL"

    command.downgrade(config, previous_revision)
    with clean_public_schema.connect() as connection:
        downgraded_columns, downgraded_ondelete = lifecycle_shape(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            previous_revision
        )
    assert lifecycle_columns.isdisjoint(downgraded_columns)
    assert downgraded_ondelete is None


def test_known_revision_without_manifest_is_blocked() -> None:
    upgrade("d1e6c8a4f2b9")

    report = inspect_database()

    assert report.current_revision == "d1e6c8a4f2b9"
    assert report.upgrade_allowed is False
    assert any(
        "no reviewed schema manifest" in error and "d1e6c8a4f2b9" in error
        for error in report.errors
    )
    assert migrate.main(["upgrade", "--json"]) == 2


def test_reviewed_source_schema_drift_is_blocked(
    clean_public_schema: Engine,
) -> None:
    upgrade("c9e4f1a7b2d6")
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_users_deleted_by_id"))

    report = inspect_database()

    assert report.current_revision == "c9e4f1a7b2d6"
    assert report.upgrade_allowed is False
    assert any("source schema" in error.lower() for error in report.errors)


def test_head_schema_drift_is_blocked(clean_public_schema: Engine) -> None:
    upgrade()
    with clean_public_schema.begin() as connection:
        connection.execute(text("DROP INDEX ix_courses_category"))

    report = inspect_database()

    assert report.current_revision == head_revision()
    assert report.upgrade_allowed is False
    assert any("head" in error.lower() for error in report.errors)


def test_concurrent_migration_advisory_lock_fails_closed(
    clean_public_schema: Engine,
) -> None:
    second_engine = create_engine(alembic_config().get_main_option("sqlalchemy.url"))
    try:
        with (
            migration_advisory_lock(clean_public_schema),
            pytest.raises(RuntimeError, match="advisory lock"),
            migration_advisory_lock(second_engine),
        ):
            pass
    finally:
        second_engine.dispose()


def test_multiple_repository_heads_fail_closed(
    clean_public_schema: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade()
    script, heads = revision_graph()
    current_head = heads[0]
    monkeypatch.setattr(
        "app.db.migration_safety.revision_graph",
        lambda config=None: (script, [current_head, "second_head"]),
    )
    report = inspect_database()
    assert report.multiple_heads is True
    assert report.upgrade_allowed is False


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        ("DROP TABLE announcement_read_receipts", "tables"),
        ("ALTER TABLE users DROP COLUMN nickname", "users.columns"),
        (
            (
                "ALTER TABLE users ALTER COLUMN show_level_title TYPE text "
                "USING show_level_title::text"
            ),
            "users.show_level_title.type",
        ),
        (
            "ALTER TABLE users ALTER COLUMN email DROP NOT NULL",
            "users.email.nullability",
        ),
        (
            (
                "ALTER TABLE system_issue_reports "
                "ALTER COLUMN github_sync_status DROP DEFAULT"
            ),
            "system_issue_reports.github_sync_status.server_default",
        ),
        (
            "ALTER TABLE users DROP CONSTRAINT fk_users_deleted_by_id_users",
            "users.foreign_keys",
        ),
        (
            (
                "ALTER TABLE announcement_read_receipts "
                "DROP CONSTRAINT uq_announcement_read_receipts_notification_user"
            ),
            "announcement_read_receipts.unique_constraints",
        ),
        (
            "ALTER TABLE comment_reports DROP CONSTRAINT ck_comment_reports_status",
            "comment_reports.check_constraints",
        ),
        ("DROP INDEX ix_users_deleted_by_id", "users.indexes"),
        (
            "ALTER TYPE submissionstatus ADD VALUE 'UNEXPECTED_SAFETY_TEST_VALUE'",
            "enum.submissionstatus.values",
        ),
    ],
)
def test_partial_schema_states_fail_closed(
    clean_public_schema: Engine, mutation: str, failed_check: str
) -> None:
    upgrade()
    drop_ledger(clean_public_schema)
    with clean_public_schema.begin() as connection:
        connection.execute(text(mutation))

    report = inspect_database()
    assert report.upgrade_allowed is False
    assert report.schema_candidate_revision is None
    assert any(
        not check.passed and check.name == failed_check
        for check in report.schema_checks
    ), report.to_dict()


def test_credentials_are_redacted_from_errors_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "migration-super-secret:/?#[]@!"
    monkeypatch.setattr("app.db.migration_safety.settings.DB_PASSWORD", password)
    monkeypatch.setattr("app.db.migration_safety.settings.DB_PORT", 1)

    report = inspect_database()
    rendered = json.dumps(report.to_dict(), default=str)
    raw_url = database_url().render_as_string(hide_password=False)
    error = safe_error(
        RuntimeError(
            f"{password} {quote(password, safe='')} {quote_plus(password)} {raw_url}"
        )
    )
    assert report.database_connected is False
    assert password not in error
    assert quote(password, safe="") not in error
    assert quote_plus(password) not in error
    assert raw_url not in error
    assert password not in rendered
    assert "postgresql" not in rendered
