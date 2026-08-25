"""Registry of schema revisions reviewed for automatic forward migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ARCHIVE_REPORT_PREVIOUS_SCHEMA_REVISION = "c7e4a9b2d6f1"
WISH_REPORT_PREVIOUS_SCHEMA_REVISION = "c8e4a1f7b2d9"
PREVIOUS_HEAD_SCHEMA_REVISION = "d1f5a9c3e7b2"
HEAD_SCHEMA_REVISION = "e2c6a8f4b1d9"


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
    "a7c3e9f1b5d2": ManifestSpec(
        revision="a7c3e9f1b5d2",
        description="schema before archive submission self-delete eligibility",
        metadata_variant="pre_owner_self_delete_eligibility",
    ),
    "f5e1d8c3a7b2": ManifestSpec(
        revision="f5e1d8c3a7b2",
        description="schema before archive submission previous status",
        metadata_variant="pre_archive_submission_previous_status",
    ),
    "d8f2a6c1b4e7": ManifestSpec(
        revision="d8f2a6c1b4e7",
        description="schema before ArchiveSubmission one-to-one links",
        metadata_variant="pre_archive_submission_one_to_one",
    ),
    "6f3a9c2d8e41": ManifestSpec(
        revision="6f3a9c2d8e41",
        description="schema before NTHU OAuth identity uniqueness",
        metadata_variant="pre_user_oauth_identity_unique",
    ),
    "9f1c2a7e4b63": ManifestSpec(
        revision="9f1c2a7e4b63",
        description="schema before persisted NTHU student ID",
        metadata_variant="pre_nthu_student_id",
    ),
    "b7e3d9a1c5f2": ManifestSpec(
        revision="b7e3d9a1c5f2",
        description="schema before bilingual course catalog fields",
        metadata_variant="pre_bilingual_course_catalog",
    ),
    "c2a8e4f6b9d1": ManifestSpec(
        revision="c2a8e4f6b9d1",
        description="schema before bilingual archive submission snapshots",
        metadata_variant="pre_bilingual_submission_snapshots",
    ),
    "d4b7e2a9c6f1": ManifestSpec(
        revision="d4b7e2a9c6f1",
        description="schema before About Us entries",
        metadata_variant="pre_about_us_entries",
    ),
    "e6a1b3c5d7f9": ManifestSpec(
        revision="e6a1b3c5d7f9",
        description="schema before both reviewed sibling branches",
        metadata_variant="pre_sibling_branches",
    ),
    "e8a4c1d7b2f6": ManifestSpec(
        revision="e8a4c1d7b2f6",
        description="schema before CourseSubmission lifecycle independence",
        metadata_variant="pre_course_submission_lifecycle",
    ),
    "a9c2e5f7b1d4": ManifestSpec(
        revision="a9c2e5f7b1d4",
        description="Stage 5D sibling head before Wish Pool convergence",
        metadata_variant="coordination_sibling_head",
    ),
    "a9c4e7b2d6f1": ManifestSpec(
        revision="a9c4e7b2d6f1",
        description="Wish Pool sibling head before Stage 5D convergence",
        metadata_variant="main_sibling_head",
    ),
    "b4d6f8a2c1e3": ManifestSpec(
        revision="b4d6f8a2c1e3",
        description="schema before optional Wish academic year",
        metadata_variant="pre_wish_optional_semester",
    ),
    "f3a7c1e9d5b2": ManifestSpec(
        revision="f3a7c1e9d5b2",
        description="schema before persisted About Us ordering",
        metadata_variant="pre_about_us_ordering",
    ),
    ARCHIVE_REPORT_PREVIOUS_SCHEMA_REVISION: ManifestSpec(
        revision=ARCHIVE_REPORT_PREVIOUS_SCHEMA_REVISION,
        description="schema before active-pending ArchiveReport uniqueness",
        metadata_variant="pre_archive_report_active_pending_uniqueness",
    ),
    WISH_REPORT_PREVIOUS_SCHEMA_REVISION: ManifestSpec(
        revision=WISH_REPORT_PREVIOUS_SCHEMA_REVISION,
        description="schema before ArchiveWishReport trash metadata",
        metadata_variant="pre_archive_wish_report_trash_metadata",
    ),
    PREVIOUS_HEAD_SCHEMA_REVISION: ManifestSpec(
        revision=PREVIOUS_HEAD_SCHEMA_REVISION,
        description="schema before homepage slogan submissions",
        metadata_variant="pre_homepage_slogan_submissions",
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
