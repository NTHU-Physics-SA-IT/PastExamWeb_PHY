"""Deterministic content precondition for ArchiveSubmission moderation."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from app.db.course_categories import canonicalize_course_category_key
from app.utils.course_text import normalize_first_course_search_text

REVIEW_REVISION_PREFIX = "asr-v1:"

_CONTENT_FIELDS = (
    "id",
    "object_name",
    "subject",
    "category",
    "name",
    "academic_year",
    "archive_type",
    "professor",
    "has_answers",
    "requested_course_name",
    "requested_course_name_en",
    "requested_category_key",
    "requested_category_name",
    "requested_category_name_en",
    "requested_category_label",
    "requested_category_label_en",
    "requested_category_icon",
    "source_wish_id",
    "created_archive_id",
    "requester_id",
    "owner_id",
)


def _value(source: object | Mapping[str, Any], field: str) -> Any:
    if isinstance(source, Mapping):
        value = source.get(field)
    else:
        value = getattr(source, field, None)
    return getattr(value, "value", value)


def review_revision_payload(source: object | Mapping[str, Any]) -> dict[str, Any]:
    payload = {field: _value(source, field) for field in _CONTENT_FIELDS}
    category = payload["requested_category_key"] or payload["category"] or ""
    payload["effective_approval_target"] = {
        "category": canonicalize_course_category_key(str(category)),
        "course": normalize_first_course_search_text(
            payload["requested_course_name"],
            payload["subject"],
        ),
    }
    return payload


def compute_archive_submission_review_revision(
    source: object | Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        review_revision_payload(source),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{REVIEW_REVISION_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def review_revision_matches(expected: str, current: str) -> bool:
    return hmac.compare_digest(expected, current)
