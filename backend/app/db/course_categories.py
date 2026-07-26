"""Canonical course-category definitions and normalization rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalCourseCategory:
    key: str
    name: str
    label: str
    icon: str
    badge_color: str
    order_index: int


CANONICAL_COURSE_CATEGORIES = (
    CanonicalCourseCategory(
        "fundamental",
        "基礎必修",
        "基礎",
        "pi pi-fw pi-book",
        "navy",
        1,
    ),
    CanonicalCourseCategory(
        "required",
        "專業必修",
        "必修",
        "pi pi-fw pi-compass",
        "forest",
        2,
    ),
    CanonicalCourseCategory(
        "experience",
        "實驗課程",
        "實驗",
        "pi pi-fw pi-sparkles",
        "amber",
        3,
    ),
    CanonicalCourseCategory(
        "optional",
        "專業選修",
        "選修",
        "pi pi-fw pi-book",
        "violet",
        4,
    ),
    CanonicalCourseCategory(
        "graduate",
        "研究所",
        "研究所",
        "pi pi-fw pi-graduation-cap",
        "burgundy",
        5,
    ),
    CanonicalCourseCategory(
        "math-department",
        "跨群數學系",
        "數學",
        "pi pi-fw pi-calculator",
        "slate",
        6,
    ),
)

CANONICAL_COURSE_CATEGORY_BY_KEY = {
    category.key: category for category in CANONICAL_COURSE_CATEGORIES
}
LEGACY_COURSE_CATEGORY_ALIASES = {
    "freshman": "fundamental",
    "sophomore": "required",
    "junior": "experience",
    "senior": "optional",
    "interdisciplinary": "math-department",
}
RESERVED_LEGACY_COURSE_CATEGORY_KEYS = frozenset(
    LEGACY_COURSE_CATEGORY_ALIASES
)


def normalize_course_category_key(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def normalize_course_category_name(value: str) -> str:
    return value.strip().lower()


def canonicalize_course_category_key(value: str) -> str:
    normalized = normalize_course_category_key(value)
    return LEGACY_COURSE_CATEGORY_ALIASES.get(normalized, normalized)
