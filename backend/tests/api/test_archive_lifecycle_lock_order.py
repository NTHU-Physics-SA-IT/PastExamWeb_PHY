import asyncio
from datetime import datetime, timezone
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import archives as archives_service
from app.api.services.archive_submission_lifecycle import (
    ARCHIVE_LIFECYCLE_CONFLICT_CODE,
    ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE,
    COURSE_LIFECYCLE_CONFLICT_CODE,
    COURSE_LIFECYCLE_CONFLICT_MESSAGE,
    LIFECYCLE_ARCHIVE_TRASHED,
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
from app.services import course_lifecycle_locks
from app.services.archive_lifecycle_locks import LifecycleResourceClass
from app.services.course_lifecycle_locks import (
    CourseLifecycleOperation,
    CourseLifecycleRevalidationResult,
)
from app.services.archive_submission_links import (
    validate_archive_source_membership,
)
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


def _override_admin(user_id: int):
    return _override_user(user_id, is_admin=True)


async def _create_archive_context(
    session_maker,
    *,
    requester_id: int,
) -> tuple[
    CourseCategoryConfig,
    Course,
    Archive,
    ArchiveSubmission,
]:
    marker = uuid.uuid4().hex
    category = CourseCategoryConfig(
        key=f"lock-{marker[:12]}",
        name=f"Lock category {marker}",
        label=f"Lock category {marker}",
    )
    course = Course(
        name=f"Lock course {marker}",
        category=category.key,
    )
    async with session_maker() as session:
        session.add(category)
        session.add(course)
        await session.flush()
        archive = Archive(
            name=f"Lock archive {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Lock Professor",
            object_name=f"archive/lock-{marker}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        target = ArchiveSubmission(
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
        session.add(target)
        await session.commit()
        for row in (category, course, archive, target):
            await session.refresh(row)
    return category, course, archive, target


async def _create_second_pair(
    session_maker,
    *,
    course: Course,
    requester_id: int,
) -> tuple[Archive, ArchiveSubmission]:
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        archive = Archive(
            name=f"Second lock archive {marker}",
            academic_year=2026,
            archive_type=ArchiveType.MIDTERM,
            professor="Second Lock Professor",
            object_name=f"archive/second-lock-{marker}.pdf",
            uploader_id=requester_id,
            course_id=course.id,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=course.category,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requester_id=requester_id,
            status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(archive)
        await session.refresh(submission)
    return archive, submission


async def _cleanup_archive_context(
    session_maker,
    *,
    category_id: int,
    course_id: int,
    archive_ids: list[int],
    submission_ids: list[int],
) -> None:
    async with session_maker() as session:
        if submission_ids:
            await session.execute(
                delete(PersonalNotification).where(
                    PersonalNotification.source_type == "archive_submission",
                    PersonalNotification.source_id.in_(submission_ids),
                )
            )
            await session.execute(
                delete(ArchiveSubmissionEvent).where(
                    ArchiveSubmissionEvent.submission_id.in_(submission_ids)
                )
            )
            await session.execute(
                delete(ArchiveSubmission).where(
                    ArchiveSubmission.id.in_(submission_ids)
                )
            )
        if archive_ids:
            await session.execute(delete(Archive).where(Archive.id.in_(archive_ids)))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.execute(
            delete(CourseCategoryConfig).where(CourseCategoryConfig.id == category_id)
        )
        await session.commit()


async def _replace_archive_source(
    session_maker,
    *,
    archive: Archive,
    course: Course,
    requester_id: int,
    current_source_id: int,
    status: SubmissionStatus,
    lifecycle_reason: str | None,
) -> int:
    """Change legal membership without ever violating the database constraint."""
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        current = await session.get(ArchiveSubmission, current_source_id)
        assert current is not None
        current.created_archive_id = None
        await session.flush()
        replacement = ArchiveSubmission(
            subject=course.name,
            category=course.category,
            name=f"Replacement source {marker}",
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=f"archive/replacement-source-{marker}.pdf",
            requester_id=requester_id,
            status=status,
            lifecycle_reason=lifecycle_reason,
            created_archive_id=archive.id,
        )
        session.add(replacement)
        await session.commit()
        await session.refresh(replacement)
        return replacement.id


def _resource_trace(plan):
    return [(resource.resource_class, resource.row_id) for resource in plan.resources]


async def _run_two_request_lock_race(
    *,
    monkeypatch,
    first_request,
    second_request,
):
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    call_count = 0
    sqlstates: list[str] = []
    traces = []
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
    first_task = asyncio.create_task(first_request())
    await asyncio.wait_for(first_locked.wait(), timeout=10)
    second_task = asyncio.create_task(second_request())
    await asyncio.wait_for(second_attempted.wait(), timeout=10)
    assert not second_task.done()
    release_first.set()
    first_result = await asyncio.wait_for(first_task, timeout=10)
    second_result = await asyncio.wait_for(second_task, timeout=10)
    return first_result, second_result, traces, sqlstates


@pytest.mark.asyncio
async def test_course_trash_and_restore_use_canonical_parent_first_plans(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    traces = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(_resource_trace(plan))
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        trash_response = await client.delete(f"/courses/admin/courses/{course.id}")
        assert trash_response.status_code == 200
        restore_response = await client.post(
            "/trash/restore",
            json={"item_type": "course", "item_id": course.id},
        )
        assert restore_response.status_code == 200

        assert traces == [
            [
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
            ],
            [
                (LifecycleResourceClass.COURSE_CATEGORY, category.id),
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
            ],
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize(
    "operation",
    [CourseLifecycleOperation.TRASH, CourseLifecycleOperation.RESTORE],
)
@pytest.mark.asyncio
async def test_course_lifecycle_rebuild_exhaustion_returns_narrow_contract(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    calls = 0
    try:
        if operation is CourseLifecycleOperation.RESTORE:
            trash_response = await client.delete(f"/courses/admin/courses/{course.id}")
            assert trash_response.status_code == 200

        async def always_changed(db, locked):
            nonlocal calls
            calls += 1
            return CourseLifecycleRevalidationResult(
                valid=False,
                fingerprint=locked.plan.fingerprint,
                reasons=("synthetic_membership_change",),
            )

        monkeypatch.setattr(
            course_lifecycle_locks,
            "revalidate_course_lifecycle_plan",
            always_changed,
        )
        response = (
            await client.delete(f"/courses/admin/courses/{course.id}")
            if operation is CourseLifecycleOperation.TRASH
            else await client.post(
                "/trash/restore",
                json={"item_type": "course", "item_id": course.id},
            )
        )
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": COURSE_LIFECYCLE_CONFLICT_CODE,
            "message": COURSE_LIFECYCLE_CONFLICT_MESSAGE,
        }
        assert calls == 2

        async with session_maker() as session:
            stored_course = await session.get(Course, course.id)
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                target.id,
            )
            expected_deleted = operation is CourseLifecycleOperation.RESTORE
            assert (stored_course.deleted_at is not None) is expected_deleted
            assert (stored_archive.deleted_at is not None) is expected_deleted
            assert stored_submission.status == (
                SubmissionStatus.TAKEDOWN
                if expected_deleted
                else SubmissionStatus.PENDING
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_course_lifecycle_first_membership_change_rebuilds_once(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    calls = 0
    original_revalidate = course_lifecycle_locks.revalidate_course_lifecycle_plan

    async def changed_once(db, locked):
        nonlocal calls
        calls += 1
        if calls == 1:
            return CourseLifecycleRevalidationResult(
                valid=False,
                fingerprint=locked.plan.fingerprint,
                reasons=("synthetic_membership_change",),
            )
        return await original_revalidate(db, locked)

    monkeypatch.setattr(
        course_lifecycle_locks,
        "revalidate_course_lifecycle_plan",
        changed_once,
    )
    try:
        response = await client.delete(f"/courses/admin/courses/{course.id}")
        assert response.status_code == 200
        assert calls == 2
        async with session_maker() as session:
            assert (await session.get(Course, course.id)).deleted_at is not None
            assert (await session.get(Archive, archive.id)).deleted_at is not None
            assert (
                await session.get(ArchiveSubmission, target.id)
            ).status == SubmissionStatus.TAKEDOWN
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["course", "archive"])
@pytest.mark.asyncio
async def test_course_trash_and_archive_trash_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def trash_course():
        return await client.delete(f"/courses/admin/courses/{course.id}")

    async def trash_archive():
        return await client.delete(f"/courses/{course.id}/archives/{archive.id}")

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                trash_course if first_operation == "course" else trash_archive
            ),
            second_request=(
                trash_archive if first_operation == "course" else trash_course
            ),
        )
        assert first.status_code == 200
        assert second.status_code == (404 if first_operation == "course" else 200)
        assert "40P01" not in sqlstates
        for trace in traces:
            assert trace == sorted(trace)
            assert trace.index(
                (LifecycleResourceClass.COURSE, course.id)
            ) < trace.index((LifecycleResourceClass.ARCHIVE, archive.id))
            assert trace.index(
                (LifecycleResourceClass.ARCHIVE, archive.id)
            ) < trace.index((LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id))
        async with session_maker() as session:
            assert (await session.get(Course, course.id)).deleted_at is not None
            assert (await session.get(Archive, archive.id)).deleted_at is not None
            assert (
                await session.get(ArchiveSubmission, target.id)
            ).status == SubmissionStatus.TAKEDOWN
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["course", "review"])
@pytest.mark.asyncio
async def test_course_trash_and_submission_review_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def trash_course():
        return await client.delete(f"/courses/admin/courses/{course.id}")

    async def approve():
        return await client.post(
            f"/archives/admin/submissions/{target.id}/approve",
            json={"expected_status": "pending", "note": "course race"},
        )

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=trash_course if first_operation == "course" else approve,
            second_request=approve if first_operation == "course" else trash_course,
        )
        assert first.status_code == 200
        assert second.status_code == (409 if first_operation == "course" else 200)
        if first_operation == "course":
            assert second.json()["detail"]["code"] == ("archive_submission_stale_state")
        assert "40P01" not in sqlstates
        for trace in traces:
            assert trace == sorted(trace)
            assert (LifecycleResourceClass.COURSE, course.id) in trace
            assert (LifecycleResourceClass.ARCHIVE, archive.id) in trace
            assert (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                target.id,
            ) in trace
        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.TAKEDOWN
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == target.id,
                    )
                )
                or 0
            )
            assert notification_count == (0 if first_operation == "course" else 1)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["course", "submission"])
@pytest.mark.asyncio
async def test_course_restore_and_submission_restore_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        delete_submission = await client.delete(
            f"/archives/admin/submissions/{target.id}"
        )
        assert delete_submission.status_code == 200
        delete_course = await client.delete(f"/courses/admin/courses/{course.id}")
        assert delete_course.status_code == 200

        async def restore_course():
            return await client.post(
                "/trash/restore",
                json={"item_type": "course", "item_id": course.id},
            )

        async def restore_submission():
            return await client.post(
                "/trash/restore",
                json={
                    "item_type": "archive_submission",
                    "item_id": target.id,
                },
            )

        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                restore_course if first_operation == "course" else restore_submission
            ),
            second_request=(
                restore_submission if first_operation == "course" else restore_course
            ),
        )
        assert first.status_code == (200 if first_operation == "course" else 409)
        assert second.status_code == 200
        assert "40P01" not in sqlstates
        for trace in traces:
            assert trace == sorted(trace)

        async with session_maker() as session:
            stored_course = await session.get(Course, course.id)
            stored_submission = await session.get(
                ArchiveSubmission,
                target.id,
            )
            assert stored_course.deleted_at is None
            if first_operation == "course":
                assert stored_submission.deleted_at is None
                assert stored_submission.status == SubmissionStatus.APPROVED
            else:
                assert stored_submission.deleted_at is not None
                assert stored_submission.status == SubmissionStatus.DELETED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_course_trash_and_restore_have_legal_concurrent_winner_orders(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks
    sqlstates: list[str] = []
    call_count = 0

    async def observed_acquire(db, plan):
        nonlocal call_count
        call_count += 1
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
        if call_count == 1:
            first_locked.set()
            await asyncio.wait_for(release_first.wait(), timeout=10)
        return locked

    try:
        if first_operation == "restore":
            initial_trash = await client.delete(f"/courses/admin/courses/{course.id}")
            assert initial_trash.status_code == 200
            call_count = 0
        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_lifecycle_locks",
            observed_acquire,
        )

        async def trash_course():
            return await client.delete(f"/courses/admin/courses/{course.id}")

        async def restore_course():
            return await client.post(
                "/trash/restore",
                json={"item_type": "course", "item_id": course.id},
            )

        winner_task = asyncio.create_task(
            trash_course() if first_operation == "trash" else restore_course()
        )
        await asyncio.wait_for(first_locked.wait(), timeout=10)
        loser = await asyncio.wait_for(
            restore_course() if first_operation == "trash" else trash_course(),
            timeout=10,
        )
        assert loser.status_code == 404
        release_first.set()
        winner = await asyncio.wait_for(winner_task, timeout=10)
        assert winner.status_code == 200
        assert "40P01" not in sqlstates

        async with session_maker() as session:
            stored_course = await session.get(Course, course.id)
            assert (stored_course.deleted_at is not None) is (
                first_operation == "trash"
            )
    finally:
        release_first.set()
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_course_trash_rebuilds_after_real_membership_change(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks
    inserted_submission_ids: list[int] = []
    calls = 0

    async def insert_matching_submission() -> None:
        marker = uuid.uuid4().hex
        async with session_maker() as session:
            submission = ArchiveSubmission(
                subject=course.name,
                category=course.category,
                name=f"Membership {marker}",
                academic_year=2026,
                archive_type=ArchiveType.FINAL,
                professor="Membership Professor",
                object_name=f"submissions/membership-{marker}.pdf",
                requester_id=requester.id,
                status=SubmissionStatus.PENDING,
            )
            session.add(submission)
            await session.commit()
            await session.refresh(submission)
            inserted_submission_ids.append(submission.id)

    async def change_before_first_lock(db, plan):
        nonlocal calls
        calls += 1
        if calls == 1:
            await insert_matching_submission()
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        change_before_first_lock,
    )
    try:
        response = await client.delete(f"/courses/admin/courses/{course.id}")
        assert response.status_code == 200
        assert calls == 2
        assert len(inserted_submission_ids) == 1
        async with session_maker() as session:
            inserted = await session.get(
                ArchiveSubmission,
                inserted_submission_ids[0],
            )
            assert inserted.status == SubmissionStatus.TAKEDOWN
            assert inserted.lifecycle_reason.startswith("course_trashed|")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if inserted_submission_ids:
            async with session_maker() as session:
                await session.execute(
                    delete(ArchiveSubmission).where(
                        ArchiveSubmission.id.in_(inserted_submission_ids)
                    )
                )
                await session.commit()
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_course_trash_second_real_membership_change_returns_conflict(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks
    inserted_submission_ids: list[int] = []

    async def change_membership_before_lock(db, plan):
        marker = uuid.uuid4().hex
        async with session_maker() as session:
            submission = ArchiveSubmission(
                subject=course.name,
                category=course.category,
                name=f"Membership conflict {marker}",
                academic_year=2026,
                archive_type=ArchiveType.FINAL,
                professor="Membership Conflict Professor",
                object_name=f"submissions/membership-conflict-{marker}.pdf",
                requester_id=requester.id,
                status=SubmissionStatus.PENDING,
            )
            session.add(submission)
            await session.commit()
            await session.refresh(submission)
            inserted_submission_ids.append(submission.id)
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        change_membership_before_lock,
    )
    try:
        response = await client.delete(f"/courses/admin/courses/{course.id}")
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": COURSE_LIFECYCLE_CONFLICT_CODE,
            "message": COURSE_LIFECYCLE_CONFLICT_MESSAGE,
        }
        assert len(inserted_submission_ids) == 2
        async with session_maker() as session:
            assert (await session.get(Course, course.id)).deleted_at is None
            assert (await session.get(Archive, archive.id)).deleted_at is None
            for submission_id in [target.id, *inserted_submission_ids]:
                stored = await session.get(ArchiveSubmission, submission_id)
                assert stored.status == SubmissionStatus.PENDING
                assert stored.lifecycle_reason is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if inserted_submission_ids:
            async with session_maker() as session:
                await session.execute(
                    delete(ArchiveSubmission).where(
                        ArchiveSubmission.id.in_(inserted_submission_ids)
                    )
                )
                await session.commit()
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_two_course_reverse_input_plans_lock_identically(
    session_maker,
    make_user,
):
    requester = await make_user()
    first = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    second = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    first_category, first_course, first_archive, first_submission = first
    second_category, second_course, second_archive, second_submission = second
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    traces = []
    sqlstates: list[str] = []

    async def acquire(*, reverse: bool, hold: bool) -> None:
        courses = [first_course.id, second_course.id]
        archives = [first_archive.id, second_archive.id]
        submissions = [first_submission.id, second_submission.id]
        if reverse:
            courses.reverse()
            archives.reverse()
            submissions.reverse()
        plan = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            course_ids=courses,
            archive_ids=archives,
            submission_ids=submissions,
        )
        traces.append(_resource_trace(plan))
        async with session_maker() as session:
            if not hold:
                second_attempted.set()
            try:
                await archive_lifecycle_locks.acquire_lifecycle_locks(
                    session,
                    plan,
                )
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None) or getattr(
                    getattr(exc, "orig", None),
                    "sqlstate",
                    None,
                )
                if sqlstate:
                    sqlstates.append(str(sqlstate))
                raise
            if hold:
                first_locked.set()
                await asyncio.wait_for(release_first.wait(), timeout=10)
            await session.rollback()

    first_task = asyncio.create_task(acquire(reverse=True, hold=True))
    await asyncio.wait_for(first_locked.wait(), timeout=10)
    second_task = asyncio.create_task(acquire(reverse=False, hold=False))
    await asyncio.wait_for(second_attempted.wait(), timeout=10)
    assert not second_task.done()
    release_first.set()
    try:
        await asyncio.wait_for(first_task, timeout=10)
        await asyncio.wait_for(second_task, timeout=10)
        assert traces[0] == traces[1]
        assert traces[0] == sorted(traces[0])
        assert "40P01" not in sqlstates
    finally:
        release_first.set()
        await _cleanup_archive_context(
            session_maker,
            category_id=first_category.id,
            course_id=first_course.id,
            archive_ids=[first_archive.id],
            submission_ids=[first_submission.id],
        )
        await _cleanup_archive_context(
            session_maker,
            category_id=second_category.id,
            course_id=second_course.id,
            archive_ids=[second_archive.id],
            submission_ids=[second_submission.id],
        )


@pytest.mark.asyncio
async def test_approve_existing_acquires_mutex_then_parent_first_one_to_one_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    trace: list[tuple[str, object]] = []
    original_mutex = archive_lifecycle_locks.acquire_approval_namespace_mutex
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_mutex(db, **kwargs):
        trace.append(("mutex", None))
        return await original_mutex(db, **kwargs)

    async def observed_acquire(db, plan):
        trace.append(("rows", _resource_trace(plan)))
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_approval_namespace_mutex",
        observed_mutex,
    )
    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{target.id}/approve",
            json={"expected_status": "pending", "note": "parent first"},
        )
        assert response.status_code == 200
        assert trace == [
            ("mutex", None),
            (
                "rows",
                [
                    (LifecycleResourceClass.COURSE_CATEGORY, category.id),
                    (LifecycleResourceClass.COURSE, course.id),
                    (LifecycleResourceClass.ARCHIVE, archive.id),
                    (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
                ],
            ),
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_archive_trash_and_restore_share_parent_first_one_to_one_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    trace = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        trace.append(_resource_trace(plan))
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        delete_response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}"
        )
        assert delete_response.status_code == 200
        restore_response = await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )
        assert restore_response.status_code == 200

        expected = [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
        ]
        assert trace == [expected, expected]

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("delete_actor", ["owner", "admin"])
@pytest.mark.asyncio
async def test_submission_delete_acquires_parent_first_one_to_one_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
    delete_actor,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()

    traces = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(_resource_trace(plan))
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    actor = requester if delete_actor == "owner" else admin
    path = (
        f"/archives/submissions/{target.id}"
        if delete_actor == "owner"
        else f"/archives/admin/submissions/{target.id}"
    )
    app.dependency_overrides[get_current_user] = _override_user(
        actor.id,
        is_admin=delete_actor == "admin",
    )
    try:
        response = await client.delete(path)
        assert response.status_code == 200
        assert response.json()["changed"] is True
        assert traces == [
            [
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
            ]
        ]
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(ArchiveSubmission, target.id)
            assert stored_archive.deleted_at is not None
            assert stored_submission.status == SubmissionStatus.DELETED
            assert stored_submission.deleted_at is not None
            assert stored_submission.previous_status == SubmissionStatus.APPROVED
            assert stored_submission.owner_self_delete_consumed is (
                delete_actor == "owner"
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == target.id,
                        )
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(ArchiveSubmissionEvent.id)).where(
                            ArchiveSubmissionEvent.submission_id == target.id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_owner_submission_delete_authorizes_before_retry_noop(
    client,
    session_maker,
    make_user,
):
    requester = await make_user()
    stranger = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()

    try:
        app.dependency_overrides[get_current_user] = _override_user(
            requester.id,
            is_admin=False,
        )
        first = await client.delete(f"/archives/submissions/{target.id}")
        retry = await client.delete(f"/archives/submissions/{target.id}")

        assert first.status_code == 200
        assert first.json()["changed"] is True
        assert retry.status_code == 200
        assert retry.json()["changed"] is False

        app.dependency_overrides[get_current_user] = _override_user(
            stranger.id,
            is_admin=False,
        )
        forbidden = await client.delete(f"/archives/submissions/{target.id}")
        assert forbidden.status_code == 403

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.APPROVED
            assert stored.owner_self_delete_consumed is True
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == target.id,
                        )
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(ArchiveSubmissionEvent.id)).where(
                            ArchiveSubmissionEvent.submission_id == target.id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_consumed_owner_submission_delete_returns_stable_conflict(
    client,
    session_maker,
    make_user,
):
    requester = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        stored.owner_self_delete_consumed = True
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_user(
        requester.id,
        is_admin=False,
    )
    try:
        response = await client.delete(f"/archives/submissions/{target.id}")
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "archive_submission_self_delete_consumed",
            "message": "此投稿的自助刪除資格已使用。",
            "reload_required": False,
        }

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.deleted_at is None
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is True
            assert stored_archive.deleted_at is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize(
    "prior_status",
    [
        SubmissionStatus.PENDING,
        SubmissionStatus.APPROVED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.TAKEDOWN,
    ],
)
@pytest.mark.asyncio
async def test_admin_submission_delete_records_exact_provenance(
    client,
    session_maker,
    make_user,
    prior_status,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = prior_status
        stored.owner_self_delete_consumed = prior_status == SubmissionStatus.REJECTED
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.delete(f"/archives/admin/submissions/{target.id}")
        assert response.status_code == 200
        assert response.json()["changed"] is True

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == prior_status
            assert stored.owner_self_delete_consumed is (
                prior_status == SubmissionStatus.REJECTED
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_admin_submission_delete_retry_preserves_existing_provenance(
    client,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.DELETED
        stored.previous_status = SubmissionStatus.TAKEDOWN
        stored.owner_self_delete_consumed = True
        stored.deleted_at = stored.reviewed_at
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.delete(f"/archives/admin/submissions/{target.id}")
        assert response.status_code == 200
        assert response.json()["changed"] is False

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.TAKEDOWN
            assert stored.owner_self_delete_consumed is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_system_submission_group_delete_records_provenance_without_consuming_owner(
    session_maker,
    make_user,
):
    requester = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored = await session.get(ArchiveSubmission, target.id)
            stored.status = SubmissionStatus.REJECTED
            result = await soft_delete_archive_submission_group(
                session,
                archive=stored_archive,
                submission=stored,
                user_id=None,
                reason="system cascade",
            )
            await session.commit()
            assert result["submissions"] == 1

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.REJECTED
            assert stored.owner_self_delete_consumed is False
    finally:
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_owner_submission_delete_rolls_back_provenance_flag_and_linked_archive(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()

    original_delete = archives_service.soft_delete_submission_with_linked_archive

    async def fail_after_mutation(*args, **kwargs):
        await original_delete(*args, **kwargs)
        raise RuntimeError("injected delete failure")

    monkeypatch.setattr(
        archives_service,
        "soft_delete_submission_with_linked_archive",
        fail_after_mutation,
    )
    app.dependency_overrides[get_current_user] = _override_user(
        requester.id,
        is_admin=False,
    )
    try:
        with pytest.raises(RuntimeError, match="injected delete failure"):
            await client.delete(f"/archives/submissions/{target.id}")

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored_archive.deleted_at is None
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.deleted_at is None
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is False
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == target.id,
                        )
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(ArchiveSubmissionEvent.id)).where(
                            ArchiveSubmissionEvent.submission_id == target.id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_submission_restore_acquires_parent_first_one_to_one_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    async with session_maker() as session:
        stored_archive = await session.get(Archive, archive.id)
        stored_submission = await session.get(ArchiveSubmission, target.id)
        stored_archive.deleted_at = stored_submission.deleted_at = (
            stored_submission.reviewed_at
        )
        stored_submission.status = SubmissionStatus.DELETED
        stored_submission.previous_status = SubmissionStatus.APPROVED
        stored_submission.delete_reason = "admin deleted"
        await session.commit()

    traces = []
    original_acquire = archive_lifecycle_locks.acquire_lifecycle_locks

    async def observed_acquire(db, plan):
        traces.append(_resource_trace(plan))
        return await original_acquire(db, plan)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_acquire,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": target.id},
        )
        assert response.status_code == 200
        assert traces == [
            [
                (LifecycleResourceClass.COURSE, course.id),
                (LifecycleResourceClass.ARCHIVE, archive.id),
                (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
            ]
        ]
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(ArchiveSubmission, target.id)
            assert stored_archive.deleted_at is None
            assert stored_submission.status == SubmissionStatus.APPROVED
            assert stored_submission.deleted_at is None
            assert stored_submission.previous_status is None
            assert stored_submission.owner_self_delete_consumed is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize(
    ("previous_status", "expected_status", "expected_archive_restored"),
    [
        (SubmissionStatus.APPROVED, SubmissionStatus.APPROVED, True),
        (SubmissionStatus.PENDING, SubmissionStatus.PENDING, False),
        (SubmissionStatus.REJECTED, SubmissionStatus.REJECTED, False),
        (SubmissionStatus.TAKEDOWN, SubmissionStatus.TAKEDOWN, False),
        (None, SubmissionStatus.PENDING, False),
    ],
)
@pytest.mark.asyncio
async def test_submission_restore_uses_exact_previous_status_with_pending_fallback(
    client,
    session_maker,
    make_user,
    previous_status,
    expected_status,
    expected_archive_restored,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    deleted_at = datetime.now(timezone.utc)
    async with session_maker() as session:
        stored_archive = await session.get(Archive, archive.id)
        stored_submission = await session.get(ArchiveSubmission, target.id)
        stored_archive.deleted_at = deleted_at
        stored_submission.status = SubmissionStatus.DELETED
        stored_submission.previous_status = previous_status
        stored_submission.deleted_at = deleted_at
        stored_submission.delete_reason = "admin deleted"
        stored_submission.owner_self_delete_consumed = True
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": target.id},
        )

        assert response.status_code == 200
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_submission = await session.get(ArchiveSubmission, target.id)
            assert stored_submission.status == expected_status
            assert stored_submission.deleted_at is None
            assert stored_submission.previous_status is None
            assert stored_submission.owner_self_delete_consumed is True
            assert (stored_archive.deleted_at is None) is expected_archive_restored
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["owner", "admin"])
@pytest.mark.asyncio
async def test_owner_and_admin_submission_delete_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    actor = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=actor.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(actor.id)

    async def owner_delete():
        return await client.delete(f"/archives/submissions/{target.id}")

    async def admin_delete():
        return await client.delete(f"/archives/admin/submissions/{target.id}")

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                owner_delete if first_operation == "owner" else admin_delete
            ),
            second_request=(
                admin_delete if first_operation == "owner" else owner_delete
            ),
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert sorted([first.json()["changed"], second.json()["changed"]]) == [
            False,
            True,
        ]
        assert "40P01" not in sqlstates
        assert traces[0] == traces[1]
        assert traces[0] == [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
        ]

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.deleted_at is not None
            assert stored.previous_status == SubmissionStatus.APPROVED
            assert stored.owner_self_delete_consumed is (first_operation == "owner")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["delete", "restore"])
@pytest.mark.asyncio
async def test_submission_delete_and_restore_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    actor = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=actor.id,
    )
    async with session_maker() as session:
        stored = await session.get(ArchiveSubmission, target.id)
        stored.status = SubmissionStatus.APPROVED
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(actor.id)

    async def delete_submission():
        return await client.delete(f"/archives/submissions/{target.id}")

    async def restore_submission():
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": target.id},
        )

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                delete_submission if first_operation == "delete" else restore_submission
            ),
            second_request=(
                restore_submission if first_operation == "delete" else delete_submission
            ),
        )
        assert first.status_code == (200 if first_operation == "delete" else 404)
        assert second.status_code == 200
        assert "40P01" not in sqlstates
        assert traces[0] == traces[1]
        assert traces[0] == [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
        ]

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            if first_operation == "delete":
                assert stored.status == SubmissionStatus.APPROVED
                assert stored.deleted_at is None
                assert stored.previous_status is None
            else:
                assert stored.status == SubmissionStatus.DELETED
                assert stored.deleted_at is not None
                assert stored.previous_status == SubmissionStatus.APPROVED
            assert stored.owner_self_delete_consumed is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["edit", "review"])
@pytest.mark.asyncio
async def test_submission_edit_and_review_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=admin.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def edit_submission():
        return await client.put(
            f"/archives/admin/submissions/{target.id}",
            json={"professor": "Serialized edit professor"},
        )

    async def approve_submission():
        return await client.post(
            f"/archives/admin/submissions/{target.id}/approve",
            json={"expected_status": "pending"},
        )

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                edit_submission if first_operation == "edit" else approve_submission
            ),
            second_request=(
                approve_submission if first_operation == "edit" else edit_submission
            ),
        )
        assert first.status_code == 200
        assert second.status_code == (200 if first_operation == "edit" else 409)
        if first_operation == "review":
            assert (
                second.json()["detail"]
                == archives_service.ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL
            )
        assert "40P01" not in sqlstates
        for trace in traces:
            assert trace == sorted(trace)
            assert (LifecycleResourceClass.COURSE, course.id) in trace
            assert (LifecycleResourceClass.ARCHIVE, archive.id) in trace
            assert (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                target.id,
            ) in trace

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.APPROVED
            assert stored.professor == (
                "Serialized edit professor"
                if first_operation == "edit"
                else "Lock Professor"
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["edit", "delete"])
@pytest.mark.asyncio
async def test_submission_edit_and_delete_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=admin.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def edit_submission():
        return await client.put(
            f"/archives/admin/submissions/{target.id}",
            json={"professor": "Serialized edit professor"},
        )

    async def delete_submission():
        return await client.delete(f"/archives/admin/submissions/{target.id}")

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                edit_submission if first_operation == "edit" else delete_submission
            ),
            second_request=(
                delete_submission if first_operation == "edit" else edit_submission
            ),
        )
        assert first.status_code == 200
        assert second.status_code == (200 if first_operation == "edit" else 409)
        if first_operation == "delete":
            assert (
                second.json()["detail"]
                == archives_service.ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL
            )
        assert "40P01" not in sqlstates
        assert traces[0] == traces[1]

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.PENDING
            assert stored.professor == (
                "Serialized edit professor"
                if first_operation == "edit"
                else "Lock Professor"
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["edit", "restore"])
@pytest.mark.asyncio
async def test_submission_edit_and_restore_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=admin.id,
    )
    deleted_at = datetime.now(timezone.utc)
    async with session_maker() as session:
        stored_archive = await session.get(Archive, archive.id)
        stored = await session.get(ArchiveSubmission, target.id)
        stored_archive.deleted_at = deleted_at
        stored.status = SubmissionStatus.DELETED
        stored.previous_status = SubmissionStatus.PENDING
        stored.deleted_at = deleted_at
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def edit_submission():
        return await client.put(
            f"/archives/admin/submissions/{target.id}",
            json={"professor": "Serialized edit professor"},
        )

    async def restore_submission():
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": target.id},
        )

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=(
                edit_submission if first_operation == "edit" else restore_submission
            ),
            second_request=(
                restore_submission if first_operation == "edit" else edit_submission
            ),
        )
        assert first.status_code == (409 if first_operation == "edit" else 200)
        assert second.status_code == 200
        if first_operation == "edit":
            assert (
                first.json()["detail"]
                == archives_service.ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL
            )
        assert "40P01" not in sqlstates
        assert traces[0] == traces[1]

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == SubmissionStatus.PENDING
            assert stored.previous_status is None
            assert stored.professor == (
                "Serialized edit professor"
                if first_operation == "restore"
                else "Lock Professor"
            )
            assert stored_archive.deleted_at == deleted_at
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize(
    ("previous_status", "restored_status", "edit_allowed", "archive_restored"),
    [
        (SubmissionStatus.PENDING, SubmissionStatus.PENDING, True, False),
        (SubmissionStatus.REJECTED, SubmissionStatus.REJECTED, True, False),
        (SubmissionStatus.TAKEDOWN, SubmissionStatus.TAKEDOWN, True, False),
        (SubmissionStatus.APPROVED, SubmissionStatus.APPROVED, False, True),
        (None, SubmissionStatus.PENDING, True, False),
    ],
)
@pytest.mark.asyncio
async def test_submission_restore_then_edit_obeys_restored_state_contract(
    client,
    session_maker,
    make_user,
    previous_status,
    restored_status,
    edit_allowed,
    archive_restored,
):
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=admin.id,
    )
    deleted_at = datetime.now(timezone.utc)
    async with session_maker() as session:
        stored_archive = await session.get(Archive, archive.id)
        stored = await session.get(ArchiveSubmission, target.id)
        stored_archive.deleted_at = deleted_at
        stored.status = SubmissionStatus.DELETED
        stored.previous_status = previous_status
        stored.owner_self_delete_consumed = True
        stored.deleted_at = deleted_at
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        restore_response = await client.post(
            "/trash/restore",
            json={"item_type": "archive_submission", "item_id": target.id},
        )
        edit_response = await client.put(
            f"/archives/admin/submissions/{target.id}",
            json={"professor": "Post-restore edit professor"},
        )

        assert restore_response.status_code == 200
        assert edit_response.status_code == (200 if edit_allowed else 409)
        if not edit_allowed:
            assert (
                edit_response.json()["detail"]
                == archives_service.ARCHIVE_SUBMISSION_EDIT_FORBIDDEN_DETAIL
            )

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored = await session.get(ArchiveSubmission, target.id)
            assert stored.status == restored_status
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is True
            assert stored.professor == (
                "Post-restore edit professor" if edit_allowed else "Lock Professor"
            )
            assert (stored_archive.deleted_at is None) is archive_restored
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_reverse_input_submission_plans_lock_same_rows_in_same_order(
    session_maker,
    make_user,
):
    requester = await make_user()
    category, course, first_archive, first_submission = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    second_archive, second_submission = await _create_second_pair(
        session_maker,
        course=course,
        requester_id=requester.id,
    )
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    traces = []
    sqlstates: list[str] = []

    async def acquire(input_order, *, hold, attempted):
        plan = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            course_ids=[course.id, course.id],
            archive_ids=input_order["archives"],
            submission_ids=input_order["submissions"],
        )
        traces.append(_resource_trace(plan))
        async with session_maker() as session:
            if attempted:
                second_attempted.set()
            try:
                await archive_lifecycle_locks.acquire_lifecycle_locks(session, plan)
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None) or getattr(
                    getattr(exc, "orig", None),
                    "sqlstate",
                    None,
                )
                if sqlstate:
                    sqlstates.append(str(sqlstate))
                raise
            if hold:
                first_locked.set()
                await asyncio.wait_for(release_first.wait(), timeout=10)
            await session.rollback()

    first_task = asyncio.create_task(
        acquire(
            {
                "archives": [second_archive.id, first_archive.id],
                "submissions": [second_submission.id, first_submission.id],
            },
            hold=True,
            attempted=False,
        )
    )
    await asyncio.wait_for(first_locked.wait(), timeout=10)
    second_task = asyncio.create_task(
        acquire(
            {
                "archives": [first_archive.id, second_archive.id],
                "submissions": [first_submission.id, second_submission.id],
            },
            hold=False,
            attempted=True,
        )
    )
    await asyncio.wait_for(second_attempted.wait(), timeout=10)
    assert not second_task.done()
    release_first.set()
    try:
        await asyncio.wait_for(first_task, timeout=10)
        await asyncio.wait_for(second_task, timeout=10)
        assert traces[0] == traces[1]
        assert traces[0] == [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, first_archive.id),
            (LifecycleResourceClass.ARCHIVE, second_archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, first_submission.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, second_submission.id),
        ]
        assert "40P01" not in sqlstates
    finally:
        release_first.set()
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[first_archive.id, second_archive.id],
            submission_ids=[first_submission.id, second_submission.id],
        )


@pytest.mark.parametrize("first_operation", ["approve", "trash"])
@pytest.mark.asyncio
async def test_approve_existing_and_archive_trash_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def approve():
        return await client.post(
            f"/archives/admin/submissions/{target.id}/approve",
            json={"expected_status": "pending", "note": "race approve"},
        )

    async def trash():
        return await client.delete(f"/courses/{course.id}/archives/{archive.id}")

    try:
        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=approve if first_operation == "approve" else trash,
            second_request=trash if first_operation == "approve" else approve,
        )
        assert first.status_code == 200
        if first_operation == "approve":
            assert first.json()["changed"] is True
            assert second.status_code == 200
        else:
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == ("archive_submission_stale_state")
        assert "40P01" not in sqlstates

        for trace in traces:
            assert trace == sorted(trace)
            assert (LifecycleResourceClass.COURSE, course.id) in trace
            assert (LifecycleResourceClass.ARCHIVE, archive.id) in trace
            assert trace.index(
                (LifecycleResourceClass.COURSE, course.id)
            ) < trace.index((LifecycleResourceClass.ARCHIVE, archive.id))
            submission_ids = [
                resource_id
                for resource_class, resource_id in trace
                if resource_class == LifecycleResourceClass.ARCHIVE_SUBMISSION
            ]
            assert submission_ids == [target.id]

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_target = await session.get(ArchiveSubmission, target.id)
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == target.id,
                    )
                )
                or 0
            )
            event_count = int(
                await session.scalar(
                    select(func.count(ArchiveSubmissionEvent.id)).where(
                        ArchiveSubmissionEvent.submission_id == target.id
                    )
                )
                or 0
            )
        assert stored_archive.deleted_at is not None
        assert stored_target.status == SubmissionStatus.TAKEDOWN
        assert notification_count == (1 if first_operation == "approve" else 0)
        assert event_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_trash_and_restore_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def trash():
        return await client.delete(f"/courses/{course.id}/archives/{archive.id}")

    async def restore():
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )

    try:
        if first_operation == "restore":
            setup_response = await trash()
            assert setup_response.status_code == 200

        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=trash if first_operation == "trash" else restore,
            second_request=restore if first_operation == "trash" else trash,
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert "40P01" not in sqlstates
        assert traces[0] == traces[1]
        assert traces[0] == [
            (LifecycleResourceClass.COURSE, course.id),
            (LifecycleResourceClass.ARCHIVE, archive.id),
            (LifecycleResourceClass.ARCHIVE_SUBMISSION, target.id),
        ]

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_target = await session.get(ArchiveSubmission, target.id)
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == target.id,
                    )
                )
                or 0
            )
        if first_operation == "trash":
            assert stored_archive.deleted_at is None
            assert stored_target.status == SubmissionStatus.APPROVED
        else:
            assert stored_archive.deleted_at is not None
            assert stored_target.status == SubmissionStatus.TAKEDOWN
        assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("first_operation", ["restore", "republish"])
@pytest.mark.asyncio
async def test_republish_and_archive_restore_serialize_without_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    first_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def restore():
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )

    async def republish():
        return await client.post(
            f"/archives/admin/submissions/{target.id}/republish",
            json={"expected_status": "takedown", "note": "restore race"},
        )

    try:
        setup_response = await client.delete(
            f"/courses/{course.id}/archives/{archive.id}"
        )
        assert setup_response.status_code == 200

        first, second, traces, sqlstates = await _run_two_request_lock_race(
            monkeypatch=monkeypatch,
            first_request=restore if first_operation == "restore" else republish,
            second_request=republish if first_operation == "restore" else restore,
        )
        if first_operation == "restore":
            assert first.status_code == 200
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == ("archive_submission_stale_state")
        else:
            assert first.status_code == 409
            assert second.status_code == 200
        assert "40P01" not in sqlstates
        for trace in traces:
            assert trace == sorted(trace)
            assert (LifecycleResourceClass.COURSE, course.id) in trace
            assert (LifecycleResourceClass.ARCHIVE, archive.id) in trace
            assert (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                target.id,
            ) in trace

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_target = await session.get(ArchiveSubmission, target.id)
        assert stored_archive.deleted_at is None
        assert stored_target.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_two_one_to_one_pairs_reverse_input_lock_same_canonical_order(
    session_maker,
    make_user,
):
    requester = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    second_archive, second_submission = await _create_second_pair(
        session_maker,
        course=course,
        requester_id=requester.id,
    )
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    traces = []
    sqlstates: list[str] = []
    archive_ids = [archive.id, second_archive.id]
    submission_ids = [target.id, second_submission.id]

    async def worker(input_archive_ids, input_submission_ids, *, first):
        plan = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            course_ids=[course.id],
            archive_ids=input_archive_ids,
            submission_ids=input_submission_ids,
        )
        traces.append(_resource_trace(plan))
        async with session_maker() as session:
            if not first:
                second_attempted.set()
            try:
                locked = await archive_lifecycle_locks.acquire_lifecycle_locks(
                    session,
                    plan,
                )
                if first:
                    first_locked.set()
                    await asyncio.wait_for(release_first.wait(), timeout=10)
                assert [row.id for row in locked.archives] == sorted(archive_ids)
                assert [row.id for row in locked.submissions] == sorted(submission_ids)
                await session.rollback()
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None) or getattr(
                    getattr(exc, "orig", None),
                    "sqlstate",
                    None,
                )
                if sqlstate:
                    sqlstates.append(str(sqlstate))
                raise

    try:
        first_task = asyncio.create_task(
            worker(
                list(reversed(archive_ids)),
                list(reversed(submission_ids)),
                first=True,
            )
        )
        await asyncio.wait_for(first_locked.wait(), timeout=10)
        second_task = asyncio.create_task(
            worker(archive_ids, submission_ids, first=False)
        )
        await asyncio.wait_for(second_attempted.wait(), timeout=10)
        assert not second_task.done()
        release_first.set()
        await asyncio.wait_for(first_task, timeout=10)
        await asyncio.wait_for(second_task, timeout=10)
        assert traces[0] == traces[1]
        assert "40P01" not in sqlstates
    finally:
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=archive_ids,
            submission_ids=submission_ids,
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_rebuilds_once_after_real_membership_change(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    created_submission_ids: list[int] = []
    discovery_ready = asyncio.Event()
    membership_committed = asyncio.Event()
    discovery_calls = 0
    original_discover = archive_lifecycle_locks.discover_exact_archive_lifecycle_plan

    async def observed_discover(db, *, archive_id, operation):
        nonlocal discovery_calls
        plan = await original_discover(
            db,
            archive_id=archive_id,
            operation=operation,
        )
        discovery_calls += 1
        if discovery_calls == 1:
            discovery_ready.set()
            await asyncio.wait_for(membership_committed.wait(), timeout=10)
        return plan

    async def mutate_membership_once():
        await asyncio.wait_for(discovery_ready.wait(), timeout=10)
        created_submission_ids.append(
            await _replace_archive_source(
                session_maker,
                archive=archive,
                course=course,
                requester_id=requester.id,
                current_source_id=target.id,
                status=(
                    SubmissionStatus.APPROVED
                    if operation == "trash"
                    else SubmissionStatus.TAKEDOWN
                ),
                lifecycle_reason=(
                    None if operation == "trash" else LIFECYCLE_ARCHIVE_TRASHED
                ),
            )
        )
        membership_committed.set()

    async def invoke_operation():
        if operation == "trash":
            return await client.delete(f"/courses/{course.id}/archives/{archive.id}")
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )

    try:
        if operation == "restore":
            setup_response = await client.delete(
                f"/courses/{course.id}/archives/{archive.id}"
            )
            assert setup_response.status_code == 200

        monkeypatch.setattr(
            archive_lifecycle_locks,
            "discover_exact_archive_lifecycle_plan",
            observed_discover,
        )
        mutation_task = asyncio.create_task(mutate_membership_once())
        response = await asyncio.wait_for(invoke_operation(), timeout=10)
        await asyncio.wait_for(mutation_task, timeout=10)

        assert response.status_code == 200
        assert discovery_calls == 2
        replacement_id = created_submission_ids[0]
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_target = await session.get(ArchiveSubmission, target.id)
            stored_replacement = await session.get(
                ArchiveSubmission,
                replacement_id,
            )
        assert stored_target.created_archive_id is None
        if operation == "trash":
            assert stored_archive.deleted_at is not None
            assert stored_target.status == SubmissionStatus.PENDING
            assert stored_replacement.status == SubmissionStatus.TAKEDOWN
        else:
            assert stored_archive.deleted_at is None
            assert stored_target.status == SubmissionStatus.TAKEDOWN
            assert stored_replacement.status == SubmissionStatus.APPROVED
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id, *created_submission_ids],
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_second_membership_change_returns_contract(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    created_submission_ids: list[int] = []
    discovery_events = [asyncio.Event(), asyncio.Event()]
    membership_events = [asyncio.Event(), asyncio.Event()]
    discovery_calls = 0
    current_source_id = target.id
    original_discover = archive_lifecycle_locks.discover_exact_archive_lifecycle_plan

    async def observed_discover(db, *, archive_id, operation):
        nonlocal discovery_calls
        plan = await original_discover(
            db,
            archive_id=archive_id,
            operation=operation,
        )
        call_index = discovery_calls
        discovery_calls += 1
        if call_index < 2:
            discovery_events[call_index].set()
            await asyncio.wait_for(
                membership_events[call_index].wait(),
                timeout=10,
            )
        return plan

    async def mutate_membership_twice():
        nonlocal current_source_id
        for call_index in range(2):
            await asyncio.wait_for(
                discovery_events[call_index].wait(),
                timeout=10,
            )
            replacement_id = await _replace_archive_source(
                session_maker,
                archive=archive,
                course=course,
                requester_id=requester.id,
                current_source_id=current_source_id,
                status=(
                    SubmissionStatus.APPROVED
                    if operation == "trash"
                    else SubmissionStatus.TAKEDOWN
                ),
                lifecycle_reason=(
                    None if operation == "trash" else LIFECYCLE_ARCHIVE_TRASHED
                ),
            )
            created_submission_ids.append(replacement_id)
            current_source_id = replacement_id
            membership_events[call_index].set()

    async def invoke_operation():
        if operation == "trash":
            return await client.delete(f"/courses/{course.id}/archives/{archive.id}")
        return await client.post(
            "/trash/restore",
            json={"item_type": "archive", "item_id": archive.id},
        )

    try:
        if operation == "restore":
            setup_response = await client.delete(
                f"/courses/{course.id}/archives/{archive.id}"
            )
            assert setup_response.status_code == 200

        async with session_maker() as session:
            archive_before = await session.get(Archive, archive.id)
            target_before = await session.get(ArchiveSubmission, target.id)
            lifecycle_before = (
                archive_before.deleted_at,
                archive_before.deleted_by_id,
                archive_before.deleted_reason,
                archive_before.restored_at,
                archive_before.restored_by_id,
                target_before.status,
                target_before.lifecycle_reason,
                target_before.reviewed_at,
                target_before.reviewer_id,
            )

        monkeypatch.setattr(
            archive_lifecycle_locks,
            "discover_exact_archive_lifecycle_plan",
            observed_discover,
        )
        mutation_task = asyncio.create_task(mutate_membership_twice())
        response = await asyncio.wait_for(invoke_operation(), timeout=10)
        await asyncio.wait_for(mutation_task, timeout=10)

        assert response.status_code == 409
        assert response.json() == {
            "detail": {
                "code": ARCHIVE_LIFECYCLE_CONFLICT_CODE,
                "message": ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE,
            }
        }
        assert discovery_calls == 2
        assert len(created_submission_ids) == 2
        assert "fingerprint" not in response.text
        assert str(archive.id) not in response.text

        async with session_maker() as session:
            archive_after = await session.get(Archive, archive.id)
            target_after = await session.get(ArchiveSubmission, target.id)
            lifecycle_after = (
                archive_after.deleted_at,
                archive_after.deleted_by_id,
                archive_after.deleted_reason,
                archive_after.restored_at,
                archive_after.restored_by_id,
                target_after.status,
                target_after.lifecycle_reason,
                target_after.reviewed_at,
                target_after.reviewer_id,
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id.in_(
                            [target.id, *created_submission_ids]
                        ),
                    )
                )
                or 0
            )
        assert lifecycle_after == lifecycle_before
        assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id, *created_submission_ids],
        )


@pytest.mark.parametrize(
    ("operation", "route_operation"),
    [("trash", "archive_trash"), ("restore", "archive_restore")],
)
@pytest.mark.asyncio
async def test_static_multi_source_anomaly_is_generic_500_without_rebuild(
    session_maker,
    make_user,
    monkeypatch,
    caplog,
    operation,
    route_operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    calls = 0
    original_validate = validate_archive_source_membership

    def static_anomaly(_submission_ids, *, operation):
        nonlocal calls
        calls += 1
        assert operation == route_operation
        return original_validate([101, 102], operation=operation)

    try:
        if operation == "restore":
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as setup_client:
                setup_response = await setup_client.delete(
                    f"/courses/{course.id}/archives/{archive.id}"
                )
            assert setup_response.status_code == 200

        async with session_maker() as session:
            archive_before = await session.get(Archive, archive.id)
            target_before = await session.get(ArchiveSubmission, target.id)
            before = (
                archive_before.deleted_at,
                archive_before.deleted_reason,
                archive_before.restored_at,
                target_before.status,
                target_before.lifecycle_reason,
            )

        monkeypatch.setattr(
            archive_lifecycle_locks,
            "validate_archive_source_membership",
            static_anomaly,
        )
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as non_raising_client:
            if operation == "trash":
                response = await non_raising_client.delete(
                    f"/courses/{course.id}/archives/{archive.id}"
                )
            else:
                response = await non_raising_client.post(
                    "/trash/restore",
                    json={"item_type": "archive", "item_id": archive.id},
                )

        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert ARCHIVE_LIFECYCLE_CONFLICT_CODE not in response.text
        assert "archive_submission_link_conflict" not in response.text
        assert str(archive.id) not in response.text
        assert calls == 1
        assert any(
            getattr(record, "event", None)
            == "archive_submission_one_to_one_invariant_violation"
            and getattr(record, "operation", None) == route_operation
            for record in caplog.records
        )

        async with session_maker() as session:
            archive_after = await session.get(Archive, archive.id)
            target_after = await session.get(ArchiveSubmission, target.id)
            after = (
                archive_after.deleted_at,
                archive_after.deleted_reason,
                archive_after.restored_at,
                target_after.status,
                target_after.lifecycle_reason,
            )
        assert after == before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.asyncio
async def test_review_static_multi_source_anomaly_keeps_generic_500_boundary(
    session_maker,
    make_user,
    monkeypatch,
    caplog,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    original_validate = validate_archive_source_membership
    calls = 0

    def static_anomaly(_submission_ids, *, operation):
        nonlocal calls
        calls += 1
        assert operation == "approval"
        return original_validate([201, 202], operation=operation)

    monkeypatch.setattr(
        archives_service,
        "validate_archive_source_membership",
        static_anomaly,
    )
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as non_raising_client:
            response = await non_raising_client.post(
                f"/archives/admin/submissions/{target.id}/approve",
                json={"expected_status": "pending", "note": "static anomaly"},
            )

        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert ARCHIVE_LIFECYCLE_CONFLICT_CODE not in response.text
        assert "archive_submission_link_conflict" not in response.text
        assert str(archive.id) not in response.text
        assert calls == 1
        assert any(
            getattr(record, "event", None)
            == "archive_submission_one_to_one_invariant_violation"
            and getattr(record, "operation", None) == "approval"
            for record in caplog.records
        )

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            stored_target = await session.get(ArchiveSubmission, target.id)
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_id == target.id
                    )
                )
                or 0
            )
        assert stored_archive.deleted_at is None
        assert stored_target.status == SubmissionStatus.PENDING
        assert stored_target.created_archive_id == archive.id
        assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_contract_is_not_used_for_invariant_failure(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    async def fail_invariant(*args, **kwargs):
        raise archive_lifecycle_locks.LifecycleLockSetExpansionError(
            "test invariant failure"
        )

    try:
        if operation == "restore":
            setup_response = await client.delete(
                f"/courses/{course.id}/archives/{archive.id}"
            )
            assert setup_response.status_code == 200

        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_exact_archive_lifecycle_locks",
            fail_invariant,
        )
        with pytest.raises(
            archive_lifecycle_locks.LifecycleLockSetExpansionError,
            match="test invariant failure",
        ):
            if operation == "trash":
                await client.delete(f"/courses/{course.id}/archives/{archive.id}")
            else:
                await client.post(
                    "/trash/restore",
                    json={"item_type": "archive", "item_id": archive.id},
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_contract_does_not_swallow_database_deadlock(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)

    class SimulatedDeadlock(RuntimeError):
        sqlstate = "40P01"

    async def fail_deadlock(*args, **kwargs):
        raise SimulatedDeadlock("simulated database deadlock")

    try:
        if operation == "restore":
            setup_response = await client.delete(
                f"/courses/{course.id}/archives/{archive.id}"
            )
            assert setup_response.status_code == 200

        monkeypatch.setattr(
            archive_lifecycle_locks,
            "acquire_exact_archive_lifecycle_locks",
            fail_deadlock,
        )
        with pytest.raises(
            SimulatedDeadlock,
            match="simulated database deadlock",
        ):
            if operation == "trash":
                await client.delete(f"/courses/{course.id}/archives/{archive.id}")
            else:
                await client.post(
                    "/trash/restore",
                    json={"item_type": "archive", "item_id": archive.id},
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_missing_target_stays_not_found_after_retry(
    client,
    make_user,
    monkeypatch,
    operation,
):
    admin = await make_user(is_admin=True)
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    plan = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build()
    locked = archive_lifecycle_locks.LockedLifecycleRows(plan=plan)
    invalid = archive_lifecycle_locks.LifecycleRevalidationResult(
        valid=False,
        fingerprint=plan.fingerprint,
        reasons=("target_missing",),
    )
    calls = 0

    async def missing_target(*args, **kwargs):
        nonlocal calls
        calls += 1
        return locked, invalid

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_exact_archive_lifecycle_locks",
        missing_target,
    )
    try:
        if operation == "trash":
            response = await client.delete("/courses/999999/archives/999999")
        else:
            response = await client.post(
                "/trash/restore",
                json={"item_type": "archive", "item_id": 999999},
            )
        assert response.status_code == 404
        assert response.json()["detail"] == "Archive not found"
        assert calls == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_archive_trash_unauthorized_stays_forbidden_after_retry(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    intruder = await make_user()
    category, course, archive, target = await _create_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_user(
        intruder.id,
        is_admin=False,
    )
    original_acquire = archive_lifecycle_locks.acquire_exact_archive_lifecycle_locks
    calls = 0

    async def force_mismatch(db, *, archive_id, operation):
        nonlocal calls
        calls += 1
        locked, revalidation = await original_acquire(
            db,
            archive_id=archive_id,
            operation=operation,
        )
        assert locked is not None
        assert revalidation is not None
        return (
            locked,
            archive_lifecycle_locks.LifecycleRevalidationResult(
                valid=False,
                fingerprint=revalidation.fingerprint,
                reasons=("forced_membership_change",),
            ),
        )

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_exact_archive_lifecycle_locks",
        force_mismatch,
    )
    try:
        response = await client.delete(f"/courses/{course.id}/archives/{archive.id}")
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "You don't have permission to delete this archive"
        )
        assert calls == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_ids=[archive.id],
            submission_ids=[target.id],
        )
