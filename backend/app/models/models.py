from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import Any, Optional

from pydantic import BaseModel, field_validator, model_validator
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
    COURSE_SUBMISSION = "course_submission"
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
    __table_args__ = (
        UniqueConstraint(
            "oauth_provider",
            "oauth_sub",
            name="uq_users_oauth_provider_sub",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    oauth_provider: str | None = Field(default=None)
    oauth_sub: str | None = Field(default=None)
    student_id: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    email: str = Field(unique=True, index=True)
    name: str = Field(unique=True, index=True)
    nickname: str | None = Field(default=None, index=True)
    show_level_title: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
    )
    is_admin: bool = Field(default=False)
    password_hash: str | None = Field(default=None)
    is_local: bool = Field(default=False)
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    last_login: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_seen_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_logout: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    archives: list["Archive"] = Relationship(back_populates="uploader")


class UserPresenceSession(SQLModel, table=True):
    __tablename__ = "user_presence_sessions"
    __table_args__ = (
        Index("ix_user_presence_sessions_user_started", "user_id", "started_at"),
        Index("ix_user_presence_sessions_identifier", "session_identifier"),
        Index("ix_user_presence_sessions_last_seen", "last_seen_at"),
        Index("ix_user_presence_sessions_ended", "ended_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
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
    ended_at: datetime | None = Field(
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
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(String, nullable=False))
    name: str = Field(index=True)
    name_en: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
    label: str = Field(
        default="",
        sa_column=Column(String, nullable=False, server_default=text("''")),
    )
    label_en: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
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
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    pre_delete_is_active: bool | None = Field(
        default=None,
        sa_column=Column(Boolean, nullable=True),
    )
    deleted_by_id: int | None = Field(default=None)
    restored_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: int | None = Field(default=None)


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"
    __table_args__ = (
        UniqueConstraint("key", name="uq_system_settings_key"),
        Index("ix_system_settings_key", "key"),
    )
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(String(128), nullable=False))
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        )
    )
    updated_by_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class Course(SQLModel, table=True):
    __tablename__ = "courses"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    name_en: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
    category: str = Field(index=True)
    order_index: int = Field(default=0, index=True)
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: int | None = Field(default=None)
    restored_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: int | None = Field(default=None)

    archives: list["Archive"] = Relationship(back_populates="course")


class Archive(SQLModel, table=True):
    __tablename__ = "archives"
    id: int | None = Field(default=None, primary_key=True)

    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str = Field(index=True)
    has_answers: bool = False
    download_count: int = Field(default=0)

    object_name: str

    uploader_id: int | None = Field(default=None, foreign_key="users.id")
    uploader: Optional["User"] = Relationship(back_populates="archives")

    course_id: int = Field(foreign_key="courses.id")
    course: "Course" = Relationship(back_populates="archives")

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: int | None = Field(default=None)
    deleted_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    restored_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: int | None = Field(default=None)


class CourseSubmission(SQLModel, table=True):
    __tablename__ = "course_submissions"
    __table_args__ = (
        CheckConstraint(
            "previous_status IS NULL OR CAST(previous_status AS TEXT) <> 'DELETED'",
            name="ck_course_submissions_previous_status_not_deleted",
        ),
        CheckConstraint(
            "deleted_at IS NOT NULL "
            "OR CAST(status AS TEXT) = 'DELETED' "
            "OR previous_status IS NULL",
            name="ck_course_submissions_active_previous_status_null",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    category: str = Field(index=True)
    status: SubmissionStatus = Field(default=SubmissionStatus.PENDING, index=True)
    previous_status: SubmissionStatus | None = Field(default=None)
    requester_id: int = Field(foreign_key="users.id", index=True)
    reviewer_id: int | None = Field(default=None, foreign_key="users.id")
    review_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_course_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    reviewed_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: int | None = Field(default=None)
    restored_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    restored_by_id: int | None = Field(default=None)


class ArchiveSubmission(SQLModel, table=True):
    __tablename__ = "archive_submissions"
    __table_args__ = (
        UniqueConstraint(
            "created_archive_id",
            name="uq_archive_submissions_created_archive_id",
        ),
        CheckConstraint(
            "previous_status IS NULL OR CAST(previous_status AS TEXT) <> 'DELETED'",
            name="ck_archive_submissions_previous_status_not_deleted",
        ),
        CheckConstraint(
            "deleted_at IS NOT NULL "
            "OR CAST(status AS TEXT) = 'DELETED' "
            "OR previous_status IS NULL",
            name="ck_archive_submissions_active_previous_status_null",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    category: str = Field(index=True)
    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str = Field(index=True)
    has_answers: bool = False
    object_name: str
    requested_course_name: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_course_name_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_key: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_name: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_name_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_label: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_label_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_icon: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    source_wish_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_wishes.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    status: SubmissionStatus = Field(default=SubmissionStatus.PENDING, index=True)
    previous_status: SubmissionStatus | None = Field(default=None)
    requester_id: int = Field(foreign_key="users.id", index=True)
    owner_id: int | None = Field(default=None)
    owner_self_delete_consumed: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    reviewer_id: int | None = Field(default=None, foreign_key="users.id")
    review_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    is_admin_upload: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    lifecycle_reason: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    created_archive_id: int | None = Field(default=None, foreign_key="archives.id")
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    deleted_by_id: int | None = Field(default=None)
    delete_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    restored_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    restored_by_id: int | None = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    reviewed_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class ArchiveSubmissionEvent(SQLModel, table=True):
    """Minimal immutable ledger entry for a submission creation event."""

    __tablename__ = "archive_submission_events"
    __table_args__ = (
        Index("ix_archive_submission_events_submitted_at", "submitted_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
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
    id: int | None = Field(default=None, primary_key=True)
    archive_id: int = Field(foreign_key="archives.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    parent_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id"),
            nullable=True,
            index=True,
        ),
    )
    reply_to_message_id: int | None = Field(
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
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    deleted_at: datetime | None = Field(
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

    id: int | None = Field(default=None, primary_key=True)
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
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )


class Meme(SQLModel, table=True):
    __tablename__ = "memes"
    id: int | None = Field(default=None, primary_key=True)
    content: str
    language: str


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(150), nullable=False))
    body: str = Field(sa_column=Column(Text, nullable=False))
    title_en: str | None = Field(
        default=None, sa_column=Column(String(150), nullable=True)
    )
    body_en: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO)
    is_active: bool = Field(default=True)
    deleted_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    starts_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ends_at: datetime | None = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
        )
    )
    updated_by_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    deleted_by_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class AboutUsEntry(SQLModel, table=True):
    __tablename__ = "about_us_entries"
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(150), nullable=False))
    body: str = Field(sa_column=Column(Text, nullable=False))
    title_en: str | None = Field(
        default=None, sa_column=Column(String(150), nullable=True)
    )
    body_en: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    updated_by_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


class ArchiveWish(SQLModel, table=True):
    __tablename__ = "archive_wishes"
    __table_args__ = (
        UniqueConstraint("target_key", name="uq_archive_wishes_target_key"),
        Index("ix_archive_wishes_created_id", "created_at", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(150), nullable=False))
    target_key: str = Field(sa_column=Column(String(64), nullable=False))
    course_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    subject: str = Field(sa_column=Column(String(200), nullable=False))
    category: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    name: str = Field(sa_column=Column(String(100), nullable=False))
    academic_year: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    archive_type: ArchiveType = Field(index=True)
    professor: str = Field(sa_column=Column(String(200), nullable=False, index=True))
    requested_course_name: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_course_name_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_key: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_name: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_name_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_label: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_label_en: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    requested_category_icon: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    creator_id: int = Field(
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
            default=lambda: datetime.now(UTC),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )


class ArchiveWishHeart(SQLModel, table=True):
    __tablename__ = "archive_wish_hearts"
    __table_args__ = (
        UniqueConstraint("wish_id", "user_id", name="uq_archive_wish_hearts_wish_user"),
        Index("ix_archive_wish_hearts_wish_created", "wish_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    wish_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("archive_wishes.id", ondelete="CASCADE"),
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
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )


class ArchiveWishReport(SQLModel, table=True):
    __tablename__ = "archive_wish_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'upheld', 'dismissed')",
            name="ck_archive_wish_reports_status",
        ),
        UniqueConstraint(
            "wish_id",
            "reporter_user_id",
            name="uq_archive_wish_reports_wish_reporter",
        ),
        Index("ix_archive_wish_reports_status_created", "status", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    wish_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_wishes.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reporter_user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    wish_title_snapshot: str = Field(sa_column=Column(String(150), nullable=False))
    target_summary_snapshot: str = Field(sa_column=Column(Text, nullable=False))
    reason: str = Field(sa_column=Column(String(50), nullable=False, index=True))
    custom_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    status: str = Field(
        default=CommentReportStatus.PENDING.value,
        sa_column=Column(
            String(30), nullable=False, index=True, server_default=text("'pending'")
        ),
    )
    admin_response: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    reviewed_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reviewed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
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

    id: int | None = Field(default=None, primary_key=True)
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
        UniqueConstraint("dedupe_key", name="uq_personal_notifications_dedupe_key"),
        Index(
            "ix_personal_notifications_user_read_created",
            "user_id",
            "read_at",
            "created_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
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
    source_type: str | None = Field(
        default=None,
        sa_column=Column(String(50), nullable=True, index=True),
    )
    source_id: int | None = Field(default=None, index=True)
    source_message_id: int | None = Field(
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
    read_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
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

    id: int | None = Field(default=None, primary_key=True)
    reporter_user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    comment_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_discussion_messages.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    comment_author_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    archive_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archives.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    course_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    thread_id: int | None = Field(default=None, index=True)
    reply_to_message_id: int | None = Field(default=None)
    reason: str = Field(sa_column=Column(String(50), nullable=False, index=True))
    custom_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    comment_content_snapshot: str = Field(sa_column=Column(Text, nullable=False))
    comment_author_name_snapshot: str = Field(
        sa_column=Column(String(100), nullable=False)
    )
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
    admin_response: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    reviewed_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    comment_deleted: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: int | None = Field(
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

    id: int | None = Field(default=None, primary_key=True)
    reporter_user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reporter_name_snapshot: str = Field(sa_column=Column(String(100), nullable=False))
    archive_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archives.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    archive_id_snapshot: int = Field(sa_column=Column(Integer, nullable=False))
    course_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    archive_submission_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("archive_submissions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reason: str = Field(sa_column=Column(String(60), nullable=False, index=True))
    supplementary_detail: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    archive_name_snapshot: str = Field(sa_column=Column(String(200), nullable=False))
    course_name_snapshot: str = Field(sa_column=Column(String(200), nullable=False))
    academic_year_snapshot: int = Field(sa_column=Column(Integer, nullable=False))
    archive_type_snapshot: str = Field(sa_column=Column(String(30), nullable=False))
    professor_snapshot: str = Field(sa_column=Column(String(200), nullable=False))
    status: str = Field(
        default=CommentReportStatus.PENDING.value,
        sa_column=Column(
            String(30),
            nullable=False,
            index=True,
            server_default=text("'pending'"),
        ),
    )
    admin_response: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    reviewed_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    reviewed_at: datetime | None = Field(
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
            default=lambda: datetime.now(UTC),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: int | None = Field(
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

    id: int | None = Field(default=None, primary_key=True)
    reporter_user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    report_type: str = Field(sa_column=Column(String(40), nullable=False, index=True))
    title: str = Field(sa_column=Column(String(100), nullable=False))
    description: str = Field(sa_column=Column(Text, nullable=False))
    contact: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    status: str = Field(
        default="local_only",
        sa_column=Column(
            String(30),
            nullable=False,
            index=True,
            server_default=text("'local_only'"),
        ),
    )
    github_issue_number: int | None = Field(default=None, index=True)
    github_issue_url: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    github_issue_state: str | None = Field(
        default=None,
        sa_column=Column(String(20), nullable=True),
    )
    github_linked_at: datetime | None = Field(
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
    github_sync_error: str | None = Field(
        default=None,
        sa_column=Column(String(300), nullable=True),
    )
    read_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    read_by_user_id: int | None = Field(
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
            default=lambda: datetime.now(UTC),
            nullable=False,
            index=True,
            server_default=text("now()"),
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            nullable=False,
            server_default=text("now()"),
        )
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    deleted_by_id: int | None = Field(
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
    nickname: str | None = None
    show_level_title: bool = True
    is_admin: bool
    is_local: bool
    last_login: datetime | None
    last_login_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_logout_at: datetime | None = None
    is_online: bool = False
    online_status_label: str | None = None
    contributor_experience: int = 0

    class Config:
        from_attributes = True


class AdminUserRead(UserRead):
    account_source: str
    student_id: str | None = None
    department_code: str | None = None
    department_name: str | None = None
    affiliation_status: str = "unresolved"
    nthu_affiliation_kind: str | None = None
    nthu_affiliation_label: str | None = None
    nthu_classification_source: str | None = None


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
    history_started_at: datetime | None = None
    points: list[OnlineStatisticsPoint] = Field(default_factory=list)


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
    points: list[SubmissionStatisticsPoint] = Field(default_factory=list)


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
    history_started_at: datetime | None = None
    points: list[UserOnlineDurationPoint] = Field(default_factory=list)


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
    course_name_en: str | None = None
    exam_name: str
    academic_year: int
    professor: str
    has_answers: bool = False
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_key: str | None = None
    is_admin_upload: bool = False
    submitted_at: datetime
    reviewed_at: datetime | None = None
    review_comment: str | None = None


class UserSubmissionStatsRead(BaseModel):
    user_id: int
    name: str
    contributor_experience: int = 0
    total_count: int = 0
    status_counts: UserSubmissionStatusCounts
    records_total: int = 0
    submission_records: list[UserSubmissionRecordRead] = Field(default_factory=list)


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
    name: str | None = None
    email: str | None = None
    password: str | None = None
    is_admin: bool | None = None

    _validate_password = field_validator("password")(validate_api_password)


class UserNicknameUpdate(BaseModel):
    nickname: str
    show_level_title: bool | None = None


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
    title: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1)
    title_en: str | None = Field(default=None, max_length=150)
    body_en: str | None = None
    severity: NotificationSeverity = NotificationSeverity.INFO
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class NotificationCreate(NotificationBase):
    title_en: str = Field(min_length=1, max_length=150)
    body_en: str = Field(min_length=1)


class NotificationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    body: str | None = Field(default=None, min_length=1)
    title_en: str | None = Field(default=None, max_length=150)
    body_en: str | None = None
    severity: NotificationSeverity | None = None
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class NotificationRead(NotificationBase):
    id: int
    created_at: datetime
    updated_at: datetime
    updated_by_username: str | None = None

    class Config:
        from_attributes = True


class AnnouncementWithRead(NotificationRead):
    is_read: bool = False
    read_at: datetime | None = None


def validate_about_us_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("About Us fields must not be blank")
    return value


def normalize_optional_bilingual_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class AboutUsEntryBase(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1)
    title_en: str | None = Field(default=None, max_length=150)
    body_en: str | None = None
    _normalize_text = field_validator("title", "body")(validate_about_us_text)
    _normalize_optional_text = field_validator("title_en", "body_en")(
        normalize_optional_bilingual_text
    )


class AboutUsEntryCreate(AboutUsEntryBase):
    title_en: str = Field(min_length=1, max_length=150)
    body_en: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_required_english_text(self):
        if self.title_en is None or self.body_en is None:
            raise ValueError("About Us English fields must not be blank")
        return self


class AboutUsEntryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    body: str | None = Field(default=None, min_length=1)
    title_en: str | None = Field(default=None, max_length=150)
    body_en: str | None = None
    _normalize_text = field_validator("title", "body")(validate_about_us_text)
    _normalize_optional_text = field_validator("title_en", "body_en")(
        normalize_optional_bilingual_text
    )


class AboutUsEntryRead(AboutUsEntryBase):
    id: int
    created_at: datetime
    updated_at: datetime
    updated_by_username: str | None = None

    class Config:
        from_attributes = True


class ArchiveWishCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    course_id: int | None = Field(default=None, ge=1)
    subject: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    academic_year: int | None = None
    archive_type: ArchiveType
    professor: str = Field(min_length=1, max_length=200)
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_key: str | None = None
    requested_category_name: str | None = None
    requested_category_name_en: str | None = None
    requested_category_label: str | None = None
    requested_category_label_en: str | None = None
    requested_category_icon: str | None = None

    @field_validator(
        "title",
        "subject",
        "category",
        "name",
        "professor",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Wish fields must not be blank")
        return value

    @field_validator(
        "requested_course_name",
        "requested_course_name_en",
        "requested_category_key",
        "requested_category_name",
        "requested_category_name_en",
        "requested_category_label",
        "requested_category_label_en",
        "requested_category_icon",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_bilingual_text(value)

    @model_validator(mode="after")
    def validate_parent_request(self):
        if self.course_id is None and not self.requested_course_name:
            raise ValueError("A course or requested course snapshot is required")
        if self.course_id is not None and self.requested_course_name:
            raise ValueError("A wish cannot select and request a course together")
        if self.requested_course_name and not self.requested_course_name_en:
            raise ValueError("Requested course Chinese and English names are required")
        category_snapshot = (
            self.requested_category_key,
            self.requested_category_name,
            self.requested_category_name_en,
            self.requested_category_label,
            self.requested_category_label_en,
        )
        if any(category_snapshot) and not all(category_snapshot):
            raise ValueError("Requested category bilingual snapshot is incomplete")
        if self.requested_category_key and not self.requested_course_name:
            raise ValueError("A new category wish must also request a new course")
        return self


class ArchiveWishRead(BaseModel):
    id: int
    title: str
    course_id: int | None = None
    subject: str
    category: str
    name: str
    academic_year: int | None = None
    archive_type: ArchiveType
    professor: str
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_key: str | None = None
    requested_category_name: str | None = None
    requested_category_name_en: str | None = None
    requested_category_label: str | None = None
    requested_category_label_en: str | None = None
    requested_category_icon: str | None = None
    creator_id: int
    creator_name: str
    heart_count: int = 0
    hearted_by_me: bool = False
    fulfilled: bool = False
    created_at: datetime


class ArchiveWishListRead(BaseModel):
    items: list[ArchiveWishRead] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class ArchiveWishHeartRead(BaseModel):
    hearted: bool
    heart_count: int


class ArchiveWishReportCreate(BaseModel):
    report_reason: CommentReportReason
    custom_message: str | None = Field(default=None, max_length=200)


class ArchiveWishReportAdminUpdate(BaseModel):
    status: CommentReportStatus
    admin_response: str | None = Field(default=None, max_length=1000)


class ArchiveWishReportRead(BaseModel):
    id: int
    wish_id: int | None = None
    reporter_user_id: int | None = None
    reporter_name: str
    wisher_name: str | None = None
    wish_title: str
    target_summary: str
    reason: str
    custom_message: str | None = None
    status: str
    admin_response: str | None = None
    reviewed_by: int | None = None
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None
    source_exists: bool
    created_at: datetime
    updated_at: datetime


class ArchiveWishReportListRead(BaseModel):
    items: list[ArchiveWishReportRead] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class PersonalNotificationRead(BaseModel):
    id: int
    notification_type: str
    title: str
    message: str
    source_type: str | None = None
    source_id: int | None = None
    source_message_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_available: bool = True
    read_at: datetime | None = None
    created_at: datetime


class CommentReportCreate(BaseModel):
    report_reason: CommentReportReason
    custom_message: str | None = Field(default=None, max_length=200)


class CommentReportAdminUpdate(BaseModel):
    status: CommentReportStatus
    admin_response: str | None = Field(default=None, max_length=1000)
    delete_comment: bool = False


class CommentReportRead(BaseModel):
    id: int
    reporter_user_id: int
    reporter_name: str
    comment_id: int | None
    comment_author_id: int | None
    comment_author_name: str
    archive_id: int | None
    course_id: int | None
    thread_id: int | None
    reply_to_message_id: int | None
    reason: str
    custom_message: str | None
    comment_content_snapshot: str
    comment_created_at_snapshot: datetime
    archive_name: str
    course_name: str
    course_name_en: str | None = None
    status: str
    admin_response: str | None
    reviewed_by: int | None
    reviewer_name: str | None
    reviewed_at: datetime | None
    comment_deleted: bool
    source_exists: bool
    created_at: datetime
    updated_at: datetime


class CommentReportListRead(BaseModel):
    items: list[CommentReportRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class ArchiveReportCreate(BaseModel):
    report_reason: ArchiveReportReason
    supplementary_detail: str | None = Field(default=None, max_length=1000)


class ArchiveReportAdminUpdate(BaseModel):
    status: CommentReportStatus
    admin_response: str | None = Field(default=None, max_length=1000)
    take_down_archive: bool = False


class ArchiveReportRead(BaseModel):
    id: int
    reporter_user_id: int | None
    reporter_name: str
    archive_id: int | None
    archive_id_snapshot: int
    course_id: int | None
    archive_submission_id: int | None
    reason: str
    supplementary_detail: str | None
    archive_name: str
    course_name: str
    course_name_en: str | None = None
    academic_year: int
    archive_type: str
    professor: str
    status: str
    admin_response: str | None
    reviewed_by: int | None
    reviewer_name: str | None
    reviewed_at: datetime | None
    archive_taken_down: bool
    source_exists: bool
    source_state: str
    can_take_down: bool
    created_at: datetime
    updated_at: datetime


class ArchiveReportListRead(BaseModel):
    items: list[ArchiveReportRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class SystemIssueReportCreate(BaseModel):
    report_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    contact: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemIssueReportRead(BaseModel):
    id: int
    reporter_user_id: int | None
    reporter_name: str
    report_type: str
    title: str
    description: str
    contact: str | None
    status: str
    github_issue_number: int | None
    github_issue_url: str | None
    is_read: bool = False
    read_at: datetime | None
    read_by_username: str | None
    created_at: datetime
    updated_at: datetime


class SystemIssueReportReadStateUpdate(BaseModel):
    is_read: bool


class SystemIssueReportListRead(BaseModel):
    items: list[SystemIssueReportRead] = Field(default_factory=list)
    total: int = 0


class NotificationUnreadCounts(BaseModel):
    announcements: int = 0
    personal_notifications: int = 0
    total: int = 0


class NotificationCenterRead(BaseModel):
    announcements: list[AnnouncementWithRead] = Field(default_factory=list)
    personal_notifications: list[PersonalNotificationRead] = Field(default_factory=list)
    counts: NotificationUnreadCounts = Field(default_factory=NotificationUnreadCounts)


class NotificationUnreadSummary(NotificationCenterRead):
    pass


class CourseInfo(BaseModel):
    id: int
    name: str
    name_en: str | None = None
    order_index: int = 0

    class Config:
        from_attributes = True


class CoursesByCategory(BaseModel):
    courses: dict[str, list[CourseInfo]] = {}

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
    uploader_id: int | None = None
    download_count: int = 0
    source_submission_ids: list[int] = []

    class Config:
        from_attributes = True


class PublicArchiveRead(BaseModel):
    """Archive metadata that is safe to expose without authentication."""

    id: int
    name: str
    academic_year: int
    archive_type: ArchiveType
    professor: str
    has_answers: bool

    class Config:
        from_attributes = True


class ArchiveDiscussionMessageRead(BaseModel):
    id: int
    archive_id: int
    user_id: int
    user_name: str
    author_show_level_title: bool = False
    author_experience: int | None = None
    content: str
    is_pinned: bool = False
    is_deleted: bool = False
    parent_id: int | None = None
    reply_to_message_id: int | None = None
    reply_to_user_name: str | None = None
    like_count: int = 0
    liked_by_current_user: bool = False
    replies: list["ArchiveDiscussionMessageRead"] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class CourseCreate(BaseModel):
    name: str
    name_en: str | None = None
    category: str
    order_index: int | None = None


class CourseUpdate(BaseModel):
    name: str | None = None
    name_en: str | None = None
    category: str | None = None
    order_index: int | None = None


class CourseReorder(BaseModel):
    category: str
    course_ids: list[int]


class CourseRead(BaseModel):
    id: int
    name: str
    name_en: str | None = None
    category: str
    order_index: int = 0

    class Config:
        from_attributes = True


class ArchiveUpdateCourse(BaseModel):
    course_id: int | None = None
    course_name: str | None = None
    course_category: str | None = None


class CourseSubmissionCreate(BaseModel):
    name: str
    category: str


class CourseCategoryCreate(BaseModel):
    key: str
    name: str
    name_en: str | None = None
    label: str = ""
    label_en: str | None = None
    icon: str = "pi pi-fw pi-book"
    badge_color: str | None = None
    order_index: int | None = None


class CourseCategoryUpdate(BaseModel):
    key: str | None = None
    name: str | None = None
    name_en: str | None = None
    label: str | None = None
    label_en: str | None = None
    icon: str | None = None
    badge_color: str | None = None
    order_index: int | None = None
    is_active: bool | None = None


class CourseCategoryReorder(BaseModel):
    category_ids: list[int]


class CourseCategoryRead(BaseModel):
    id: int
    key: str
    name: str
    name_en: str | None = None
    label: str
    label_en: str | None = None
    icon: str
    badge_color: str = "blue"
    order_index: int
    is_active: bool

    class Config:
        from_attributes = True


class SubmissionDecision(BaseModel):
    note: str | None = None
    expected_status: SubmissionStatus | None = None


class CourseSubmissionRead(BaseModel):
    id: int
    name: str
    category: str
    status: SubmissionStatus
    previous_status: SubmissionStatus | None = None
    requester_id: int
    reviewer_id: int | None = None
    review_note: str | None = None
    created_course_id: int | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    deleted_at: datetime | None = None
    deleted_by_id: int | None = None
    restored_at: datetime | None = None
    restored_by_id: int | None = None

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
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_key: str | None = None
    requested_category_name: str | None = None
    requested_category_name_en: str | None = None
    requested_category_label: str | None = None
    requested_category_label_en: str | None = None
    requested_category_icon: str | None = None
    status: SubmissionStatus
    requester_id: int
    requester_name: str | None = None
    requester_email: str | None = None
    is_admin_upload: bool = False
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    reviewer_email: str | None = None
    review_note: str | None = None
    created_archive_id: int | None = None
    lifecycle_reason: str | None = None
    linked_archive_deleted: bool = False
    linked_course_deleted: bool = False
    created_at: datetime
    reviewed_at: datetime | None = None

    class Config:
        from_attributes = True


class ArchiveSubmissionAdminRead(ArchiveSubmissionRead):
    available_actions: list[ArchiveSubmissionAdminAction]


class ArchiveSubmissionActionRead(ArchiveSubmissionAdminRead):
    changed: bool


class ArchiveSubmissionComparisonRead(ArchiveSubmissionRead):
    can_takedown: bool = False


class CourseSubmissionUpdate(BaseModel):
    name: str | None = None
    category: str | None = None


class ArchiveSubmissionUpdate(BaseModel):
    subject: str | None = None
    category: str | None = None
    name: str | None = None
    academic_year: int | None = None
    archive_type: ArchiveType | None = None
    professor: str | None = None
    has_answers: bool | None = None
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_key: str | None = None
    requested_category_name: str | None = None
    requested_category_name_en: str | None = None
    requested_category_label: str | None = None
    requested_category_label_en: str | None = None
    requested_category_icon: str | None = None


class TrashItem(BaseModel):
    item_type: TrashEntityType
    id: int
    display_name: str
    display_name_en: str | None = None
    academic_year: int | None = None
    academic_term: str | None = None
    deleted_at: datetime | None = None
    deleted_by_id: int | None = None
    deleted_by_name: str | None = None
    user_email: str | None = None
    status: str | None = None
    parent_type: str | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    parent_name_en: str | None = None
    created_archive_id: int | None = None
    source_submission_id: int | None = None
    course_id: int | None = None
    course_name: str | None = None
    course_name_en: str | None = None
    requested_course_name: str | None = None
    requested_course_name_en: str | None = None
    requested_category_name: str | None = None
    requested_category_name_en: str | None = None
    requested_category_label: str | None = None
    requested_category_label_en: str | None = None
    reason: str | None = None
    created_at: datetime | None = None
    reporter_name: str | None = None
    report_type: str | None = None
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    comment_author_name: str | None = None
    comment_snapshot: str | None = None
    archive_name: str | None = None
    canRestore: bool | None = None
    canPermanentDelete: bool | None = None
    dependencies: list[str] = []
