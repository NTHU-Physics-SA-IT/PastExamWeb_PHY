"""Canonical Archive Wish matching and fulfillment side effects."""

from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    Archive,
    ArchiveWish,
    ArchiveWishCreate,
    Course,
    PersonalNotificationType,
)
from app.services.archive_visibility import public_archive_conditions
from app.services.personal_notifications import enqueue_personal_notification
from app.utils.course_text import (
    normalize_course_search_text,
    normalized_course_text_expr,
)


def _normalized_text_expr(value):
    return func.lower(func.trim(func.coalesce(value, "")))


def _wish_course_matches_archive():
    return or_(
        (ArchiveWish.course_id.is_not(None)) & (Archive.course_id == ArchiveWish.course_id),
        (ArchiveWish.course_id.is_(None))
        & (
            normalized_course_text_expr(Course.name)
            == normalized_course_text_expr(
                ArchiveWish.requested_course_name, ArchiveWish.subject
            )
        )
        & (
            _normalized_text_expr(Course.category)
            == _normalized_text_expr(
                func.coalesce(ArchiveWish.requested_category_key, ArchiveWish.category)
            )
        ),
    )


def matching_archive_id_subquery(*, exclude_archive_id: int | None = None):
    """Return the effective-public Archive matcher correlated to ArchiveWish."""

    conditions = [
        *public_archive_conditions(),
        Course.deleted_at.is_(None),
        _wish_course_matches_archive(),
        _normalized_text_expr(Archive.name) == _normalized_text_expr(ArchiveWish.name),
        _normalized_text_expr(Archive.professor)
        == _normalized_text_expr(ArchiveWish.professor),
        or_(
            ArchiveWish.academic_year.is_(None),
            Archive.academic_year == ArchiveWish.academic_year,
        ),
        Archive.archive_type == ArchiveWish.archive_type,
    ]
    if exclude_archive_id is not None:
        conditions.append(Archive.id != exclude_archive_id)
    return (
        select(Archive.id)
        .join(Course, Course.id == Archive.course_id)
        .where(*conditions)
        .order_by(Archive.id.asc())
        .limit(1)
        .correlate(ArchiveWish)
        .scalar_subquery()
    )


async def target_has_public_archive(
    db: AsyncSession,
    data: ArchiveWishCreate,
    *,
    course: Course | None,
) -> bool:
    """Check a proposed target with the same identity used for fulfillment."""

    course_conditions = (
        [Archive.course_id == course.id]
        if course is not None
        else [
            normalized_course_text_expr(Course.name)
            == normalize_course_search_text(data.requested_course_name or data.subject),
            _normalized_text_expr(Course.category)
            == (data.requested_category_key or data.category).strip().lower(),
        ]
    )
    term_conditions = (
        [] if data.academic_year is None else [Archive.academic_year == data.academic_year]
    )
    archive_id = await db.scalar(
        select(Archive.id)
        .join(Course, Course.id == Archive.course_id)
        .where(
            *public_archive_conditions(),
            Course.deleted_at.is_(None),
            *course_conditions,
            *term_conditions,
            _normalized_text_expr(Archive.name) == data.name.strip().lower(),
            _normalized_text_expr(Archive.professor) == data.professor.strip().lower(),
            Archive.archive_type == data.archive_type,
        )
        .order_by(Archive.id.asc())
        .limit(1)
    )
    return archive_id is not None


async def enqueue_new_wish_fulfillment_notifications(
    db: AsyncSession,
    *,
    archive: Archive,
    publisher_user_id: int | None,
) -> int:
    """Notify newly fulfilled Wish owners inside the publication transaction."""

    if archive.id is None:
        raise ValueError("Archive must be flushed before fulfillment notification")
    course = await db.get(Course, archive.course_id)
    if course is None:
        return 0
    previous_match = matching_archive_id_subquery(exclude_archive_id=archive.id)
    course_match = or_(
        ArchiveWish.course_id == archive.course_id,
        (ArchiveWish.course_id.is_(None))
        & (
            normalized_course_text_expr(
                ArchiveWish.requested_course_name, ArchiveWish.subject
            )
            == normalize_course_search_text(course.name)
        )
        & (
            _normalized_text_expr(
                func.coalesce(ArchiveWish.requested_category_key, ArchiveWish.category)
            )
            == course.category.strip().lower()
        ),
    )
    wishes = (
        await db.execute(
            select(ArchiveWish).where(
                course_match,
                _normalized_text_expr(ArchiveWish.name) == archive.name.strip().lower(),
                _normalized_text_expr(ArchiveWish.professor)
                == archive.professor.strip().lower(),
                or_(
                    ArchiveWish.academic_year.is_(None),
                    ArchiveWish.academic_year == archive.academic_year,
                ),
                ArchiveWish.archive_type == archive.archive_type,
                previous_match.is_(None),
            )
        )
    ).scalars()
    created = 0
    for wish in wishes:
        if publisher_user_id is not None and wish.creator_id == publisher_user_id:
            continue
        created += int(
            await enqueue_personal_notification(
                db,
                user_id=wish.creator_id,
                notification_type=PersonalNotificationType.WISH_FULFILLED,
                title="考古許願已實現",
                message=f"你的「{wish.title}」已由其他使用者成功上傳並公開。",
                dedupe_key=f"wish_fulfilled:{wish.id}",
                metadata={
                    "wish_id": wish.id,
                    "wish_title": wish.title,
                    "archive_id": archive.id,
                    "archive_name": archive.name,
                    "course_name": course.name,
                    "course_name_en": course.name_en,
                },
            )
        )
    return created
