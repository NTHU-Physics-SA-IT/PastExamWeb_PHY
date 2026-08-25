from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from app.db.migration_safety import revision_graph
from app.db.schema_manifests import HEAD_SCHEMA_REVISION
from app.models.models import HomepageSloganSubmission


def test_homepage_slogan_migration_is_the_additive_schema_head() -> None:
    script = revision_graph()
    assert HEAD_SCHEMA_REVISION == "e2c6a8f4b1d9"
    assert script.get_heads() == [HEAD_SCHEMA_REVISION]
    assert script.get_revision(HEAD_SCHEMA_REVISION).down_revision == "d1f5a9c3e7b2"

    table = HomepageSloganSubmission.__table__
    assert tuple(table.c.keys()) == (
        "id",
        "content",
        "submitter_user_id",
        "submitter_name_snapshot",
        "status",
        "occurrence_level",
        "reviewer_user_id",
        "reviewed_at",
        "created_at",
        "updated_at",
    )
    assert table.c.content.type.length == 80
    assert table.c.submitter_user_id.nullable is True
    assert table.c.reviewer_user_id.nullable is True
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_homepage_slogan_submissions_occurrence_level",
        "ck_homepage_slogan_submissions_status",
    }
    assert {
        tuple(constraint.columns.keys()): constraint.ondelete
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    } == {
        ("submitter_user_id",): "SET NULL",
        ("reviewer_user_id",): "SET NULL",
    }
