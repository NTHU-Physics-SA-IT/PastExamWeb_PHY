import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models.models import (
    ArchiveReport,
    ArchiveSubmission,
    ArchiveType,
    ArchiveWishReport,
    CommentReport,
    SubmissionStatus,
    SystemIssueReport,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


@pytest.mark.asyncio
async def test_admin_attention_summary_uses_canonical_outstanding_states(
    client: AsyncClient,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    user = await make_user()
    unique = uuid.uuid4().hex
    now = datetime.now(UTC)
    created: dict[type, list[int]] = {}

    app.dependency_overrides[get_current_user] = _override_user(admin.id, is_admin=True)
    try:
        baseline = (await client.get("/admin/attention-summary")).json()
        async with session_maker() as session:
            rows = [
                ArchiveSubmission(
                    subject=f"New {unique}",
                    category="freshman",
                    name="Midterm",
                    academic_year=2026,
                    archive_type=ArchiveType.MIDTERM,
                    professor="Professor",
                    object_name=f"attention/{unique}-new.pdf",
                    requester_id=user.id,
                    requested_course_name=f"New {unique}",
                ),
                ArchiveSubmission(
                    subject=f"Existing {unique}",
                    category="freshman",
                    name="Final",
                    academic_year=2026,
                    archive_type=ArchiveType.FINAL,
                    professor="Professor",
                    object_name=f"attention/{unique}-existing.pdf",
                    requester_id=user.id,
                ),
                ArchiveSubmission(
                    subject=f"New category {unique}",
                    category="freshman",
                    name="Quiz",
                    academic_year=2026,
                    archive_type=ArchiveType.QUIZ,
                    professor="Professor",
                    object_name=f"attention/{unique}-new-category.pdf",
                    requester_id=user.id,
                    requested_category_key=f"category-{unique}",
                ),
                ArchiveSubmission(
                    subject=f"Final {unique}",
                    category="freshman",
                    name="Final",
                    academic_year=2026,
                    archive_type=ArchiveType.FINAL,
                    professor="Professor",
                    object_name=f"attention/{unique}-approved.pdf",
                    requester_id=user.id,
                    status=SubmissionStatus.APPROVED,
                ),
                ArchiveSubmission(
                    subject=f"Deleted pending {unique}",
                    category="freshman",
                    name="Quiz",
                    academic_year=2026,
                    archive_type=ArchiveType.QUIZ,
                    professor="Professor",
                    object_name=f"attention/{unique}-deleted.pdf",
                    requester_id=user.id,
                    deleted_at=now,
                ),
                ArchiveReport(
                    reporter_name_snapshot="Reporter",
                    archive_id_snapshot=10,
                    reason="other",
                    archive_name_snapshot=f"Archive {unique}",
                    course_name_snapshot="Course",
                    academic_year_snapshot=2026,
                    archive_type_snapshot="final",
                    professor_snapshot="Professor",
                ),
                ArchiveReport(
                    reporter_name_snapshot="Deleted reporter",
                    archive_id_snapshot=11,
                    reason="other",
                    archive_name_snapshot=f"Deleted archive {unique}",
                    course_name_snapshot="Course",
                    academic_year_snapshot=2026,
                    archive_type_snapshot="final",
                    professor_snapshot="Professor",
                    deleted_at=now,
                ),
                CommentReport(
                    reporter_user_id=user.id,
                    reason="other",
                    comment_content_snapshot=f"Comment {unique}",
                    comment_author_name_snapshot="Author",
                    comment_created_at_snapshot=now,
                    archive_name_snapshot="Archive",
                    course_name_snapshot="Course",
                ),
                CommentReport(
                    reporter_user_id=user.id,
                    reason="other",
                    comment_content_snapshot=f"Deleted comment {unique}",
                    comment_author_name_snapshot="Author",
                    comment_created_at_snapshot=now,
                    archive_name_snapshot="Archive",
                    course_name_snapshot="Course",
                    deleted_at=now,
                ),
                ArchiveWishReport(
                    reporter_user_id=user.id,
                    wish_title_snapshot=f"Wish {unique}",
                    target_summary_snapshot="Target",
                    reason="other",
                ),
                ArchiveWishReport(
                    reporter_user_id=user.id,
                    wish_title_snapshot=f"Reviewed wish {unique}",
                    target_summary_snapshot="Target",
                    reason="other",
                    status="dismissed",
                ),
                SystemIssueReport(
                    reporter_user_id=user.id,
                    report_type="bug",
                    title=f"Unread {unique}",
                    description="Unread issue",
                ),
                SystemIssueReport(
                    reporter_user_id=user.id,
                    report_type="bug",
                    title=f"Read {unique}",
                    description="Read issue",
                    read_at=now,
                    read_by_user_id=admin.id,
                ),
                SystemIssueReport(
                    reporter_user_id=user.id,
                    report_type="bug",
                    title=f"Deleted unread {unique}",
                    description="Deleted unread issue",
                    deleted_at=now,
                ),
            ]
            session.add_all(rows)
            await session.commit()
            for row in rows:
                await session.refresh(row)
                created.setdefault(type(row), []).append(row.id)

        summary = (await client.get("/admin/attention-summary")).json()
        assert summary["review_center"] == {
            "new_course_or_category": baseline["review_center"][
                "new_course_or_category"
            ]
            + 2,
            "existing_course": baseline["review_center"]["existing_course"] + 1,
            "total": baseline["review_center"]["total"] + 3,
        }
        assert summary["report_management"] == {
            "archive_reports": baseline["report_management"]["archive_reports"] + 1,
            "comment_reports": baseline["report_management"]["comment_reports"] + 1,
            "wish_reports": baseline["report_management"]["wish_reports"] + 1,
            "system_issues": baseline["report_management"]["system_issues"] + 1,
            "total": baseline["report_management"]["total"] + 4,
        }

        app.dependency_overrides[get_current_user] = _override_user(
            user.id, is_admin=False
        )
        assert (await client.get("/admin/attention-summary")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            for model, ids in created.items():
                await session.execute(delete(model).where(model.id.in_(ids)))
            await session.commit()
