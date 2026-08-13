"""Shared course-name normalization helpers for display and search."""

import re

from sqlalchemy import func

COURSE_PARENTHESIS_HALF_TO_FULL = str.maketrans({"(": "（", ")": "）"})
COURSE_PARENTHESIS_FULL_TO_HALF = str.maketrans({"（": "(", "）": ")"})


def format_course_display_name(value: str | None) -> str:
    if not value:
        return ""
    return str(value).translate(COURSE_PARENTHESIS_FULL_TO_HALF).strip()


def normalize_course_search_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).translate(COURSE_PARENTHESIS_FULL_TO_HALF)
    normalized = normalized.strip().lower()
    normalized = re.sub(r"[\s\u3000]+", "", normalized)
    normalized = normalized.replace("(", "").replace(")", "")
    return normalized


def normalize_first_course_search_text(*values: str | None) -> str:
    for value in values:
        normalized = normalize_course_search_text(value)
        if normalized:
            return normalized
    return ""


def _normalize_course_search_expression(value):
    expression = func.lower(func.trim(value))
    expression = func.replace(expression, "（", "(")
    expression = func.replace(expression, "）", ")")
    expression = func.replace(expression, "\u3000", "")
    expression = func.replace(expression, " ", "")
    expression = func.replace(expression, "\t", "")
    expression = func.replace(expression, "\n", "")
    expression = func.replace(expression, "(", "")
    expression = func.replace(expression, ")", "")
    return expression


def normalized_course_text_expr(*values):
    if not values:
        return func.lower("")

    normalized_values = [
        func.nullif(_normalize_course_search_expression(value), "") for value in values
    ]
    return func.coalesce(*normalized_values, "")
