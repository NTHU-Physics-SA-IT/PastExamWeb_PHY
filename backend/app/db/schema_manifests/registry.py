"""Registry of schema revisions reviewed for automatic forward migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


HEAD_SCHEMA_REVISION = "a7c3e9f1b5d2"


@dataclass(frozen=True)
class ManifestSpec:
    revision: str
    description: str
    metadata_variant: str | None = None
    snapshot_file: str | None = None
    retained_enums: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def snapshot_path(self) -> Path | None:
        if self.snapshot_file is None:
            return None
        return Path(__file__).with_name(self.snapshot_file)


_COURSE_CATEGORY_ENUM = (
    (
        "coursecategory",
        (
            "FRESHMAN",
            "SOPHOMORE",
            "JUNIOR",
            "SENIOR",
            "GRADUATE",
            "INTERDISCIPLINARY",
            "GENERAL",
        ),
    ),
)


MANIFESTS = {
    "c4d8e2f1a6b9": ManifestSpec(
        revision="c4d8e2f1a6b9",
        description="2026-07-12 recovery dump revision",
        snapshot_file="c4d8e2f1a6b9.json",
    ),
    "a4c7e9d2f6b1": ManifestSpec(
        revision="a4c7e9d2f6b1",
        description="pre-category-canonicalization test baseline",
        metadata_variant="pre_category_canonicalization",
        retained_enums=_COURSE_CATEGORY_ENUM,
    ),
    "c9e4f1a7b2d6": ManifestSpec(
        revision="c9e4f1a7b2d6",
        description="canonical category schema before metadata drift alignment",
        metadata_variant="pre_metadata_alignment",
        retained_enums=_COURSE_CATEGORY_ENUM,
    ),
    "e3b7c1d9f5a2": ManifestSpec(
        revision="e3b7c1d9f5a2",
        description="schema before archive report workflow",
        metadata_variant="pre_archive_reports",
    ),
    HEAD_SCHEMA_REVISION: ManifestSpec(
        revision=HEAD_SCHEMA_REVISION,
        description="current SQLModel metadata contract",
        metadata_variant="head",
    ),
}


def get_manifest_spec(revision: str | None) -> ManifestSpec | None:
    if revision is None:
        return None
    return MANIFESTS.get(revision)


def reviewed_manifest_revisions() -> tuple[str, ...]:
    return tuple(MANIFESTS)
