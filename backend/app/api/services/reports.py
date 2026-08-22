import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.services.archive_submission_lifecycle import (
    soft_delete_archive_with_submission_takedown,
)
from app.db.session import get_session
from app.models.models import (
    Archive,
    ArchiveDiscussionMessage,
    ArchiveReport,
    ArchiveReportAdminUpdate,
    ArchiveReportCreate,
    ArchiveReportListRead,
    ArchiveReportRead,
    ArchiveReportReason,
    ArchiveSubmission,
    CommentReport,
    CommentReportAdminUpdate,
    CommentReportCreate,
    CommentReportListRead,
    CommentReportRead,
    CommentReportReason,
    CommentReportStatus,
    Course,
    PersonalNotificationType,
    SubmissionStatus,
    SystemIssueReport,
    SystemIssueReportCreate,
    SystemIssueReportListRead,
    SystemIssueReportRead,
    SystemIssueReportReadStateUpdate,
    User,
    UserRoles,
)
from app.services.archive_report_lifecycle_locks import (
    acquire_stable_archive_report_locks,
)
from app.services.archive_report_uniqueness import (
    acquire_archive_report_uniqueness_mutex,
    acquire_archive_report_uniqueness_mutex_for_report,
    archive_report_pending_conflict_error,
    is_archive_report_pending_unique_violation,
)
from app.services.archive_submission_status import (
    normalize_submission_status,
    take_down_archive_submission,
)
from app.services.discussions import soft_delete_discussion_message
from app.services.personal_notifications import enqueue_personal_notification
from app.utils.auth import get_current_user

router = APIRouter()

FINAL_REPORT_STATUSES = {
    CommentReportStatus.UPHELD.value,
    CommentReportStatus.DISMISSED.value,
}
REPORT_REASON_LABELS = {
    CommentReportReason.SPAM_OR_DUPLICATE.value: "垃圾訊息或重複洗版",
    CommentReportReason.HARASSMENT_OR_HOSTILITY.value: "攻擊、騷擾或不友善內容",
    CommentReportReason.INAPPROPRIATE_OR_ILLEGAL.value: "不當或違法內容",
    CommentReportReason.PRIVACY_VIOLATION.value: "洩漏個人資料或隱私",
    CommentReportReason.MISINFORMATION.value: "錯誤或誤導資訊",
    CommentReportReason.OTHER.value: "其他",
}
ARCHIVE_REPORT_REASON_LABELS = {
    ArchiveReportReason.FILE_UNAVAILABLE_OR_CORRUPT.value: "檔案無法開啟或檔案損毀",
    ArchiveReportReason.METADATA_MISMATCH.value: "考古題內容與課程／考試資訊不符",
    ArchiveReportReason.DUPLICATE_ARCHIVE.value: "重複的考古題",
    ArchiveReportReason.INCOMPLETE_OR_LOW_QUALITY.value: "檔案模糊、缺頁或內容不完整",
    ArchiveReportReason.PERSONAL_INFORMATION.value: "含有不適合公開的個人資訊",
    ArchiveReportReason.OTHER.value: "其他問題",
}
SYSTEM_ISSUE_TYPES = {"bug", "enhancement", "performance", "ui-ux", "question"}
GITHUB_ISSUE_URL_PATTERN = re.compile(
    r"^https://github\.com/(?:PingScientist|NTHU-Physics-SA-IT)/PastExamWeb_PHY/issues/(?P<number>[1-9][0-9]*)$"
)


def _display_name(user_id: int | None, nickname: str | None, name: str | None) -> str:
    if user_id is None:
        return "已刪除使用者"
    return (nickname or name or f"使用者 {user_id}").strip()


def _require_admin(current_user: UserRoles) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )


def _report_select():
    reporter = aliased(User)
    author = aliased(User)
    reviewer = aliased(User)
    source = aliased(ArchiveDiscussionMessage)
    statement = (
        select(
            CommentReport,
            reporter.nickname,
            reporter.name,
            author.nickname,
            author.name,
            reviewer.nickname,
            reviewer.name,
            source.id,
            Course.name,
            Course.name_en,
        )
        .outerjoin(reporter, reporter.id == CommentReport.reporter_user_id)
        .outerjoin(author, author.id == CommentReport.comment_author_id)
        .outerjoin(reviewer, reviewer.id == CommentReport.reviewed_by)
        .outerjoin(
            source,
            (source.id == CommentReport.comment_id) & (source.deleted_at.is_(None)),
        )
        .outerjoin(Course, Course.id == CommentReport.course_id)
        .where(CommentReport.deleted_at.is_(None))
    )
    return statement, reporter, author, reviewer


def _serialize_report(row) -> CommentReportRead:
    report = row[0]
    return CommentReportRead(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=_display_name(report.reporter_user_id, row[1], row[2]),
        comment_id=report.comment_id,
        comment_author_id=report.comment_author_id,
        comment_author_name=(
            _display_name(report.comment_author_id, row[3], row[4])
            if report.comment_author_id and (row[3] or row[4])
            else report.comment_author_name_snapshot
        ),
        archive_id=report.archive_id,
        course_id=report.course_id,
        thread_id=report.thread_id,
        reply_to_message_id=report.reply_to_message_id,
        reason=report.reason,
        custom_message=report.custom_message,
        comment_content_snapshot=report.comment_content_snapshot,
        comment_created_at_snapshot=report.comment_created_at_snapshot,
        archive_name=report.archive_name_snapshot,
        course_name=report.course_name_snapshot,
        course_name_en=row[9] if row[8] == report.course_name_snapshot else None,
        status=report.status,
        admin_response=report.admin_response,
        reviewed_by=report.reviewed_by,
        reviewer_name=(
            _display_name(report.reviewed_by, row[5], row[6])
            if report.reviewed_by
            else None
        ),
        reviewed_at=report.reviewed_at,
        comment_deleted=report.comment_deleted,
        source_exists=row[7] is not None,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def _read_report(db: AsyncSession, report_id: int) -> CommentReportRead:
    statement, _, _, _ = _report_select()
    row = (
        await db.execute(statement.where(CommentReport.id == report_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment report not found"
        )
    return _serialize_report(row)


def _archive_report_select():
    reporter = aliased(User)
    reviewer = aliased(User)
    statement = (
        select(
            ArchiveReport,
            reporter.nickname,
            reporter.name,
            reviewer.nickname,
            reviewer.name,
            Archive.id,
            Archive.deleted_at,
            Course.id,
            Course.deleted_at,
            ArchiveSubmission.id,
            ArchiveSubmission.status,
            ArchiveSubmission.deleted_at,
            Course.name,
            Course.name_en,
        )
        .outerjoin(reporter, reporter.id == ArchiveReport.reporter_user_id)
        .outerjoin(reviewer, reviewer.id == ArchiveReport.reviewed_by)
        .outerjoin(Archive, Archive.id == ArchiveReport.archive_id)
        .outerjoin(Course, Course.id == ArchiveReport.course_id)
        .outerjoin(
            ArchiveSubmission,
            ArchiveSubmission.id == ArchiveReport.archive_submission_id,
        )
        .where(ArchiveReport.deleted_at.is_(None))
    )
    return statement, reporter, reviewer


def _serialize_archive_report(row) -> ArchiveReportRead:
    report = row[0]
    archive_exists = row[5] is not None
    archive_deleted_at = row[6]
    course_exists = row[7] is not None
    course_deleted_at = row[8]
    submission_exists = row[9] is not None
    submission_status = normalize_submission_status(row[10])
    submission_deleted_at = row[11]

    if not archive_exists or not course_exists:
        source_state = "missing"
    elif archive_deleted_at is not None or course_deleted_at is not None:
        source_state = "trashed"
    elif not submission_exists:
        source_state = "not_managed"
    elif (
        submission_deleted_at is not None
        or submission_status == SubmissionStatus.DELETED
    ):
        source_state = "deleted"
    elif submission_status == SubmissionStatus.TAKEDOWN:
        source_state = "taken_down"
    elif submission_status != SubmissionStatus.APPROVED:
        source_state = "unavailable"
    else:
        source_state = "available"

    return ArchiveReportRead(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=(
            _display_name(report.reporter_user_id, row[1], row[2])
            if report.reporter_user_id is not None
            else report.reporter_name_snapshot
        ),
        archive_id=report.archive_id,
        archive_id_snapshot=report.archive_id_snapshot,
        course_id=report.course_id,
        archive_submission_id=report.archive_submission_id,
        reason=report.reason,
        supplementary_detail=report.supplementary_detail,
        archive_name=report.archive_name_snapshot,
        course_name=report.course_name_snapshot,
        course_name_en=row[13] if row[12] == report.course_name_snapshot else None,
        academic_year=report.academic_year_snapshot,
        archive_type=report.archive_type_snapshot,
        professor=report.professor_snapshot,
        status=report.status,
        admin_response=report.admin_response,
        reviewed_by=report.reviewed_by,
        reviewer_name=(
            _display_name(report.reviewed_by, row[3], row[4])
            if report.reviewed_by is not None
            else None
        ),
        reviewed_at=report.reviewed_at,
        archive_taken_down=report.archive_taken_down,
        source_exists=source_state not in {"missing", "trashed", "deleted"},
        source_state=source_state,
        can_take_down=source_state == "available",
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def _read_archive_report(db: AsyncSession, report_id: int) -> ArchiveReportRead:
    statement, _, _ = _archive_report_select()
    row = (
        await db.execute(statement.where(ArchiveReport.id == report_id))
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive report not found",
        )
    return _serialize_archive_report(row)


def _safe_github_issue_url(report: SystemIssueReport) -> str | None:
    if not report.github_issue_url or report.github_issue_number is None:
        return None
    match = GITHUB_ISSUE_URL_PATTERN.fullmatch(report.github_issue_url)
    if not match or int(match.group("number")) != report.github_issue_number:
        return None
    return report.github_issue_url


def _serialize_system_issue(
    report: SystemIssueReport,
    nickname,
    name,
    read_by_nickname=None,
    read_by_name=None,
) -> SystemIssueReportRead:
    return SystemIssueReportRead(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        reporter_name=_display_name(report.reporter_user_id, nickname, name),
        report_type=report.report_type,
        title=report.title,
        description=report.description,
        contact=report.contact,
        status=report.status,
        github_issue_number=report.github_issue_number,
        github_issue_url=_safe_github_issue_url(report),
        is_read=report.read_at is not None,
        read_at=report.read_at,
        read_by_username=(
            _display_name(report.read_by_user_id, read_by_nickname, read_by_name)
            if report.read_by_user_id is not None
            else None
        ),
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _system_issue_select():
    reporter = aliased(User)
    reader = aliased(User)
    statement = (
        select(
            SystemIssueReport,
            reporter.nickname,
            reporter.name,
            reader.nickname,
            reader.name,
        )
        .outerjoin(reporter, reporter.id == SystemIssueReport.reporter_user_id)
        .outerjoin(reader, reader.id == SystemIssueReport.read_by_user_id)
    )
    return statement, reporter, reader


def _serialize_system_issue_row(row) -> SystemIssueReportRead:
    return _serialize_system_issue(row[0], row[1], row[2], row[3], row[4])


@router.post(
    "/system-issues",
    response_model=SystemIssueReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_system_issue_report(
    payload: SystemIssueReportCreate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    report_type = payload.report_type.strip()
    title = payload.title.strip()
    description = payload.description.strip()
    if report_type not in SYSTEM_ISSUE_TYPES or not title or not description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid system issue report",
        )
    metadata = payload.metadata or {}
    if len(json.dumps(metadata, ensure_ascii=False, default=str)) > 10_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="System issue metadata is too large",
        )
    report = SystemIssueReport(
        reporter_user_id=current_user.user_id,
        report_type=report_type,
        title=title,
        description=description,
        contact=(payload.contact or "").strip() or None,
        metadata_json=metadata,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    user = await db.get(User, current_user.user_id)
    return _serialize_system_issue(
        report,
        user.nickname if user else None,
        user.name if user else None,
    )


@router.get("/admin/system-issues", response_model=SystemIssueReportListRead)
async def list_system_issue_reports(
    search: str | None = Query(default=None, max_length=100),
    report_type: str | None = Query(default=None, max_length=40),
    read_state: str = Query(default="all", pattern="^(all|unread|read)$"),
    sort_by: str = Query(default="read_state"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    statement, reporter, _ = _system_issue_select()
    statement = statement.where(SystemIssueReport.deleted_at.is_(None))
    filters = []
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        filters.append(
            or_(
                SystemIssueReport.title.ilike(pattern),
                SystemIssueReport.description.ilike(pattern),
                reporter.name.ilike(pattern),
                reporter.nickname.ilike(pattern),
            )
        )
    if report_type:
        if report_type not in SYSTEM_ISSUE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid system issue report type",
            )
        filters.append(SystemIssueReport.report_type == report_type)
    if read_state == "read":
        filters.append(SystemIssueReport.read_at.is_not(None))
    elif read_state == "unread":
        filters.append(SystemIssueReport.read_at.is_(None))
    if filters:
        statement = statement.where(*filters)

    sort_fields = {
        "created_at": SystemIssueReport.created_at,
        "reporter": func.coalesce(reporter.nickname, reporter.name, ""),
        "title": SystemIssueReport.title,
        "report_type": SystemIssueReport.report_type,
        "read_state": case((SystemIssueReport.read_at.is_(None), 0), else_=1),
    }
    sort_column = sort_fields.get(sort_by)
    if sort_column is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid system issue sort field",
        )
    total = int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    secondary_ordering = (
        (SystemIssueReport.created_at.desc(), SystemIssueReport.id.desc())
        if sort_by == "read_state"
        else (SystemIssueReport.id.desc(),)
    )
    rows = (
        await db.execute(
            statement.order_by(ordering, *secondary_ordering)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return SystemIssueReportListRead(
        items=[_serialize_system_issue_row(row) for row in rows],
        total=total,
    )


@router.get("/admin/system-issues/{report_id}", response_model=SystemIssueReportRead)
async def get_system_issue_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    statement, _, _ = _system_issue_select()
    row = (
        await db.execute(
            statement.where(
                SystemIssueReport.id == report_id,
                SystemIssueReport.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System issue report not found",
        )
    return _serialize_system_issue_row(row)


@router.patch(
    "/admin/system-issues/{report_id}/read-state",
    response_model=SystemIssueReportRead,
)
async def update_system_issue_read_state(
    report_id: int,
    payload: SystemIssueReportReadStateUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    report = (
        await db.execute(
            select(SystemIssueReport)
            .where(
                SystemIssueReport.id == report_id,
                SystemIssueReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System issue report not found",
        )
    now = datetime.now(UTC)
    report.read_at = now if payload.is_read else None
    report.read_by_user_id = current_user.user_id if payload.is_read else None
    report.updated_at = now
    db.add(report)
    await db.commit()
    statement, _, _ = _system_issue_select()
    row = (await db.execute(statement.where(SystemIssueReport.id == report_id))).one()
    return _serialize_system_issue_row(row)


@router.delete("/admin/system-issues/{report_id}")
async def delete_system_issue_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    report = (
        await db.execute(
            select(SystemIssueReport)
            .where(
                SystemIssueReport.id == report_id,
                SystemIssueReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System issue report not found",
        )
    report.deleted_at = datetime.now(UTC)
    report.deleted_by_id = current_user.user_id
    db.add(report)
    await db.commit()
    return {"success": True}


@router.post(
    "/courses/{course_id}/archives/{archive_id}/comments/{comment_id}",
    response_model=CommentReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment_report(
    course_id: int,
    archive_id: int,
    comment_id: int,
    payload: CommentReportCreate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    custom_message = (payload.custom_message or "").strip()
    if payload.report_reason == CommentReportReason.OTHER and not custom_message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Custom message is required for the other reason",
        )

    row = (
        await db.execute(
            select(ArchiveDiscussionMessage, Archive, Course, User)
            .join(Archive, Archive.id == ArchiveDiscussionMessage.archive_id)
            .join(Course, Course.id == Archive.course_id)
            .join(User, User.id == ArchiveDiscussionMessage.user_id)
            .where(
                ArchiveDiscussionMessage.id == comment_id,
                ArchiveDiscussionMessage.archive_id == archive_id,
                ArchiveDiscussionMessage.deleted_at.is_(None),
                Archive.id == archive_id,
                Archive.course_id == course_id,
                Archive.deleted_at.is_(None),
                Course.id == course_id,
                Course.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found"
        )
    message, archive, course, author = row
    reason = payload.report_reason.value
    duplicate = await db.scalar(
        select(CommentReport.id).where(
            CommentReport.reporter_user_id == current_user.user_id,
            CommentReport.comment_id == comment_id,
            CommentReport.reason == reason,
            CommentReport.deleted_at.is_(None),
            CommentReport.status == CommentReportStatus.PENDING.value,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active report for this comment and reason",
        )

    report = CommentReport(
        reporter_user_id=current_user.user_id,
        comment_id=message.id,
        comment_author_id=message.user_id,
        archive_id=archive.id,
        course_id=course.id,
        thread_id=message.parent_id or message.id,
        reply_to_message_id=message.reply_to_message_id,
        reason=reason,
        custom_message=custom_message
        if payload.report_reason == CommentReportReason.OTHER
        else None,
        comment_content_snapshot=message.content,
        comment_author_name_snapshot=_display_name(
            author.id, author.nickname, author.name
        ),
        comment_created_at_snapshot=message.created_at,
        archive_name_snapshot=archive.name,
        course_name_snapshot=course.name,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active report for this comment and reason",
        ) from error

    await enqueue_personal_notification(
        db,
        user_id=current_user.user_id,
        notification_type=PersonalNotificationType.COMMENT_REPORT_SUBMITTED,
        title="留言回報已成功送出",
        message=f"原因：{REPORT_REASON_LABELS[reason]}。請等待管理員審核。",
        source_type="comment_report",
        source_id=report.id,
        metadata={"report_id": report.id, "reason": reason, "status": report.status},
        dedupe_key=f"comment_report_submitted:{report.id}",
    )
    await db.commit()
    return await _read_report(db, report.id)


@router.get("/admin/comments", response_model=CommentReportListRead)
async def list_comment_reports(
    report_status: CommentReportStatus | None = Query(default=None, alias="status"),
    reason: CommentReportReason | None = None,
    search: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="status"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    statement, reporter, author, reviewer = _report_select()
    filters = []
    if report_status:
        filters.append(CommentReport.status == report_status.value)
    if reason:
        filters.append(CommentReport.reason == reason.value)
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        filters.append(
            or_(
                CommentReport.comment_content_snapshot.ilike(pattern),
                CommentReport.course_name_snapshot.ilike(pattern),
                and_(
                    Course.name == CommentReport.course_name_snapshot,
                    Course.name_en.ilike(pattern),
                ),
                CommentReport.archive_name_snapshot.ilike(pattern),
                reporter.name.ilike(pattern),
                reporter.nickname.ilike(pattern),
                author.name.ilike(pattern),
                author.nickname.ilike(pattern),
            )
        )
    if filters:
        statement = statement.where(*filters)
    total = int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    status_rank = case(
        (CommentReport.status == CommentReportStatus.PENDING.value, 0),
        (CommentReport.status == CommentReportStatus.UPHELD.value, 1),
        (CommentReport.status == CommentReportStatus.DISMISSED.value, 2),
        else_=3,
    )
    sort_fields = {
        "created_at": CommentReport.created_at,
        "status": status_rank,
        "reason": CommentReport.reason,
        "reporter": func.coalesce(reporter.nickname, reporter.name, ""),
        "comment_author": func.coalesce(author.nickname, author.name, ""),
        "course_archive": func.coalesce(CommentReport.course_name_snapshot, ""),
        "reviewer": func.coalesce(reviewer.nickname, reviewer.name, ""),
        "reviewed_at": CommentReport.reviewed_at,
    }
    sort_column = sort_fields.get(sort_by)
    if sort_column is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid comment report sort field",
        )
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    secondary_ordering = (
        (CommentReport.created_at.desc(), CommentReport.id.desc())
        if sort_by == "status"
        else (CommentReport.id.desc(),)
    )
    rows = (
        await db.execute(
            statement.order_by(ordering, *secondary_ordering)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return CommentReportListRead(
        items=[_serialize_report(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/comments/{report_id}", response_model=CommentReportRead)
async def get_comment_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    return await _read_report(db, report_id)


@router.delete("/admin/comments/{report_id}")
async def delete_comment_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    report = (
        await db.execute(
            select(CommentReport)
            .where(
                CommentReport.id == report_id,
                CommentReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment report not found",
        )
    report.deleted_at = datetime.now(UTC)
    report.deleted_by_id = current_user.user_id
    db.add(report)
    await db.commit()
    return {"success": True}


@router.patch("/admin/comments/{report_id}", response_model=CommentReportRead)
async def review_comment_report(
    report_id: int,
    payload: CommentReportAdminUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    report = (
        await db.execute(
            select(CommentReport)
            .where(
                CommentReport.id == report_id,
                CommentReport.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment report not found"
        )

    new_status = payload.status.value
    if report.status in FINAL_REPORT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized report cannot be changed",
        )
    if new_status not in FINAL_REPORT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A pending report must be finalized as upheld or dismissed",
        )

    response = (payload.admin_response or "").strip()
    if payload.delete_comment and new_status != CommentReportStatus.UPHELD.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only an upheld report can delete the source comment",
        )

    now = datetime.now(UTC)
    report.status = new_status
    report.admin_response = response or None
    report.reviewed_by = current_user.user_id
    report.reviewed_at = now
    report.updated_at = now
    if payload.delete_comment and report.comment_id is not None:
        source = (
            await db.execute(
                select(ArchiveDiscussionMessage).where(
                    ArchiveDiscussionMessage.id == report.comment_id,
                    ArchiveDiscussionMessage.archive_id == report.archive_id,
                    ArchiveDiscussionMessage.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if source is not None:
            await soft_delete_discussion_message(db, source)
            report.comment_deleted = True

    db.add(report)
    result_label = (
        "回報成立" if new_status == CommentReportStatus.UPHELD.value else "回報不成立"
    )
    response_label = response or "未提供答覆"
    await enqueue_personal_notification(
        db,
        user_id=report.reporter_user_id,
        notification_type=PersonalNotificationType.COMMENT_REPORT_RESULT,
        title="留言回報審核完成",
        message=(
            f"審核結果：{result_label}。管理員答覆：{response_label}。"
            f"處置：{'留言已刪除' if report.comment_deleted else '未刪除留言'}。"
        ),
        source_type="comment_report",
        source_id=report.id,
        metadata={
            "report_id": report.id,
            "status": new_status,
            "comment_deleted": report.comment_deleted,
            "admin_response": response or None,
            "reviewed_at": now.isoformat(),
        },
        dedupe_key=f"comment_report_result:{report.id}",
    )
    await db.commit()
    return await _read_report(db, report.id)


@router.post(
    "/courses/{course_id}/archives/{archive_id}",
    response_model=ArchiveReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_archive_report(
    course_id: int,
    archive_id: int,
    payload: ArchiveReportCreate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    supplementary_detail = (payload.supplementary_detail or "").strip()
    if payload.report_reason == ArchiveReportReason.OTHER and not supplementary_detail:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Supplementary detail is required for the other reason",
        )

    row = (
        await db.execute(
            select(Archive, Course, User)
            .join(Course, Course.id == Archive.course_id)
            .join(User, User.id == current_user.user_id)
            .where(
                Archive.id == archive_id,
                Archive.course_id == course_id,
                Archive.deleted_at.is_(None),
                Course.id == course_id,
                Course.deleted_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive not found",
        )
    archive, course, reporter = row

    linked_submissions = list(
        (
            await db.execute(
                select(ArchiveSubmission)
                .where(ArchiveSubmission.created_archive_id == archive.id)
                .order_by(ArchiveSubmission.id.desc())
            )
        )
        .scalars()
        .all()
    )
    if any(
        item.deleted_at is not None
        or normalize_submission_status(item.status) != SubmissionStatus.APPROVED
        for item in linked_submissions
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive not found",
        )
    source_submission = linked_submissions[0] if linked_submissions else None

    await acquire_archive_report_uniqueness_mutex(
        db,
        reporter_user_id=current_user.user_id,
        archive_id=archive_id,
    )
    duplicate = await db.scalar(
        select(ArchiveReport.id).where(
            ArchiveReport.reporter_user_id == current_user.user_id,
            ArchiveReport.archive_id == archive_id,
            ArchiveReport.status == CommentReportStatus.PENDING.value,
            ArchiveReport.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise archive_report_pending_conflict_error()

    archive_type = getattr(archive.archive_type, "value", archive.archive_type)
    report = ArchiveReport(
        reporter_user_id=current_user.user_id,
        reporter_name_snapshot=_display_name(
            reporter.id, reporter.nickname, reporter.name
        ),
        archive_id=archive.id,
        archive_id_snapshot=archive.id,
        course_id=course.id,
        archive_submission_id=(
            source_submission.id if source_submission is not None else None
        ),
        reason=payload.report_reason.value,
        supplementary_detail=supplementary_detail or None,
        archive_name_snapshot=archive.name,
        course_name_snapshot=course.name,
        academic_year_snapshot=archive.academic_year,
        archive_type_snapshot=str(archive_type),
        professor_snapshot=archive.professor,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        if is_archive_report_pending_unique_violation(error):
            raise archive_report_pending_conflict_error() from error
        raise

    reason_label = ARCHIVE_REPORT_REASON_LABELS[report.reason]
    await enqueue_personal_notification(
        db,
        user_id=current_user.user_id,
        notification_type=PersonalNotificationType.ARCHIVE_REPORT_SUBMITTED,
        title="考古題回報已收到",
        message=(
            f"{course.name}－{archive.name}（考古題 #{archive.id}）的回報已收到。"
            f"原因：{reason_label}。目前為待審核。"
        ),
        source_type="archive_report",
        source_id=report.id,
        metadata={
            "report_id": report.id,
            "course_id": course.id,
            "archive_id": archive.id,
            "course_name": course.name,
            "course_name_en": course.name_en,
            "archive_name": archive.name,
            "reason": report.reason,
            "status": report.status,
            "destination": "archive",
        },
        dedupe_key=f"archive_report_submitted:{report.id}",
    )
    await db.commit()
    return await _read_archive_report(db, report.id)


@router.get(
    "/courses/{course_id}/archives/{archive_id}/pending",
    response_model=ArchiveReportRead,
)
async def get_pending_archive_report(
    course_id: int,
    archive_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    report_id = await db.scalar(
        select(ArchiveReport.id).where(
            ArchiveReport.reporter_user_id == current_user.user_id,
            ArchiveReport.course_id == course_id,
            ArchiveReport.archive_id == archive_id,
            ArchiveReport.status == CommentReportStatus.PENDING.value,
            ArchiveReport.deleted_at.is_(None),
        )
    )
    if report_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending archive report not found",
        )
    return await _read_archive_report(db, report_id)


@router.get("/admin/archives", response_model=ArchiveReportListRead)
async def list_archive_reports(
    report_status: CommentReportStatus | None = Query(default=None, alias="status"),
    reason: ArchiveReportReason | None = None,
    search: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="status"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    statement, reporter, reviewer = _archive_report_select()
    filters = []
    if report_status:
        filters.append(ArchiveReport.status == report_status.value)
    if reason:
        filters.append(ArchiveReport.reason == reason.value)
    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        search_conditions = [
            ArchiveReport.supplementary_detail.ilike(pattern),
            ArchiveReport.course_name_snapshot.ilike(pattern),
            and_(
                Course.name == ArchiveReport.course_name_snapshot,
                Course.name_en.ilike(pattern),
            ),
            ArchiveReport.archive_name_snapshot.ilike(pattern),
            ArchiveReport.professor_snapshot.ilike(pattern),
            ArchiveReport.reporter_name_snapshot.ilike(pattern),
            reporter.name.ilike(pattern),
            reporter.nickname.ilike(pattern),
        ]
        if normalized_search.isdigit():
            search_conditions.extend(
                [
                    ArchiveReport.archive_id_snapshot == int(normalized_search),
                    ArchiveReport.id == int(normalized_search),
                ]
            )
        filters.append(or_(*search_conditions))
    if filters:
        statement = statement.where(*filters)

    total = int(
        await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    status_rank = case(
        (ArchiveReport.status == CommentReportStatus.PENDING.value, 0),
        (ArchiveReport.status == CommentReportStatus.UPHELD.value, 1),
        (ArchiveReport.status == CommentReportStatus.DISMISSED.value, 2),
        else_=3,
    )
    sort_fields = {
        "created_at": ArchiveReport.created_at,
        "status": status_rank,
        "reason": ArchiveReport.reason,
        "reporter": func.coalesce(
            reporter.nickname,
            reporter.name,
            ArchiveReport.reporter_name_snapshot,
        ),
        "course_archive": func.coalesce(ArchiveReport.course_name_snapshot, ""),
        "archive_id": ArchiveReport.archive_id_snapshot,
        "reviewer": func.coalesce(reviewer.nickname, reviewer.name, ""),
        "reviewed_at": ArchiveReport.reviewed_at,
    }
    sort_column = sort_fields.get(sort_by)
    if sort_column is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid archive report sort field",
        )
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    secondary_ordering = (
        (ArchiveReport.created_at.desc(), ArchiveReport.id.desc())
        if sort_by == "status"
        else (ArchiveReport.id.desc(),)
    )
    rows = (
        await db.execute(
            statement.order_by(ordering, *secondary_ordering)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return ArchiveReportListRead(
        items=[_serialize_archive_report(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/archives/{report_id}", response_model=ArchiveReportRead)
async def get_archive_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    return await _read_archive_report(db, report_id)


@router.delete("/admin/archives/{report_id}")
async def delete_archive_report(
    report_id: int,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    await acquire_archive_report_uniqueness_mutex_for_report(
        db,
        report_id=report_id,
    )
    locked = await acquire_stable_archive_report_locks(
        db,
        report_id=report_id,
        operation="archive_report_trash",
    )
    if locked is None or locked.report.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive report not found",
        )
    report = locked.report
    report.deleted_at = datetime.now(UTC)
    report.deleted_by_id = current_user.user_id
    db.add(report)
    await db.commit()
    return {"success": True}


@router.patch("/admin/archives/{report_id}", response_model=ArchiveReportRead)
async def review_archive_report(
    report_id: int,
    payload: ArchiveReportAdminUpdate,
    current_user: UserRoles = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    _require_admin(current_user)
    locked = await acquire_stable_archive_report_locks(
        db,
        report_id=report_id,
        operation="archive_report_review",
    )
    if locked is None or locked.report.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive report not found",
        )
    report = locked.report
    if report.status in FINAL_REPORT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized report cannot be changed",
        )

    new_status = payload.status.value
    if new_status not in FINAL_REPORT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A pending report must be finalized as upheld or dismissed",
        )
    if payload.take_down_archive and new_status != CommentReportStatus.UPHELD.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only an upheld report can take down the source archive",
        )

    if payload.take_down_archive:
        if report.archive_submission_id is None:
            archive = locked.archive
            if (
                archive is None
                or archive.id != report.archive_id
                or archive.deleted_at is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The source archive is no longer publicly available",
                )
            result = await soft_delete_archive_with_submission_takedown(
                db,
                archive=archive,
                submissions=(),
                user_id=current_user.user_id,
                reason=f"考古題回報 #{report.id} 成立",
            )
            if result["archives"] != 1 or result["submissions_takedown"] != 0:
                raise RuntimeError(
                    "Legacy ArchiveReport takedown did not mutate exactly one Archive"
                )
        else:
            submission = locked.submission
            if (
                submission is None
                or submission.id != report.archive_submission_id
                or submission.created_archive_id != report.archive_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The source archive submission no longer exists",
                )
            if (
                normalize_submission_status(submission.status)
                != SubmissionStatus.APPROVED
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The source archive is no longer publicly available",
                )
            await take_down_archive_submission(
                db,
                submission,
                reviewer_id=current_user.user_id,
                note=f"考古題回報 #{report.id} 成立",
            )
        report.archive_taken_down = True

    response = (payload.admin_response or "").strip()
    now = datetime.now(UTC)
    report.status = new_status
    report.admin_response = response or None
    report.reviewed_by = current_user.user_id
    report.reviewed_at = now
    report.updated_at = now
    db.add(report)

    result_label = (
        "回報成立" if new_status == CommentReportStatus.UPHELD.value else "回報不成立"
    )
    disposition = (
        "該考古題已下架。"
        if report.archive_taken_down
        else "管理員已完成處理；該考古題未因本次審核下架。"
    )
    if report.reporter_user_id is not None:
        course = (
            locked.rows.course(report.course_id)
            if report.course_id is not None
            else None
        )
        course_name_en = (
            course.name_en
            if course is not None and course.name == report.course_name_snapshot
            else None
        )
        await enqueue_personal_notification(
            db,
            user_id=report.reporter_user_id,
            notification_type=PersonalNotificationType.ARCHIVE_REPORT_RESULT,
            title="考古題回報審核完成",
            message=(
                f"{report.course_name_snapshot}－{report.archive_name_snapshot}"
                f"（考古題 #{report.archive_id_snapshot}）：{result_label}。"
                f"管理員答覆：{response or '未提供答覆'}。{disposition}"
            ),
            source_type="archive_report",
            source_id=report.id,
            metadata={
                "report_id": report.id,
                "course_id": report.course_id,
                "archive_id": report.archive_id,
                "course_name": report.course_name_snapshot,
                "course_name_en": course_name_en,
                "archive_name": report.archive_name_snapshot,
                "status": new_status,
                "archive_taken_down": report.archive_taken_down,
                "admin_response": response or None,
                "reviewed_at": now.isoformat(),
                "destination": "archive",
            },
            dedupe_key=f"archive_report_result:{report.id}",
        )

    await db.commit()
    return await _read_archive_report(db, report.id)
