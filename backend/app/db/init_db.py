import asyncio
from datetime import datetime, timezone
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import yaml
from sqlmodel import func, select

from app.core.config import settings
from app.db.course_categories import (
    CANONICAL_COURSE_CATEGORIES,
    RESERVED_LEGACY_COURSE_CATEGORY_KEYS,
    normalize_course_category_name,
)
from app.db.migration_safety import MigrationReport, inspect_database
from app.db.session import AsyncSessionLocal
from app.models.models import Course, CourseCategory, CourseCategoryConfig, Meme, User
from app.utils.auth import get_password_hash
from app.utils.course_text import format_course_display_name

SEED_DATA_PATH = Path(__file__).with_name("seed_data.yaml")


@lru_cache(maxsize=1)
def load_seed_data():
    with SEED_DATA_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _seed_course_key(course: Course) -> tuple[str, str]:
    category = getattr(course.category, "value", course.category)
    return (str(category), format_course_display_name(course.name))


async def sync_course_catalog(session):
    seed_courses = [
        (
            course["category"],
            format_course_display_name(course["name"]),
        )
        for course in load_seed_data().get("courses", [])
    ]

    result = await session.execute(select(Course))
    existing_courses = result.scalars().all()
    changed = False
    for course in existing_courses:
        formatted_name = format_course_display_name(course.name)
        if formatted_name != course.name:
            course.name = formatted_name
            changed = True
    courses_by_key: dict[tuple[str, str], list[Course]] = {}
    for course in existing_courses:
        courses_by_key.setdefault(_seed_course_key(course), []).append(course)
    seed_order_by_key = {}
    category_positions = defaultdict(int)
    for category_name, course_name in seed_courses:
        category = CourseCategory[category_name]
        seed_order_by_key[(category.value, course_name)] = category_positions[category.value]
        category_positions[category.value] += 1

    active_courses_by_category = defaultdict(list)
    for course in existing_courses:
        if course.deleted_at is None:
            category = getattr(course.category, "value", course.category)
            active_courses_by_category[category].append(course)

    should_initialize_order = {
        category: all(course.order_index == 0 for course in courses)
        for category, courses in active_courses_by_category.items()
    }

    for category_name, course_name in seed_courses:
        category = CourseCategory[category_name]
        key = (category.value, course_name)
        matching_courses = courses_by_key.get(key, [])
        if matching_courses:
            primary, *duplicates = matching_courses
            if primary.deleted_at is not None:
                primary.deleted_at = None
                changed = True
            if should_initialize_order.get(category.value, True):
                expected_order = seed_order_by_key[key]
                if primary.order_index != expected_order:
                    primary.order_index = expected_order
                    changed = True
            for duplicate in duplicates:
                if duplicate.deleted_at is None:
                    duplicate.deleted_at = datetime.now(timezone.utc)
                    changed = True
            continue

        session.add(
            Course(
                name=course_name,
                category=category.value,
                order_index=seed_order_by_key[key],
            )
        )
        changed = True

    if changed:
        await session.commit()


async def sync_course_categories(session):
    result = await session.execute(select(CourseCategoryConfig))
    existing_categories = result.scalars().all()
    legacy_keys = sorted(
        category.key
        for category in existing_categories
        if category.key.strip().lower() in RESERVED_LEGACY_COURSE_CATEGORY_KEYS
    )
    if legacy_keys:
        raise RuntimeError(
            "Legacy course categories remain in the database; "
            "run the canonicalization migration before bootstrapping"
        )

    existing_by_key = {category.key: category for category in existing_categories}
    existing_by_name = {
        normalize_course_category_name(category.name): category
        for category in existing_categories
    }
    changed = False

    for definition in CANONICAL_COURSE_CATEGORIES:
        category = existing_by_key.get(definition.key)
        if category:
            continue
        name_conflict = existing_by_name.get(
            normalize_course_category_name(definition.name)
        )
        if name_conflict:
            raise RuntimeError(
                "Course category name already exists under a different key: "
                f"{definition.name}"
            )

        session.add(
            CourseCategoryConfig(
                key=definition.key,
                name=definition.name,
                label=definition.label,
                icon=definition.icon,
                badge_color=definition.badge_color,
                order_index=definition.order_index,
                is_active=True,
            )
        )
        changed = True

    if changed:
        await session.commit()


def _startup_readiness_errors(report: MigrationReport) -> list[str]:
    errors = list(report.errors)
    if not report.database_connected:
        errors.append("database connection failed")
    if report.multiple_heads:
        errors.append("repository has multiple Alembic heads")
    if not report.alembic_version_exists:
        errors.append("Alembic ledger is missing")
    if len(report.alembic_versions) != 1:
        errors.append("Alembic ledger must contain exactly one revision")
    if (
        len(report.repository_heads) == 1
        and report.current_revision != report.repository_heads[0]
    ):
        errors.append("database migration is not at repository head")
    if report.current_revision == (
        report.repository_heads[0] if len(report.repository_heads) == 1 else None
    ) and not report.schema_matches_head:
        errors.append("database schema does not match repository head")
    return list(dict.fromkeys(errors))


def validate_database_ready() -> MigrationReport:
    """Fail fast without migrating, creating tables, or seeding data."""
    report = inspect_database()
    errors = _startup_readiness_errors(report)
    if errors:
        raise RuntimeError(
            "Database startup check failed: "
            + "; ".join(errors)
            + ". Run the explicit migration preflight/upgrade command."
        )
    return report


async def init_db() -> None:
    """Read-only startup compatibility check retained as the app hook."""
    await asyncio.to_thread(validate_database_ready)


async def bootstrap_db(*, confirmed_database_name: str) -> None:
    """Explicitly seed an already-migrated database; never called at startup."""
    if not settings.ALLOW_DATABASE_BOOTSTRAP:
        raise RuntimeError(
            "Database bootstrap is disabled; set ALLOW_DATABASE_BOOTSTRAP=true "
            "only for an explicitly confirmed local or isolated test database"
        )
    if confirmed_database_name != settings.DB_NAME:
        raise RuntimeError(
            "Explicit bootstrap confirmation does not match the configured database"
        )
    await asyncio.to_thread(validate_database_ready)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.name == settings.DEFAULT_ADMIN_NAME)
        )
        admin_user = result.scalar_one_or_none()

        if admin_user and getattr(admin_user, "deleted_at", None) is not None:
            admin_user.deleted_at = None
            admin_user.password_hash = get_password_hash(
                settings.DEFAULT_ADMIN_PASSWORD
            )
            admin_user.is_local = True
            admin_user.is_admin = True
            await session.commit()
            await session.refresh(admin_user)
        elif not admin_user:
            admin_user = User(
                name=settings.DEFAULT_ADMIN_NAME,
                email=settings.DEFAULT_ADMIN_EMAIL,
                password_hash=get_password_hash(settings.DEFAULT_ADMIN_PASSWORD),
                is_local=True,
                is_admin=True,
            )
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)

        await sync_course_categories(session)
        await sync_course_catalog(session)

        result = await session.execute(select(func.count()).select_from(Meme))
        count = result.scalar()
        if count == 0:
            seed_data = load_seed_data()
            initial_memes = [
                Meme(
                    content=meme["content"],
                    language=meme["language"],
                )
                for meme in seed_data.get("memes", [])
            ]
            session.add_all(initial_memes)
            await session.commit()


async def get_session():
    """
    Database dependency for FastAPI endpoints.
    """
    async with AsyncSessionLocal() as session:
        yield session
