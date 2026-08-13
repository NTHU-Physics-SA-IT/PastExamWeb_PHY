from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, delete, func, or_, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.courses import _public_archive_conditions
from app.db.session import get_session
from app.models.models import (
    AnnouncementReadReceipt,
    AnnouncementWithRead,
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveSubmission,
    Course,
    Notification,
    NotificationCenterRead,
    NotificationCreate,
    NotificationRead,
    NotificationUnreadCounts,
    NotificationUnreadSummary,
    NotificationUpdate,
    PersonalNotification,
    PersonalNotificationRead,
    SubmissionStatus,
    User,
    UserRoles,
)
from app.utils.auth import get_current_user

router = APIRouter()


def _notification_read(
    notification: Notification, updater: User | None = None
) -> NotificationRead:
    return NotificationRead.model_validate(notification).model_copy(
        update={"updated_by_username": updater.name if updater else None}
    )


def _apply_time_filters(statement):
    now = datetime.now(UTC)
    return (
        statement.where(Notification.deleted_at.is_(None))
        .where(Notification.is_active.is_(True))
        .where((Notification.starts_at.is_(None)) | (Notification.starts_at <= now))
        .where((Notification.ends_at.is_(None)) | (Notification.ends_at >= now))
    )


def _announcement_is_read(read_at: datetime | None, updated_at: datetime) -> bool:
    return bool(read_at and read_at >= updated_at)


async def _list_announcements_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    unread_only: bool = False,
    limit: int | None = None,
) -> list[AnnouncementWithRead]:
    statement = (
        select(Notification, AnnouncementReadReceipt.read_at)
        .outerjoin(
            AnnouncementReadReceipt,
            (AnnouncementReadReceipt.notification_id == Notification.id)
            & (AnnouncementReadReceipt.user_id == user_id),
        )
        .order_by(Notification.updated_at.desc(), Notification.id.desc())
    )
    statement = _apply_time_filters(statement)
    if unread_only:
        statement = statement.where(
            or_(
                AnnouncementReadReceipt.id.is_(None),
                AnnouncementReadReceipt.read_at < Notification.updated_at,
            )
        )
    if limit is not None:
        statement = statement.limit(max(1, min(limit, 100)))
    rows = (await db.execute(statement)).all()
    return [
        AnnouncementWithRead(
            **NotificationRead.model_validate(notification).model_dump(),
            is_read=_announcement_is_read(read_at, notification.updated_at),
            read_at=read_at,
        )
        for notification, read_at in rows
    ]


async def _list_personal_notifications(
    db: AsyncSession,
    user_id: int,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[PersonalNotificationRead]:
    statement = (
        select(PersonalNotification)
        .order_by(
            PersonalNotification.created_at.desc(), PersonalNotification.id.desc()
        )
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    )
    statement = statement.where(PersonalNotification.user_id == user_id)
    if unread_only:
        statement = statement.where(PersonalNotification.read_at.is_(None))
    items = list((await db.execute(statement)).scalars().all())

    archive_submission_source_ids = {
        item.source_id
        for item in items
        if item.source_type == "archive_submission" and item.source_id is not None
    }
    available_archive_submission_ids: set[int] = set()
    if archive_submission_source_ids:
        available_archive_submission_ids = set(
            (
                await db.execute(
                    select(ArchiveSubmission.id).where(
                        ArchiveSubmission.id.in_(archive_submission_source_ids),
                        ArchiveSubmission.requester_id == user_id,
                        ArchiveSubmission.deleted_at.is_(None),
                        ArchiveSubmission.status != SubmissionStatus.DELETED,
                    )
                )
            )
            .scalars()
            .all()
        )
    archive_report_source_ids = {
        item.source_id
        for item in items
        if item.source_type == "archive_report" and item.source_id is not None
    }
    available_archive_report_destinations: dict[int, tuple[int, int]] = {}
    if archive_report_source_ids:
        available_archive_report_destinations = {
            report_id: (course_id, archive_id)
            for report_id, course_id, archive_id in (
                await db.execute(
                    select(ArchiveReport.id, Course.id, Archive.id)
                    .join(Archive, Archive.id == ArchiveReport.archive_id)
                    .join(
                        Course,
                        and_(
                            Course.id == ArchiveReport.course_id,
                            Course.id == Archive.course_id,
                        ),
                    )
                    .where(
                        ArchiveReport.id.in_(archive_report_source_ids),
                        ArchiveReport.deleted_at.is_(None),
                        ArchiveReport.reporter_user_id == user_id,
                        Course.deleted_at.is_(None),
                        *_public_archive_conditions(),
                    )
                )
            ).all()
        }

    discussion_source_pairs = {
        (item.source_id, item.source_message_id)
        for item in items
        if item.source_type == "archive_discussion_thread"
        and item.source_id is not None
        and item.source_message_id is not None
    }
    available_discussion_destinations: dict[tuple[int, int], tuple[int, int]] = {}
    if discussion_source_pairs:
        root = aliased(ArchiveDiscussionMessage)
        message = aliased(ArchiveDiscussionMessage)
        available_discussion_destinations = {
            (root_id, message_id): (course_id, archive_id)
            for root_id, message_id, course_id, archive_id in (
                await db.execute(
                    select(root.id, message.id, Course.id, Archive.id)
                    .join(message, message.archive_id == root.archive_id)
                    .join(Archive, Archive.id == root.archive_id)
                    .join(Course, Course.id == Archive.course_id)
                    .where(
                        tuple_(root.id, message.id).in_(discussion_source_pairs),
                        root.parent_id.is_(None),
                        root.deleted_at.is_(None),
                        message.deleted_at.is_(None),
                        or_(message.id == root.id, message.parent_id == root.id),
                        Course.deleted_at.is_(None),
                        *_public_archive_conditions(),
                    )
                )
            ).all()
        }

    def metadata_id(item: PersonalNotification, key: str) -> int | None:
        value = (item.metadata_json or {}).get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def optional_metadata_id_matches(
        item: PersonalNotification, key: str, expected: int
    ) -> bool:
        value = (item.metadata_json or {}).get(key)
        return value is None or metadata_id(item, key) == expected

    def source_is_available(item: PersonalNotification) -> bool:
        if item.source_type is None:
            return item.source_id is None and item.source_message_id is None
        if item.source_type == "archive_submission":
            return (
                item.source_id is not None
                and item.source_message_id is None
                and item.source_id in available_archive_submission_ids
                and optional_metadata_id_matches(item, "submission_id", item.source_id)
            )
        if item.source_type == "archive_report":
            if item.source_id is None or item.source_message_id is not None:
                return False
            destination = available_archive_report_destinations.get(item.source_id)
            return bool(
                destination
                and metadata_id(item, "course_id") == destination[0]
                and metadata_id(item, "archive_id") == destination[1]
                and optional_metadata_id_matches(item, "report_id", item.source_id)
            )
        if item.source_type == "comment_report":
            return False
        if item.source_type == "archive_discussion_thread":
            if item.source_id is None or item.source_message_id is None:
                return False
            destination = available_discussion_destinations.get(
                (item.source_id, item.source_message_id)
            )
            return bool(
                destination
                and metadata_id(item, "course_id") == destination[0]
                and metadata_id(item, "archive_id") == destination[1]
                and optional_metadata_id_matches(item, "thread_id", item.source_id)
                and optional_metadata_id_matches(
                    item, "message_id", item.source_message_id
                )
                and optional_metadata_id_matches(
                    item, "reply_message_id", item.source_message_id
                )
            )
        return False

    return [
        PersonalNotificationRead(
            id=item.id,
            notification_type=item.notification_type,
            title=item.title,
            message=item.message,
            source_type=item.source_type,
            source_id=item.source_id,
            source_message_id=item.source_message_id,
            metadata=dict(item.metadata_json or {}),
            source_available=source_is_available(item),
            read_at=item.read_at,
            created_at=item.created_at,
        )
        for item in items
    ]


async def _unread_counts(
    db: AsyncSession,
    user_id: int,
) -> NotificationUnreadCounts:
    announcement_statement = (
        select(func.count(Notification.id))
        .outerjoin(
            AnnouncementReadReceipt,
            (AnnouncementReadReceipt.notification_id == Notification.id)
            & (AnnouncementReadReceipt.user_id == user_id),
        )
        .where(
            or_(
                AnnouncementReadReceipt.id.is_(None),
                AnnouncementReadReceipt.read_at < Notification.updated_at,
            )
        )
    )
    announcement_statement = _apply_time_filters(announcement_statement)
    announcement_count = int(await db.scalar(announcement_statement) or 0)
    personal_statement = select(func.count(PersonalNotification.id)).where(
        PersonalNotification.read_at.is_(None),
        PersonalNotification.user_id == user_id,
    )
    personal_count = int(await db.scalar(personal_statement) or 0)
    return NotificationUnreadCounts(
        announcements=announcement_count,
        personal_notifications=personal_count,
        total=announcement_count + personal_count,
    )


@router.get("/active", response_model=list[NotificationRead])
async def get_active_notifications(
    db: AsyncSession = Depends(get_session),
):
    query = select(Notification).order_by(Notification.updated_at.desc())
    query = _apply_time_filters(query)
    result = await db.execute(query)
    notifications = result.scalars().all()
    return [
        NotificationRead.model_validate(notification) for notification in notifications
    ]


@router.get("", response_model=list[NotificationRead])
async def list_public_notifications(
    db: AsyncSession = Depends(get_session),
):
    query = select(Notification).order_by(Notification.updated_at.desc())
    query = _apply_time_filters(query)
    result = await db.execute(query)
    notifications = result.scalars().all()
    return [
        NotificationRead.model_validate(notification) for notification in notifications
    ]


@router.get("/center", response_model=NotificationCenterRead)
async def get_notification_center(
    personal_limit: int = Query(default=50, ge=1, le=100),
    personal_offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    announcements = await _list_announcements_for_user(db, current_user.user_id)
    personal_notifications = await _list_personal_notifications(
        db,
        current_user.user_id,
        limit=personal_limit,
        offset=personal_offset,
    )
    counts = await _unread_counts(db, current_user.user_id)
    return NotificationCenterRead(
        announcements=announcements,
        personal_notifications=personal_notifications,
        counts=counts,
    )


@router.get("/counts", response_model=NotificationUnreadCounts)
async def get_notification_counts(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    return await _unread_counts(db, current_user.user_id)


@router.get("/unread-summary", response_model=NotificationUnreadSummary)
async def get_unread_notification_summary(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    announcements = await _list_announcements_for_user(
        db, current_user.user_id, unread_only=True, limit=limit
    )
    personal_notifications = await _list_personal_notifications(
        db,
        current_user.user_id,
        unread_only=True,
        limit=limit,
    )
    counts = await _unread_counts(db, current_user.user_id)
    return NotificationUnreadSummary(
        announcements=announcements,
        personal_notifications=personal_notifications,
        counts=counts,
    )


@router.put("/announcements/{notification_id}/read")
async def mark_announcement_read(
    notification_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    statement = select(Notification.id).where(Notification.id == notification_id)
    statement = _apply_time_filters(statement)
    if await db.scalar(statement) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found"
        )
    read_at = datetime.now(UTC)
    await db.execute(
        pg_insert(AnnouncementReadReceipt)
        .values(
            notification_id=notification_id,
            user_id=current_user.user_id,
            read_at=read_at,
        )
        .on_conflict_do_update(
            constraint="uq_announcement_read_receipts_notification_user",
            set_={"read_at": read_at},
        )
    )
    await db.commit()
    return {"success": True, "read_at": read_at}


@router.put("/personal/{personal_notification_id}/read")
async def mark_personal_notification_read(
    personal_notification_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    item = (
        await db.execute(
            select(PersonalNotification).where(
                PersonalNotification.id == personal_notification_id,
                PersonalNotification.user_id == current_user.user_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
        db.add(item)
        await db.commit()
    return {"success": True, "read_at": item.read_at}


@router.put("/personal/read-all")
async def mark_all_personal_notifications_read(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    read_at = datetime.now(UTC)
    await db.execute(
        update(PersonalNotification)
        .where(
            PersonalNotification.user_id == current_user.user_id,
            PersonalNotification.read_at.is_(None),
        )
        .values(read_at=read_at)
    )
    await db.commit()
    return {"success": True, "read_at": read_at}


@router.delete("/personal/{personal_notification_id}")
async def delete_personal_notification(
    personal_notification_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    deleted_id = await db.scalar(
        delete(PersonalNotification)
        .where(
            PersonalNotification.id == personal_notification_id,
            PersonalNotification.user_id == current_user.user_id,
        )
        .returning(PersonalNotification.id)
    )
    if deleted_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    await db.commit()
    return {"success": True}


@router.delete("/personal")
async def delete_all_personal_notifications(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    deleted_ids = list(
        (
            await db.execute(
                delete(PersonalNotification)
                .where(PersonalNotification.user_id == current_user.user_id)
                .returning(PersonalNotification.id)
            )
        )
        .scalars()
        .all()
    )
    await db.commit()
    return {"deleted_count": len(deleted_ids)}


@router.put("/mark-all-read")
async def mark_all_announcements_and_notifications_read(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    read_at = datetime.now(UTC)
    announcement_ids = [
        announcement.id
        for announcement in await _list_announcements_for_user(db, current_user.user_id)
    ]
    if announcement_ids:
        await db.execute(
            pg_insert(AnnouncementReadReceipt)
            .values(
                [
                    {
                        "notification_id": notification_id,
                        "user_id": current_user.user_id,
                        "read_at": read_at,
                    }
                    for notification_id in announcement_ids
                ]
            )
            .on_conflict_do_update(
                constraint="uq_announcement_read_receipts_notification_user",
                set_={"read_at": read_at},
            )
        )
    await db.execute(
        update(PersonalNotification)
        .where(
            PersonalNotification.user_id == current_user.user_id,
            PersonalNotification.read_at.is_(None),
        )
        .values(read_at=read_at)
    )
    await db.commit()
    return {"success": True, "read_at": read_at}


@router.get("/admin/notifications", response_model=list[NotificationRead])
async def list_admin_notifications(
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    query = (
        select(Notification, User)
        .outerjoin(User, User.id == Notification.updated_by_id)
        .where(Notification.deleted_at.is_(None))
        .order_by(Notification.updated_at.desc())
    )
    result = await db.execute(query)
    return [
        _notification_read(notification, updater)
        for notification, updater in result.all()
    ]


@router.post(
    "/admin/notifications",
    response_model=NotificationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification(
    notification_data: NotificationCreate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    notification = Notification(**notification_data.model_dump())
    now = datetime.now(UTC)
    notification.created_at = now
    notification.updated_at = now
    notification.updated_by_id = current_user.user_id

    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    updater = await db.get(User, current_user.user_id)
    return _notification_read(notification, updater)


@router.put("/admin/notifications/{notification_id}", response_model=NotificationRead)
async def update_notification(
    notification_id: int,
    notification_data: NotificationUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.deleted_at.is_(None)
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )

    update_data = notification_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(notification, field, value)

    notification.updated_at = datetime.now(UTC)
    notification.updated_by_id = current_user.user_id

    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    updater = await db.get(User, current_user.user_id)
    return _notification_read(notification, updater)


@router.delete(
    "/admin/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: UserRoles = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.deleted_at.is_(None)
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )

    now = datetime.now(UTC)
    notification.deleted_at = now
    notification.updated_at = now
    notification.deleted_by_id = current_user.user_id
    await db.commit()
