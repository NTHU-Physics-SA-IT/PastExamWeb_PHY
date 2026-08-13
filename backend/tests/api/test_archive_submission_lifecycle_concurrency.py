import asyncio
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services.archive_submission_lifecycle import (
    acquire_stable_submission_lifecycle_locks,
    soft_delete_archive_submission_group,
)
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    Course,
    CourseCategoryConfig,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_lifecycle_locks
from app.services.archive_lifecycle_locks import LifecycleResourceClass
from app.utils.auth import get_current_user

_current_actor: ContextVar[UserRoles] = ContextVar("lifecycle_concurrency_actor")


async def _context_actor() -> UserRoles:
    return _current_actor.get()


async def _as_actor(actor: UserRoles, operation):
    token = _current_actor.set(actor)
    try:
        return await operation()
    finally:
        _current_actor.reset(token)


async def _create_context(session_maker, *, requester_id: int):
    marker = uuid.uuid4().hex
    category = CourseCategoryConfig(
        key=f"s3c-{marker[:12]}",
        name=f"S3C category {marker}",
        label=f"S3C category {marker}",
    )
    course = Course(name=f"S3C course {marker}", category=category.key)
    async with session_maker() as session:
        session.add(category)
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"S3C archive {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="S3C Professor",
            object_name=f"archive/s3c-{marker}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=category.key,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requested_course_name=course.name,
            requested_category_key=category.key,
            requester_id=requester_id,
            status=SubmissionStatus.PENDING,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        for row in (category, course, archive, submission):
            await session.refresh(row)
    return category, course, archive, submission


async def _cleanup_context(
    session_maker,
    *,
    category_id: int,
    course_id: int,
    archive_id: int,
    submission_id: int,
) -> None:
    async with session_maker() as session:
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id == submission_id,
            )
        )
        await session.execute(
            delete(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.submission_id == submission_id
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(ArchiveSubmission.id == submission_id)
        )
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.execute(
            delete(CourseCategoryConfig).where(
                CourseCategoryConfig.id == category_id
            )
        )
        await session.commit()


def _resource_trace(plan):
    return [(resource.resource_class, resource.row_id) for resource in plan.resources]


async def _run_serialized_race(
    *,
    monkeypatch,
    first_operation,
    second_operation,
):
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    call_count = 0
    traces = []
    sqlstates: list[str] = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        nonlocal call_count
        call_count += 1
        call_number = call_count
        traces.append(_resource_trace(plan))
        if call_number == 2:
            second_attempted.set()
        try:
            locked = await original_acquire(db, plan)
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None) or getattr(
                getattr(exc, "orig", None),
                "sqlstate",
                None,
            )
            if sqlstate:
                sqlstates.append(str(sqlstate))
            raise
        if call_number == 1:
            first_locked.set()
            await asyncio.wait_for(release_first.wait(), timeout=10)
        return locked

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    first_task = asyncio.create_task(first_operation())
    await asyncio.wait_for(first_locked.wait(), timeout=10)
    second_task = asyncio.create_task(second_operation())
    await asyncio.wait_for(second_attempted.wait(), timeout=10)
    assert not second_task.done()
    release_first.set()
    first_result = await asyncio.wait_for(first_task, timeout=10)
    second_result = await asyncio.wait_for(second_task, timeout=10)
    assert "40P01" not in sqlstates
    return first_result, second_result, traces


def _assert_canonical_plan(
    traces,
    *,
    course_id: int,
    archive_id: int,
    submission_id: int,
):
    expected = [
        (LifecycleResourceClass.COURSE, course_id),
        (LifecycleResourceClass.ARCHIVE, archive_id),
        (LifecycleResourceClass.ARCHIVE_SUBMISSION, submission_id),
    ]
    assert len(traces) == 2
    for trace in traces:
        assert trace == sorted(trace)
        assert trace[-3:] == expected


def _review_status(action: str) -> SubmissionStatus:
    return {
        "approve": SubmissionStatus.APPROVED,
        "reject": SubmissionStatus.REJECTED,
        "takedown": SubmissionStatus.TAKEDOWN,
    }[action]


async def _counts(session, submission_id: int) -> tuple[int, int]:
    notifications = int(
        await session.scalar(
            select(func.count(PersonalNotification.id)).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id == submission_id,
            )
        )
        or 0
    )
    events = int(
        await session.scalar(
            select(func.count(ArchiveSubmissionEvent.id)).where(
                ArchiveSubmissionEvent.submission_id == submission_id
            )
        )
        or 0
    )
    return notifications, events


@pytest.mark.parametrize("review_action", ["reject", "takedown"])
@pytest.mark.parametrize("first_operation", ["review", "owner"])
@pytest.mark.asyncio
async def test_direct_review_and_owner_delete_serialize(
    client,
    session_maker,
    make_user,
    monkeypatch,
    review_action,
    first_operation,
):
    owner = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, submission = await _create_context(
        session_maker,
        requester_id=owner.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, submission.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()
    app.dependency_overrides[get_current_user] = _context_actor
    owner_actor = UserRoles(user_id=owner.id, is_admin=False)
    admin_actor = UserRoles(user_id=admin.id, is_admin=True)

    async def review():
        return await _as_actor(
            admin_actor,
            lambda: client.post(
                f"/archives/admin/submissions/{submission.id}/{review_action}",
                json={"expected_status": "approved", "note": "S3C review race"},
            ),
        )

    async def owner_delete():
        return await _as_actor(
            owner_actor,
            lambda: client.delete(f"/archives/submissions/{submission.id}"),
        )

    try:
        first, second, traces = await _run_serialized_race(
            monkeypatch=monkeypatch,
            first_operation=review if first_operation == "review" else owner_delete,
            second_operation=owner_delete if first_operation == "review" else review,
        )
        assert first.status_code == 200
        assert first.json()["changed"] is True
        if first_operation == "review":
            assert second.status_code == 400
        else:
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == "archive_submission_stale_state"
            assert second.json()["detail"]["actual_status"] == "deleted"
            assert second.json()["detail"]["reload_required"] is True
        _assert_canonical_plan(
            traces,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored_archive = await session.get(Archive, archive.id)
            notifications, events = await _counts(session, submission.id)
            if first_operation == "review":
                assert stored.status == _review_status(review_action)
                assert stored.previous_status is None
                assert stored.owner_self_delete_consumed is False
                assert stored_archive.deleted_at is None
                assert notifications == 1
            else:
                assert stored.status == SubmissionStatus.DELETED
                assert stored.previous_status == SubmissionStatus.APPROVED
                assert stored.owner_self_delete_consumed is True
                assert stored_archive.deleted_at is not None
                assert notifications == 0
            assert stored.created_archive_id == archive.id
            assert events == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize("review_action", ["approve", "reject", "takedown"])
@pytest.mark.parametrize("first_operation", ["review", "admin_delete"])
@pytest.mark.asyncio
async def test_direct_review_and_admin_delete_serialize(
    client,
    session_maker,
    make_user,
    monkeypatch,
    review_action,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _context_actor
    admin_actor = UserRoles(user_id=admin.id, is_admin=True)

    async def review():
        return await _as_actor(
            admin_actor,
            lambda: client.post(
                f"/archives/admin/submissions/{submission.id}/{review_action}",
                json={"expected_status": "pending", "note": "S3C admin race"},
            ),
        )

    async def admin_delete():
        return await _as_actor(
            admin_actor,
            lambda: client.delete(f"/archives/admin/submissions/{submission.id}"),
        )

    try:
        first, second, traces = await _run_serialized_race(
            monkeypatch=monkeypatch,
            first_operation=review if first_operation == "review" else admin_delete,
            second_operation=admin_delete if first_operation == "review" else review,
        )
        assert first.status_code == 200
        assert first.json()["changed"] is True
        if first_operation == "admin_delete":
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == "archive_submission_stale_state"
            assert second.json()["detail"]["actual_status"] == "deleted"
            assert second.json()["detail"]["reload_required"] is True
        else:
            assert second.status_code == 200
            assert second.json()["changed"] is True
        _assert_canonical_plan(
            traces,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )

        retry = await admin_delete()
        assert retry.status_code == 200
        assert retry.json()["changed"] is False
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored_archive = await session.get(Archive, archive.id)
            notifications, events = await _counts(session, submission.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == (
                _review_status(review_action)
                if first_operation == "review"
                else SubmissionStatus.PENDING
            )
            assert stored.owner_self_delete_consumed is False
            assert stored.created_archive_id == archive.id
            assert stored_archive.deleted_at is not None
            assert notifications == (1 if first_operation == "review" else 0)
            assert events == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize("first_operation", ["review", "restore"])
@pytest.mark.asyncio
async def test_direct_review_and_exact_restore_serialize(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
    )
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, submission.id)
        stored_archive = await session.get(Archive, archive.id)
        stored.status = SubmissionStatus.DELETED
        stored.previous_status = SubmissionStatus.APPROVED
        stored.owner_self_delete_consumed = True
        stored.deleted_at = deleted_at
        stored.deleted_by_id = requester.id
        stored.delete_reason = "owner deleted"
        stored_archive.deleted_at = deleted_at
        stored_archive.deleted_by_id = requester.id
        stored_archive.deleted_reason = "owner deleted"
        await session.commit()
    app.dependency_overrides[get_current_user] = _context_actor
    admin_actor = UserRoles(user_id=admin.id, is_admin=True)

    async def review():
        return await _as_actor(
            admin_actor,
            lambda: client.post(
                f"/archives/admin/submissions/{submission.id}/takedown",
                json={"expected_status": "approved", "note": "S3C restore race"},
            ),
        )

    async def restore():
        return await _as_actor(
            admin_actor,
            lambda: client.post(
                "/trash/restore",
                json={
                    "item_type": "archive_submission",
                    "item_id": submission.id,
                },
            ),
        )

    try:
        first, second, traces = await _run_serialized_race(
            monkeypatch=monkeypatch,
            first_operation=review if first_operation == "review" else restore,
            second_operation=restore if first_operation == "review" else review,
        )
        if first_operation == "review":
            assert first.status_code == 409
            assert first.json()["detail"]["actual_status"] == "deleted"
            assert first.json()["detail"]["reload_required"] is True
            assert second.status_code == 200
        else:
            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json()["changed"] is True
        _assert_canonical_plan(
            traces,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored_archive = await session.get(Archive, archive.id)
            notifications, events = await _counts(session, submission.id)
            assert stored.status == (
                SubmissionStatus.APPROVED
                if first_operation == "review"
                else SubmissionStatus.TAKEDOWN
            )
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is True
            assert stored.created_archive_id == archive.id
            assert stored_archive.deleted_at is None
            assert notifications == (0 if first_operation == "review" else 1)
            assert events == 0

        retry = await restore()
        assert retry.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )


@pytest.mark.parametrize("first_operation", ["system", "owner"])
@pytest.mark.asyncio
async def test_system_group_delete_and_owner_delete_serialize(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    owner = await make_user()
    category, course, archive, submission = await _create_context(
        session_maker,
        requester_id=owner.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, submission.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()
    app.dependency_overrides[get_current_user] = _context_actor
    owner_actor = UserRoles(user_id=owner.id, is_admin=False)

    async def system_delete():
        async with session_maker() as session:
            locked = await acquire_stable_submission_lifecycle_locks(
                session,
                submission_id=submission.id,
                operation="submission_delete",
            )
            assert locked is not None
            result = await soft_delete_archive_submission_group(
                session,
                archive=locked.archive(archive.id),
                submission=locked.submission(submission.id),
                user_id=None,
                reason="system cascade",
            )
            await session.commit()
            return result

    async def owner_delete():
        return await _as_actor(
            owner_actor,
            lambda: client.delete(f"/archives/submissions/{submission.id}"),
        )

    try:
        first, second, traces = await _run_serialized_race(
            monkeypatch=monkeypatch,
            first_operation=system_delete if first_operation == "system" else owner_delete,
            second_operation=owner_delete if first_operation == "system" else system_delete,
        )
        if first_operation == "system":
            assert first["archives"] == 1
            assert first["submissions"] == 1
            assert second.status_code == 200
            assert second.json()["changed"] is False
        else:
            assert first.status_code == 200
            assert first.json()["changed"] is True
            assert second["archives"] == 0
            assert second["submissions"] == 0
        _assert_canonical_plan(
            traces,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission.id)
            stored_archive = await session.get(Archive, archive.id)
            notifications, events = await _counts(session, submission.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.APPROVED
            assert stored.owner_self_delete_consumed is (first_operation == "owner")
            assert stored.created_archive_id == archive.id
            assert stored_archive.deleted_at is not None
            assert stored.delete_reason == (
                "system cascade" if first_operation == "system" else "user deleted"
            )
            assert notifications == 0
            assert events == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_id=submission.id,
        )
