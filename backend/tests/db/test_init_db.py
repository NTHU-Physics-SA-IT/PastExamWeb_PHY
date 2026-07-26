from contextlib import asynccontextmanager

import pytest

from app.core.config import settings
from app.db import init_db
from app.db.course_categories import CANONICAL_COURSE_CATEGORIES
from app.db.migration_safety import CheckResult, MigrationReport
from app.models.models import Course, CourseCategory, CourseCategoryConfig, Meme, User
from app.utils.auth import verify_password


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
        category_configs=None,
        courses=None,
        meme_count=0,
    ):
        self.admin = (
            User(
                name=settings.DEFAULT_ADMIN_NAME,
                email=settings.DEFAULT_ADMIN_EMAIL,
            )
            if admin_exists
            else None
        )
        self.category_configs = list(category_configs or [])
        self.courses = list(courses or [])
        self.meme_count = meme_count
        self.added_courses: list[Course] = []
        self.added_category_configs: list[CourseCategoryConfig] = []
        self.added_memes: list[Meme] = []
        self.execute_step = 0
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query):
        values = (
            self.admin,
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
        item.key for item in CANONICAL_COURSE_CATEGORIES
    ]
    assert len(fake_session.added_courses) == 2
    assert len(fake_session.added_memes) == 1


@pytest.mark.asyncio
async def test_category_seed_is_idempotent_and_rejects_legacy_keys():
    fake_session = FakeSession()
    for _ in range(10):
        fake_session.execute_step = 1
        await init_db.sync_course_categories(fake_session)

    assert len(fake_session.category_configs) == 6
    assert {item.key for item in fake_session.category_configs} == {
        item.key for item in CANONICAL_COURSE_CATEGORIES
    }

    legacy_session = FakeSession(
        category_configs=[
            CourseCategoryConfig(
                key="freshman",
                name="基礎必修",
            )
        ]
    )
    legacy_session.execute_step = 1
    with pytest.raises(RuntimeError, match="Legacy course categories"):
        await init_db.sync_course_categories(legacy_session)


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
