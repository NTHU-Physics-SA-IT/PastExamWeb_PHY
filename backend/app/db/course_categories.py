"""Course-category keys, legacy aliases, and missing-row defaults."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefaultCourseCategoryDefinition:
    key: str
    name: str
    name_en: str
    label: str
    label_en: str
    icon: str
    badge_color: str
    order_index: int


DEFAULT_COURSE_CATEGORY_DEFINITIONS = (
    DefaultCourseCategoryDefinition(
        "fundamental",
        "基礎必修",
        "Foundation Courses",
        "基礎",
        "Foundation",
        "pi pi-fw pi-book",
        "navy",
        1,
    ),
    DefaultCourseCategoryDefinition(
        "required",
        "專業必修",
        "Required Major Courses",
        "必修",
        "Required",
        "pi pi-fw pi-compass",
        "forest",
        2,
    ),
    DefaultCourseCategoryDefinition(
        "optional",
        "專業選修",
        "Major Electives",
        "選修",
        "Elective",
        "pi pi-fw pi-book",
        "violet",
        3,
    ),
    DefaultCourseCategoryDefinition(
        "experience",
        "實驗課程",
        "Laboratory Courses",
        "實驗",
        "Laboratory",
        "pi pi-fw pi-sparkles",
        "amber",
        4,
    ),
    DefaultCourseCategoryDefinition(
        "graduate",
        "研究所",
        "Graduate Courses",
        "研究所",
        "Graduate",
        "pi pi-fw pi-graduation-cap",
        "burgundy",
        5,
    ),
    DefaultCourseCategoryDefinition(
        "math-department",
        "戳戳數學系",
        "Mathematics Courses",
        "數學",
        "Mathematics",
        "pi pi-fw pi-calculator",
        "slate",
        6,
    ),
)

CANONICAL_COURSE_CATEGORY_KEYS = frozenset(
    definition.key for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
)
DEFAULT_COURSE_CATEGORY_BY_KEY = {
    definition.key: definition
    for definition in DEFAULT_COURSE_CATEGORY_DEFINITIONS
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
