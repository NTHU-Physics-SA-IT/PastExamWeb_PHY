import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import archives as archives_service
from app.api.services.archive_submission_lifecycle import (
    ARCHIVE_LIFECYCLE_CONFLICT_CODE,
    ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE,
    LIFECYCLE_ARCHIVE_TRASHED,
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
            assert stored_submission.previous_status is None
            assert stored_submission.owner_self_delete_consumed is False
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
        assert second.status_code == (409 if first_operation == "owner" else 200)
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
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is False
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
            else:
                assert stored.status == SubmissionStatus.DELETED
                assert stored.deleted_at is not None
            assert stored.previous_status is None
            assert stored.owner_self_delete_consumed is False
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
