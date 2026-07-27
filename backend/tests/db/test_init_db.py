from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.db import init_db
from app.db.course_categories import (
    CANONICAL_COURSE_CATEGORY_KEYS,
    DEFAULT_COURSE_CATEGORY_DEFINITIONS,
)
from app.db.migration_safety import CheckResult, MigrationReport
from app.models.models import (
    Course,
    CourseCategory,
    CourseCategoryConfig,
    Meme,
    SystemSetting,
    User,
)
from app.utils.auth import get_password_hash, verify_password


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class FakeSession:
    def __init__(
        self,
        *,
        admin_exists=False,
        admin=None,
        email_owner=None,
        category_configs=None,
        courses=None,
        meme_count=0,
        query_values=None,
    ):
        self.admin = admin or (
            User(
                name=settings.DEFAULT_ADMIN_NAME,
                email=settings.DEFAULT_ADMIN_EMAIL,
            )
            if admin_exists
            else None
        )
        self.email_owner = email_owner
        self.category_configs = list(category_configs or [])
        self.courses = list(courses or [])
        self.meme_count = meme_count
        self.added_courses: list[Course] = []
        self.added_category_configs: list[CourseCategoryConfig] = []
        self.added_memes: list[Meme] = []
        self.added_settings: list[SystemSetting] = []
        self.execute_step = 0
        self.commits = 0
        self.query_values = query_values

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query):
        values = self.query_values or (
            self.admin,
            self.email_owner,
            self.category_configs,
            self.courses,
            self.meme_count,
        )
        if self.execute_step >= len(values):
            raise AssertionError("Unexpected execute call")
        value = values[self.execute_step]
        self.execute_step += 1
        return FakeScalarResult(value)

    def add(self, obj):
        if isinstance(obj, User):
            self.admin = obj
        elif isinstance(obj, Course):
            self.added_courses.append(obj)
        elif isinstance(obj, CourseCategoryConfig):
            self.added_category_configs.append(obj)
            self.category_configs.append(obj)
        elif isinstance(obj, SystemSetting):
            self.added_settings.append(obj)

    def add_all(self, objs):
        for obj in objs:
            if isinstance(obj, Course):
                self.added_courses.append(obj)
            elif isinstance(obj, Meme):
                self.added_memes.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


def ready_report() -> MigrationReport:
    return MigrationReport(
        database_connected=True,
        database_empty=False,
        alembic_version_exists=True,
        alembic_versions=["head"],
        current_revision="head",
        current_revision_known=True,
        repository_heads=["head"],
        schema_checks=[CheckResult("schema", True, "OK")],
        upgrade_allowed=True,
    )


@pytest.mark.asyncio
async def test_startup_fails_fast_when_migration_is_missing(monkeypatch):
    report = MigrationReport(
        database_connected=True,
        database_empty=True,
        alembic_version_exists=False,
        repository_heads=["head"],
        upgrade_allowed=True,
    )
    monkeypatch.setattr(init_db, "inspect_database", lambda: report)

    with pytest.raises(RuntimeError, match="Alembic ledger is missing"):
        await init_db.init_db()


@pytest.mark.asyncio
async def test_explicit_bootstrap_creates_admin_and_canonical_seed(monkeypatch):
    seed_payload = {
        "courses": [
            {"name": "Seed Course A", "category": CourseCategory.FRESHMAN.name},
            {"name": "Seed Course B", "category": CourseCategory.GRADUATE.name},
        ],
        "memes": [{"content": "Study hard!", "language": "en"}],
    }
    fake_session = FakeSession()

    @asynccontextmanager
    async def fake_session_factory():
        async with fake_session:
            yield fake_session

    monkeypatch.setattr(init_db, "validate_database_ready", ready_report)
    monkeypatch.setattr(init_db, "load_seed_data", lambda: seed_payload)
    monkeypatch.setattr(init_db, "AsyncSessionLocal", fake_session_factory)
    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", True)
    monkeypatch.setattr(settings, "DB_NAME", "archive_db_dev_unit")

    async def empty_database(_session):
        return True

    monkeypatch.setattr(
        init_db,
        "_validate_bootstrap_contents",
        empty_database,
    )

    await init_db.bootstrap_db(
        confirmed_database_name=settings.DB_NAME,
    )

    assert fake_session.admin is not None
    assert verify_password(
        settings.DEFAULT_ADMIN_PASSWORD,
        fake_session.admin.password_hash,
    )
    assert [item.key for item in fake_session.added_category_configs] == [
        item.key for item in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    ]
    assert len(fake_session.added_courses) == 2
    assert len(fake_session.added_memes) == 1
    assert [item.key for item in fake_session.added_settings] == [
        init_db.BOOTSTRAP_MARKER_KEY
    ]


@pytest.mark.asyncio
async def test_category_seed_is_idempotent_and_rejects_legacy_keys():
    fake_session = FakeSession()
    for _ in range(10):
        fake_session.execute_step = 2
        await init_db.sync_course_categories(fake_session)

    assert len(fake_session.category_configs) == 6
    assert {item.key for item in fake_session.category_configs} == {
        item.key for item in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    }

    legacy_session = FakeSession(
        category_configs=[
            CourseCategoryConfig(
                key="freshman",
                name="基礎必修",
            )
        ]
    )
    legacy_session.execute_step = 2
    with pytest.raises(RuntimeError, match="Legacy course categories"):
        await init_db.sync_course_categories(legacy_session)


@pytest.mark.asyncio
async def test_category_seed_preserves_managed_and_custom_rows_and_fills_missing():
    categories = [
        CourseCategoryConfig(
            key=definition.key,
            name=(
                "管理員自訂數學分類"
                if definition.key == "math-department"
                else definition.name
            ),
            label=definition.label,
            icon=definition.icon,
            badge_color=definition.badge_color,
            order_index=definition.order_index,
            is_active=definition.key != "math-department",
        )
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
        if definition.key != "required"
    ]
    custom = CourseCategoryConfig(
        key="web-development",
        name="網站架設",
        label="網站",
        icon="custom-web-icon",
        badge_color="forest",
        order_index=99,
        is_active=False,
    )
    categories.append(custom)
    math_category = next(
        category
        for category in categories
        if category.key == "math-department"
    )
    before_math = math_category.model_dump()
    before_custom = custom.model_dump()
    fake_session = FakeSession(
        category_configs=categories,
        query_values=[categories],
    )

    await init_db.sync_course_categories(fake_session)

    assert [item.key for item in fake_session.added_category_configs] == [
        "required"
    ]
    assert math_category.model_dump() == before_math
    assert custom.model_dump() == before_custom
    assert {
        category.key for category in fake_session.category_configs
    } == CANONICAL_COURSE_CATEGORY_KEYS | {"web-development"}


@pytest.mark.asyncio
async def test_math_default_name_is_used_only_when_row_is_missing():
    categories = [
        CourseCategoryConfig(
            key=definition.key,
            name=definition.name,
            label=definition.label,
            icon=definition.icon,
            badge_color=definition.badge_color,
            order_index=definition.order_index,
        )
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
        if definition.key != "math-department"
    ]
    fake_session = FakeSession(
        category_configs=categories,
        query_values=[categories],
    )

    await init_db.sync_course_categories(fake_session)

    assert len(fake_session.added_category_configs) == 1
    assert fake_session.added_category_configs[0].key == "math-department"
    assert fake_session.added_category_configs[0].name == "戳戳數學系"


@pytest.mark.asyncio
async def test_first_bootstrap_rejects_missing_category_before_writes(
    monkeypatch,
):
    categories = [
        CourseCategoryConfig(key=definition.key, name=definition.name)
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS[:-1]
    ]
    fake_session = FakeSession(query_values=[None, categories])

    @asynccontextmanager
    async def fake_session_factory():
        async with fake_session:
            yield fake_session

    monkeypatch.setattr(init_db, "validate_database_ready", ready_report)
    monkeypatch.setattr(init_db, "AsyncSessionLocal", fake_session_factory)
    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", True)
    monkeypatch.setattr(settings, "DB_NAME", "archive_db_dev_missing_category")

    with pytest.raises(RuntimeError, match="six migration-created"):
        await init_db.bootstrap_db(
            confirmed_database_name=settings.DB_NAME,
        )

    assert fake_session.admin is None
    assert fake_session.added_category_configs == []
    assert fake_session.added_settings == []
    assert fake_session.commits == 0


@pytest.mark.asyncio
async def test_first_bootstrap_accepts_only_six_categories_and_empty_tables():
    categories = [
        CourseCategoryConfig(key=definition.key, name=definition.name)
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    ]
    fake_session = FakeSession(
        query_values=[None, categories, *([0] * 11)],
    )

    assert await init_db._validate_bootstrap_contents(fake_session) is True


@pytest.mark.asyncio
async def test_first_bootstrap_rejects_extra_custom_category():
    categories = _canonical_category_models()
    categories.append(
        CourseCategoryConfig(
            key="web-development",
            name="網站架設",
        )
    )
    fake_session = FakeSession(query_values=[None, categories])

    with pytest.raises(RuntimeError, match="only the six"):
        await init_db._validate_bootstrap_contents(fake_session)


@pytest.mark.asyncio
async def test_later_bootstrap_fails_on_default_name_under_custom_key():
    categories = [
        category
        for category in _canonical_category_models()
        if category.key != "math-department"
    ]
    categories.append(
        CourseCategoryConfig(
            key="custom-math",
            name="戳戳數學系",
        )
    )
    fake_session = FakeSession(
        category_configs=categories,
        query_values=[categories],
    )

    with pytest.raises(RuntimeError, match="different key"):
        await init_db.sync_course_categories(fake_session)

    assert fake_session.added_category_configs == []


def _configure_bootstrap_test(monkeypatch, fake_session: FakeSession) -> None:
    @asynccontextmanager
    async def fake_session_factory():
        async with fake_session:
            yield fake_session

    async def later_bootstrap(_session):
        return False

    monkeypatch.setattr(init_db, "validate_database_ready", ready_report)
    monkeypatch.setattr(init_db, "_validate_bootstrap_contents", later_bootstrap)
    monkeypatch.setattr(init_db, "AsyncSessionLocal", fake_session_factory)
    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", True)
    monkeypatch.setattr(settings, "DB_NAME", "archive_db_dev_admin_test")


def _canonical_category_models() -> list[CourseCategoryConfig]:
    return [
        CourseCategoryConfig(
            key=definition.key,
            name=definition.name,
            label=definition.label,
            icon=definition.icon,
            badge_color=definition.badge_color,
            order_index=definition.order_index,
        )
        for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
    ]


@pytest.mark.asyncio
async def test_existing_default_admin_credentials_are_not_changed(monkeypatch):
    original_hash = get_password_hash("administrator-managed-password")
    admin = User(
        name=settings.DEFAULT_ADMIN_NAME,
        email="administrator-managed@example.invalid",
        password_hash=original_hash,
        is_local=False,
        is_admin=True,
    )
    categories = _canonical_category_models()
    fake_session = FakeSession(
        admin=admin,
        category_configs=categories,
        query_values=[admin, categories, [], 1],
    )
    _configure_bootstrap_test(monkeypatch, fake_session)

    await init_db.bootstrap_db(
        confirmed_database_name=settings.DB_NAME,
    )

    assert admin.password_hash == original_hash
    assert admin.email == "administrator-managed@example.invalid"
    assert admin.is_local is False


@pytest.mark.asyncio
async def test_soft_deleted_default_admin_is_restored_and_password_reset(
    monkeypatch,
):
    old_hash = get_password_hash("old-password")
    admin = User(
        name=settings.DEFAULT_ADMIN_NAME,
        email=settings.DEFAULT_ADMIN_EMAIL,
        password_hash=old_hash,
        is_local=False,
        is_admin=False,
        deleted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    categories = _canonical_category_models()
    fake_session = FakeSession(
        admin=admin,
        category_configs=categories,
        query_values=[admin, categories, [], 1],
    )
    _configure_bootstrap_test(monkeypatch, fake_session)

    await init_db.bootstrap_db(
        confirmed_database_name=settings.DB_NAME,
    )

    assert admin.deleted_at is None
    assert admin.password_hash != old_hash
    assert verify_password(settings.DEFAULT_ADMIN_PASSWORD, admin.password_hash)
    assert admin.is_local is True
    assert admin.is_admin is True


@pytest.mark.asyncio
async def test_missing_default_admin_is_created(monkeypatch):
    categories = _canonical_category_models()
    fake_session = FakeSession(
        category_configs=categories,
        query_values=[None, None, categories, [], 1],
    )
    _configure_bootstrap_test(monkeypatch, fake_session)

    await init_db.bootstrap_db(
        confirmed_database_name=settings.DB_NAME,
    )

    assert fake_session.admin is not None
    assert fake_session.admin.name == settings.DEFAULT_ADMIN_NAME
    assert verify_password(
        settings.DEFAULT_ADMIN_PASSWORD,
        fake_session.admin.password_hash,
    )


@pytest.mark.asyncio
async def test_renamed_admin_email_collision_fails_without_mutation(monkeypatch):
    original_hash = get_password_hash("renamed-admin-password")
    email_owner = User(
        name="Renamed administrator",
        email=settings.DEFAULT_ADMIN_EMAIL,
        password_hash=original_hash,
        is_local=True,
        is_admin=True,
    )
    fake_session = FakeSession(
        email_owner=email_owner,
        query_values=[None, email_owner],
    )
    _configure_bootstrap_test(monkeypatch, fake_session)

    with pytest.raises(RuntimeError, match="email is already used"):
        await init_db.bootstrap_db(
            confirmed_database_name=settings.DB_NAME,
        )

    assert email_owner.password_hash == original_hash
    assert fake_session.admin is None
    assert fake_session.commits == 0


@pytest.mark.asyncio
async def test_bootstrap_requires_explicit_flag_and_exact_database_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", False)
    with pytest.raises(RuntimeError, match="disabled"):
        await init_db.bootstrap_db(
            confirmed_database_name=settings.DB_NAME,
        )

    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", True)
    with pytest.raises(RuntimeError, match="confirmation"):
        await init_db.bootstrap_db(
            confirmed_database_name=f"{settings.DB_NAME}_wrong",
        )


@pytest.mark.asyncio
async def test_bootstrap_rejects_normal_and_production_database_names(
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_DATABASE_BOOTSTRAP", True)
    for database_name in ("archive_db", "archive_db_production"):
        monkeypatch.setattr(settings, "DB_NAME", database_name)
        with pytest.raises(RuntimeError, match="dev/test"):
            await init_db.bootstrap_db(
                confirmed_database_name=database_name,
            )
