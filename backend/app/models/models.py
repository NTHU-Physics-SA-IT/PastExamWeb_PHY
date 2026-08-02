from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Any, List, Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.utils.passwords import validate_api_password


class CourseCategory(str, PyEnum):
    FRESHMAN = "fundamental"
    SOPHOMORE = "required"
    JUNIOR = "experience"
    SENIOR = "optional"
    GRADUATE = "graduate"
    INTERDISCIPLINARY = "math-department"
    GENERAL = "general"


class ArchiveType(str, PyEnum):
    QUIZ = "quiz"
    MIDTERM = "midterm"
    FINAL = "final"
    OTHER = "other"


class NotificationSeverity(str, PyEnum):
    INFO = "info"
    DANGER = "danger"


class PersonalNotificationType(str, PyEnum):
    DISCUSSION_REPLY = "discussion_reply"
    DISCUSSION_LIKE = "discussion_like"
    DISCUSSION_PIN = "discussion_pin"
    COMMENT_REPORT_SUBMITTED = "comment_report_submitted"
    COMMENT_REPORT_RESULT = "comment_report_result"
    ARCHIVE_REPORT_SUBMITTED = "archive_report_submitted"
    ARCHIVE_REPORT_RESULT = "archive_report_result"
    ARCHIVE_SUBMISSION_APPROVED = "archive_submission_approved"
    ARCHIVE_SUBMISSION_REJECTED = "archive_submission_rejected"
    ARCHIVE_SUBMISSION_TAKEDOWN = "archive_submission_takedown"
    ARCHIVE_SUBMISSION_REPUBLISHED = "archive_submission_republished"


class CommentReportReason(str, PyEnum):
    SPAM_OR_DUPLICATE = "spam_or_duplicate"
    HARASSMENT_OR_HOSTILITY = "harassment_or_hostility"
    INAPPROPRIATE_OR_ILLEGAL = "inappropriate_or_illegal"
    PRIVACY_VIOLATION = "privacy_violation"
    MISINFORMATION = "misinformation"
    OTHER = "other"


class ArchiveReportReason(str, PyEnum):
    FILE_UNAVAILABLE_OR_CORRUPT = "file_unavailable_or_corrupt"
    METADATA_MISMATCH = "metadata_mismatch"
    DUPLICATE_ARCHIVE = "duplicate_archive"
    INCOMPLETE_OR_LOW_QUALITY = "incomplete_or_low_quality"
    PERSONAL_INFORMATION = "personal_information"
    OTHER = "other"


class CommentReportStatus(str, PyEnum):
    PENDING = "pending"
    UPHELD = "upheld"
    DISMISSED = "dismissed"


class TrashEntityType(str, PyEnum):
    ARCHIVE = "archive"
    ARCHIVE_SUBMISSION = "archive_submission"
    COURSE_CATEGORY = "course_category"
    COURSE = "course"
    SYSTEM_ISSUE_REPORT = "system_issue_report"
    COMMENT_REPORT = "comment_report"
    ARCHIVE_REPORT = "archive_report"
    NOTIFICATION = "notification"
    USER = "user"


class SubmissionStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELETED = "deleted"
    TAKEDOWN = "takedown"


class ArchiveSubmissionAdminAction(str, PyEnum):
    APPROVE = "approve"
    REJECT = "reject"
    TAKEDOWN = "takedown"
    REPUBLISH = "republish"
    DELETE = "delete"


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    oauth_provider: Optional[str] = Field(default=None)
    oauth_sub: Optional[str] = Field(default=None)
    email: str = Field(unique=True, index=True)
    name: str = Field(unique=True, index=True)
    nickname: Optional[str] = Field(default=None, index=True)
    show_level_title: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
    )
    is_admin: bool = Field(default=False)
    password_hash: Optional[str] = Field(default=None)
    is_local: bool = Field(default=False)
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    last_login: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_seen_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_logout: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    archives: List["Archive"] = Relationship(back_populates="uploader")


class UserPresenceSession(SQLModel, table=True):
    __tablename__ = "user_presence_sessions"
    __table_args__ = (
        Index("ix_user_presence_sessions_user_started", "user_id", "started_at"),
        Index("ix_user_presence_sessions_identifier", "session_identifier"),
        Index("ix_user_presence_sessions_last_seen", "last_seen_at"),
        Index("ix_user_presence_sessions_ended", "ended_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    session_identifier: str = Field(sa_column=Column(String(64), nullable=False))
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_seen_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    ended_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class CourseCategoryConfig(SQLModel, table=True):
    __tablename__ = "course_category_configs"
    __table_args__ = (
        UniqueConstraint("key"),
        Index("ix_course_category_configs_key", "key", unique=True),
        Index(
            "uq_course_category_configs_normalized_name",
            text("lower(btrim(name))"),
            unique=True,
        ),
        Index(
            "uq_course_category_configs_normalized_key",
            text("lower(btrim(key))"),
            unique=True,
        ),
        CheckConstraint(
            "lower(btrim(key)) NOT IN "
            "('freshman', 'sophomore', 'junior', 'senior', 'interdisciplinary')",
            name="ck_course_category_configs_no_legacy_key",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(String, nullable=False))
    name: str = Field(index=True)
    label: str = Field(
        default="",
        sa_column=Column(String, nullable=False, server_default=text("''")),
    )
    icon: str = Field(
        default="pi pi-fw pi-book",
        sa_column=Column(
            String,
            nullable=False,
            server_default=text("'pi pi-fw pi-book'"),
        ),
    )
    badge_color: str = Field(
        default="blue",
        sa_column=Column(String, nullable=False, server_default="blue"),
    )
    order_index: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            index=True,
            server_default=text("0"),
        ),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            index=True,
            server_default=text("true"),
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: Optional[int] = Field(default=None)
    restored_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: Optional[int] = Field(default=None)


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("key", name="uq_system_settings_key"),
        Index("ix_system_settings_key", "key"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(
        sa_column=Column(String(128), nullable=False)
    )
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        )
    )
    updated_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class Course(SQLModel, table=True):
    __tablename__ = "courses"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    category: str = Field(index=True)
    order_index: int = Field(default=0, index=True)
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: Optional[int] = Field(default=None)
    restored_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: Optional[int] = Field(default=None)

    archives: List["Archive"] = Relationship(back_populates="course")


class Archive(SQLModel, table=True):
    __tablename__ = "archives"
    id: Optional[int] = Field(default=None, primary_key=True)

    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str = Field(index=True)
    has_answers: bool = False
    download_count: int = Field(default=0)

    object_name: str

    uploader_id: Optional[int] = Field(default=None, foreign_key="users.id")
    uploader: Optional["User"] = Relationship(back_populates="archives")

    course_id: int = Field(foreign_key="courses.id")
    course: "Course" = Relationship(back_populates="archives")

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: Optional[int] = Field(default=None)
    deleted_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    restored_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: Optional[int] = Field(default=None)


class CourseSubmission(SQLModel, table=True):
    __tablename__ = "course_submissions"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    category: str = Field(index=True)
    status: SubmissionStatus = Field(default=SubmissionStatus.PENDING, index=True)
    requester_id: int = Field(foreign_key="users.id", index=True)
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id")
    review_note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_course_id: Optional[int] = Field(default=None, foreign_key="courses.id")
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    reviewed_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class ArchiveSubmission(SQLModel, table=True):
    __tablename__ = "archive_submissions"
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    category: str = Field(index=True)
    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str = Field(index=True)
    has_answers: bool = False
    object_name: str
    requested_course_name: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    requested_category_key: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    requested_category_name: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    requested_category_label: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    requested_category_icon: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    status: SubmissionStatus = Field(default=SubmissionStatus.PENDING, index=True)
    requester_id: int = Field(foreign_key="users.id", index=True)
    owner_id: Optional[int] = Field(default=None)
    owner_self_delete_consumed: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id")
    review_note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    is_admin_upload: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    lifecycle_reason: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    created_archive_id: Optional[int] = Field(default=None, foreign_key="archives.id")
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: Optional[int] = Field(default=None)
    delete_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    restored_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    reviewed_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class ArchiveSubmissionEvent(SQLModel, table=True):
    """Minimal immutable ledger entry for a submission creation event."""

    __tablename__ = "archive_submission_events"
    __table_args__ = (
        Index("ix_archive_submission_events_submitted_at", "submitted_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(unique=True, index=True)
    submitted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class ArchiveDiscussionMessage(SQLModel, table=True):
    __tablename__ = "archive_discussion_messages"
    __table_args__ = (
        Index(
            "ix_archive_discussion_messages_archive_parent",
            "archive_id",
            "parent_id",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    archive_id: int = Field(foreign_key="archives.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id"),
            nullable=True,
            index=True,
        ),
    )
    reply_to_message_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id"),
            nullable=True,
            index=True,
        ),
    )
    content: str = Field(sa_column=Column(Text, nullable=False))
    is_pinned: bool = Field(default=False, index=True)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class ArchiveDiscussionLike(SQLModel, table=True):
    __tablename__ = "archive_discussion_likes"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_archive_discussion_likes_message_user",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )


class Meme(SQLModel, table=True):
    __tablename__ = "memes"
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    language: str


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(150), nullable=False))
    body: str = Field(sa_column=Column(Text, nullable=False))
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO)
    is_active: bool = Field(default=True)
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    starts_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ends_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
        )
    )
    updated_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    deleted_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class AnnouncementReadReceipt(SQLModel, table=True):
    __tablename__ = "announcement_read_receipts"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_announcement_read_receipts_notification_user",
        ),
        Index("ix_announcement_read_receipts_user_read", "user_id", "read_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    notification_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    read_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )


class PersonalNotification(SQLModel, table=True):
    __tablename__ = "personal_notifications"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key", name="uq_personal_notifications_dedupe_key"
        ),
        Index(
            "ix_personal_notifications_user_read_created",
            "user_id",
            "read_at",
            "created_at",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    notification_type: str = Field(
        sa_column=Column(String(50), nullable=False, index=True)
    )
    title: str = Field(sa_column=Column(String(150), nullable=False))
    message: str = Field(sa_column=Column(Text, nullable=False))
    source_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(50), nullable=True, index=True),
    )
    source_id: Optional[int] = Field(default=None, index=True)
    source_message_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    dedupe_key: str = Field(sa_column=Column(String(160), nullable=False))
    read_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )


class CommentReport(SQLModel, table=True):
    __tablename__ = "comment_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'upheld', 'dismissed')",
            name="ck_comment_reports_status",
        ),
        Index(
            "uq_comment_reports_active_reporter_comment_reason",
            "reporter_user_id",
            "comment_id",
            "reason",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_comment_reports_status_created", "status", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    reporter_user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    comment_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    comment_author_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    archive_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("archives.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    course_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    thread_id: Optional[int] = Field(default=None, index=True)
    reply_to_message_id: Optional[int] = Field(default=None)
    reason: str = Field(sa_column=Column(String(50), nullable=False, index=True))
    custom_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    comment_content_snapshot: str = Field(sa_column=Column(Text, nullable=False))
    comment_author_name_snapshot: str = Field(sa_column=Column(String(100), nullable=False))
    comment_created_at_snapshot: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    archive_name_snapshot: str = Field(sa_column=Column(String(200), nullable=False))
    course_name_snapshot: str = Field(sa_column=Column(String(200), nullable=False))
    status: str = Field(
        default=CommentReportStatus.PENDING.value,
        sa_column=Column(
            String(30),
            nullable=False,
            index=True,
            server_default=text("'pending'"),
        ),
    )
    admin_response: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    reviewed_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    reviewed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=True)
    )
    comment_deleted: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class ArchiveReport(SQLModel, table=True):
    __tablename__ = "archive_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'upheld', 'dismissed')",
            name="ck_archive_reports_status",
        ),
        Index(
            "uq_archive_reports_pending_reporter_archive",
            "reporter_user_id",
            "archive_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_archive_reports_status_created", "status", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    reporter_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reporter_name_snapshot: str = Field(
        sa_column=Column(String(100), nullable=False)
    )
    archive_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archives.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    archive_id_snapshot: int = Field(sa_column=Column(Integer, nullable=False))
    course_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    archive_submission_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_submissions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reason: str = Field(sa_column=Column(String(60), nullable=False, index=True))
    supplementary_detail: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    archive_name_snapshot: str = Field(
        sa_column=Column(String(200), nullable=False)
    )
    course_name_snapshot: str = Field(
        sa_column=Column(String(200), nullable=False)
    )
    academic_year_snapshot: int = Field(sa_column=Column(Integer, nullable=False))
    archive_type_snapshot: str = Field(
        sa_column=Column(String(30), nullable=False)
    )
    professor_snapshot: str = Field(
        sa_column=Column(String(200), nullable=False)
    )
    status: str = Field(
        default=CommentReportStatus.PENDING.value,
        sa_column=Column(
            String(30),
            nullable=False,
            index=True,
            server_default=text("'pending'"),
        ),
    )
    admin_response: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    reviewed_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    archive_taken_down: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class SystemIssueReport(SQLModel, table=True):
    __tablename__ = "system_issue_reports"
    __table_args__ = (
        Index("ix_system_issue_reports_status_created", "status", "created_at"),
        Index("ix_system_issue_reports_read_at_created", "read_at", "created_at"),
        Index(
            "ix_system_issue_reports_github_sync_status",
            "github_sync_status",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    reporter_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    report_type: str = Field(sa_column=Column(String(40), nullable=False, index=True))
    title: str = Field(sa_column=Column(String(100), nullable=False))
    description: str = Field(sa_column=Column(Text, nullable=False))
    contact: Optional[str] = Field(default=None, sa_column=Column(String(200), nullable=True))
    status: str = Field(
        default="local_only",
        sa_column=Column(
            String(30),
            nullable=False,
            index=True,
            server_default=text("'local_only'"),
        ),
    )
    github_issue_number: Optional[int] = Field(default=None, index=True)
    github_issue_url: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    github_issue_state: Optional[str] = Field(
        default=None,
        sa_column=Column(String(20), nullable=True),
    )
    github_linked_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    github_sync_status: str = Field(
        default="pending",
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=text("'pending'"),
        ),
    )
    github_sync_error: Optional[str] = Field(
        default=None,
        sa_column=Column(String(300), nullable=True),
    )
    read_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    read_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class UserRead(BaseModel):
    id: int
    email: str
    name: str
    nickname: Optional[str] = None
    show_level_title: bool = True
    is_admin: bool
    is_local: bool
    last_login: Optional[datetime]
    last_login_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    last_logout_at: Optional[datetime] = None
    is_online: bool = False
    online_status_label: Optional[str] = None
    contributor_experience: int = 0

    class Config:
        from_attributes = True


class OnlineStatisticsPoint(BaseModel):
    start: datetime
    end: datetime
    at: datetime
    count: int
    has_data: bool


class OnlineStatisticsRead(BaseModel):
    range: str
    bucket_minutes: int
    timezone: str = "UTC"
    online_timeout_seconds: int
    current_online: int
    peak_online: int
    average_online: float
    history_started_at: Optional[datetime] = None
    points: List[OnlineStatisticsPoint] = Field(default_factory=list)


class SubmissionStatisticsSummary(BaseModel):
    total: int
    peak: int
    average: float


class SubmissionStatisticsPoint(BaseModel):
    start: datetime
    end: datetime
    count: int


class SubmissionStatisticsRead(BaseModel):
    mode: str
    range: str
    timezone: str
    bucket_minutes: int
    range_start: datetime
    range_end: datetime
    summary: SubmissionStatisticsSummary
    points: List[SubmissionStatisticsPoint] = Field(default_factory=list)


class UserOnlineDurationPoint(BaseModel):
    start: datetime
    end: datetime
    duration_seconds: int
    has_data: bool = False


class UserOnlineDurationRead(BaseModel):
    user_id: int
    mode: str
    timezone: str
    online_timeout_seconds: int
    range_start: datetime
    range_end: datetime
    history_started_at: Optional[datetime] = None
    points: List[UserOnlineDurationPoint] = Field(default_factory=list)


class UserSubmissionStatusCounts(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    takedown: int = 0
    deleted: int = 0


class UserSubmissionRecordRead(BaseModel):
    id: int
    status: SubmissionStatus
    archive_type: ArchiveType
    course_name: str
    exam_name: str
    academic_year: int
    professor: str
    has_answers: bool = False
    requested_course_name: Optional[str] = None
    requested_category_key: Optional[str] = None
    is_admin_upload: bool = False
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None


class UserSubmissionStatsRead(BaseModel):
    user_id: int
    name: str
    contributor_experience: int = 0
    total_count: int = 0
    status_counts: UserSubmissionStatusCounts
    records_total: int = 0
    submission_records: List[UserSubmissionRecordRead] = Field(default_factory=list)


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    is_admin: bool = False

    _validate_password = field_validator("password")(validate_api_password)


class UserPasswordResetRequest(BaseModel):
    new_password: str

    _validate_password = field_validator("new_password")(validate_api_password)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None

    _validate_password = field_validator("password")(validate_api_password)


class UserNicknameUpdate(BaseModel):
    nickname: str
    show_level_title: Optional[bool] = None


class UserRoles(BaseModel):
    user_id: int
    is_admin: bool = False

    class Config:
        from_attributes = True


class MemeRead(BaseModel):
    id: int
    content: str
    language: str

    class Config:
        from_attributes = True


class NotificationBase(BaseModel):
    title: str
    body: str
    severity: NotificationSeverity = NotificationSeverity.INFO
    is_active: bool = True
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class NotificationCreate(NotificationBase):
    pass


class NotificationUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    severity: Optional[NotificationSeverity] = None
    is_active: Optional[bool] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class NotificationRead(NotificationBase):
    id: int
    created_at: datetime
    updated_at: datetime
    updated_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class AnnouncementWithRead(NotificationRead):
    is_read: bool = False
    read_at: Optional[datetime] = None


class PersonalNotificationRead(BaseModel):
    id: int
    notification_type: str
    title: str
    message: str
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_message_id: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_available: bool = True
    read_at: Optional[datetime] = None
    created_at: datetime


class CommentReportCreate(BaseModel):
    report_reason: CommentReportReason
    custom_message: Optional[str] = Field(default=None, max_length=200)


class CommentReportAdminUpdate(BaseModel):
    status: CommentReportStatus
    admin_response: Optional[str] = Field(default=None, max_length=1000)
    delete_comment: bool = False


class CommentReportRead(BaseModel):
    id: int
    reporter_user_id: int
    reporter_name: str
    comment_id: Optional[int]
    comment_author_id: Optional[int]
    comment_author_name: str
    archive_id: Optional[int]
    course_id: Optional[int]
    thread_id: Optional[int]
    reply_to_message_id: Optional[int]
    reason: str
    custom_message: Optional[str]
    comment_content_snapshot: str
    comment_created_at_snapshot: datetime
    archive_name: str
    course_name: str
    status: str
    admin_response: Optional[str]
    reviewed_by: Optional[int]
    reviewer_name: Optional[str]
    reviewed_at: Optional[datetime]
    comment_deleted: bool
    source_exists: bool
    created_at: datetime
    updated_at: datetime


class CommentReportListRead(BaseModel):
    items: List[CommentReportRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class ArchiveReportCreate(BaseModel):
    report_reason: ArchiveReportReason
    supplementary_detail: Optional[str] = Field(default=None, max_length=1000)


class ArchiveReportAdminUpdate(BaseModel):
    status: CommentReportStatus
    admin_response: Optional[str] = Field(default=None, max_length=1000)
    take_down_archive: bool = False


class ArchiveReportRead(BaseModel):
    id: int
    reporter_user_id: Optional[int]
    reporter_name: str
    archive_id: Optional[int]
    archive_id_snapshot: int
    course_id: Optional[int]
    archive_submission_id: Optional[int]
    reason: str
    supplementary_detail: Optional[str]
    archive_name: str
    course_name: str
    academic_year: int
    archive_type: str
    professor: str
    status: str
    admin_response: Optional[str]
    reviewed_by: Optional[int]
    reviewer_name: Optional[str]
    reviewed_at: Optional[datetime]
    archive_taken_down: bool
    source_exists: bool
    source_state: str
    can_take_down: bool
    created_at: datetime
    updated_at: datetime


class ArchiveReportListRead(BaseModel):
    items: List[ArchiveReportRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class SystemIssueReportCreate(BaseModel):
    report_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    contact: Optional[str] = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemIssueReportRead(BaseModel):
    id: int
    reporter_user_id: Optional[int]
    reporter_name: str
    report_type: str
    title: str
    description: str
    contact: Optional[str]
    status: str
    github_issue_number: Optional[int]
    github_issue_url: Optional[str]
    is_read: bool = False
    read_at: Optional[datetime]
    read_by_username: Optional[str]
    created_at: datetime
    updated_at: datetime


class SystemIssueReportReadStateUpdate(BaseModel):
    is_read: bool


class SystemIssueReportListRead(BaseModel):
    items: List[SystemIssueReportRead] = Field(default_factory=list)
    total: int = 0


class NotificationUnreadCounts(BaseModel):
    announcements: int = 0
    personal_notifications: int = 0
    total: int = 0


class NotificationCenterRead(BaseModel):
    announcements: List[AnnouncementWithRead] = Field(default_factory=list)
    personal_notifications: List[PersonalNotificationRead] = Field(default_factory=list)
    counts: NotificationUnreadCounts = Field(default_factory=NotificationUnreadCounts)


class NotificationUnreadSummary(NotificationCenterRead):
    pass


class CourseInfo(BaseModel):
    id: int
    name: str
    order_index: int = 0

    class Config:
        from_attributes = True


class CoursesByCategory(BaseModel):
    courses: dict[str, List[CourseInfo]] = {}

    class Config:
        from_attributes = True


class ArchiveRead(BaseModel):
    id: int
    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str
    has_answers: bool
    created_at: datetime
    uploader_id: Optional[int] = None
    download_count: int = 0
    source_submission_ids: List[int] = []

    class Config:
        from_attributes = True


class ArchiveDiscussionMessageRead(BaseModel):
    id: int
    archive_id: int
    user_id: int
    user_name: str
    author_show_level_title: bool = False
    author_experience: Optional[int] = None
    content: str
    is_pinned: bool = False
    is_deleted: bool = False
    parent_id: Optional[int] = None
    reply_to_message_id: Optional[int] = None
    reply_to_user_name: Optional[str] = None
    like_count: int = 0
    liked_by_current_user: bool = False
    replies: List["ArchiveDiscussionMessageRead"] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class CourseCreate(BaseModel):
    name: str
    category: str
    order_index: Optional[int] = None


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    order_index: Optional[int] = None


class CourseReorder(BaseModel):
    category: str
    course_ids: List[int]


class CourseRead(BaseModel):
    id: int
    name: str
    category: str
    order_index: int = 0

    class Config:
        from_attributes = True


class ArchiveUpdateCourse(BaseModel):
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    course_category: Optional[str] = None


class CourseSubmissionCreate(BaseModel):
    name: str
    category: str


class CourseCategoryCreate(BaseModel):
    key: str
    name: str
    label: str = ""
    icon: str = "pi pi-fw pi-book"
    badge_color: Optional[str] = None
    order_index: Optional[int] = None


class CourseCategoryUpdate(BaseModel):
    key: Optional[str] = None
    name: Optional[str] = None
    label: Optional[str] = None
    icon: Optional[str] = None
    badge_color: Optional[str] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None


class CourseCategoryReorder(BaseModel):
    category_ids: List[int]


class CourseCategoryRead(BaseModel):
    id: int
    key: str
    name: str
    label: str
    icon: str
    badge_color: str = "blue"
    order_index: int
    is_active: bool

    class Config:
        from_attributes = True


class SubmissionDecision(BaseModel):
    note: Optional[str] = None
    expected_status: Optional[SubmissionStatus] = None


class CourseSubmissionRead(BaseModel):
    id: int
    name: str
    category: str
    status: SubmissionStatus
    requester_id: int
    reviewer_id: Optional[int] = None
    review_note: Optional[str] = None
    created_course_id: Optional[int] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArchiveSubmissionRead(BaseModel):
    id: int
    subject: str
    category: str
    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str
    has_answers: bool
    requested_course_name: Optional[str] = None
    requested_category_key: Optional[str] = None
    requested_category_name: Optional[str] = None
    requested_category_label: Optional[str] = None
    requested_category_icon: Optional[str] = None
    status: SubmissionStatus
    requester_id: int
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    is_admin_upload: bool = False
    reviewer_id: Optional[int] = None
    reviewer_name: Optional[str] = None
    reviewer_email: Optional[str] = None
    review_note: Optional[str] = None
    created_archive_id: Optional[int] = None
    lifecycle_reason: Optional[str] = None
    linked_archive_deleted: bool = False
    linked_course_deleted: bool = False
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArchiveSubmissionAdminRead(ArchiveSubmissionRead):
    available_actions: List[ArchiveSubmissionAdminAction]


class ArchiveSubmissionActionRead(ArchiveSubmissionAdminRead):
    changed: bool


class ArchiveSubmissionComparisonRead(ArchiveSubmissionRead):
    can_takedown: bool = False


class CourseSubmissionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None


class ArchiveSubmissionUpdate(BaseModel):
    subject: Optional[str] = None
    category: Optional[str] = None
    name: Optional[str] = None
    academic_year: Optional[int] = None
    archive_type: Optional[ArchiveType] = None
    professor: Optional[str] = None
    has_answers: Optional[bool] = None
    requested_course_name: Optional[str] = None
    requested_category_key: Optional[str] = None
    requested_category_name: Optional[str] = None
    requested_category_label: Optional[str] = None
    requested_category_icon: Optional[str] = None


class TrashItem(BaseModel):
    item_type: TrashEntityType
    id: int
    display_name: str
    academic_year: Optional[int] = None
    academic_term: Optional[str] = None
    deleted_at: datetime
    deleted_by_id: Optional[int] = None
    deleted_by_name: Optional[str] = None
    user_email: Optional[str] = None
    status: Optional[str] = None
    parent_type: Optional[str] = None
    parent_id: Optional[int] = None
    parent_name: Optional[str] = None
    created_archive_id: Optional[int] = None
    source_submission_id: Optional[int] = None
    course_id: Optional[int] = None
    course_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    reporter_name: Optional[str] = None
    report_type: Optional[str] = None
    github_issue_number: Optional[int] = None
    github_issue_url: Optional[str] = None
    comment_author_name: Optional[str] = None
    comment_snapshot: Optional[str] = None
    archive_name: Optional[str] = None
    canRestore: Optional[bool] = None
    canPermanentDelete: Optional[bool] = None
    dependencies: List[str] = []
