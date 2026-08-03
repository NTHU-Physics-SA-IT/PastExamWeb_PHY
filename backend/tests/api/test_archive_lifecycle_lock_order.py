import asyncio
import uuid

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.main import app
from app.api.services.archive_submission_lifecycle import (
    ARCHIVE_LIFECYCLE_CONFLICT_CODE,
    ARCHIVE_LIFECYCLE_CONFLICT_MESSAGE,
    LIFECYCLE_ARCHIVE_TRASHED,
)
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


def _override_user(user_id: int, *, is_admin: bool):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


def _override_admin(user_id: int):
    return _override_user(user_id, is_admin=True)


async def _create_shared_archive_context(session_maker, *, requester_id: int):
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
        sibling = ArchiveSubmission(
            subject=course.name,
            category=category.key,
            name=f"Sibling {marker}",
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=f"archive/sibling-{marker}.pdf",
            requester_id=requester_id,
            status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
        )
        session.add(target)
        session.add(sibling)
        await session.commit()
        for row in (category, course, archive, target, sibling):
            await session.refresh(row)
    return category, course, archive, target, sibling


async def _cleanup_shared_archive_context(
    session_maker,
    *,
    category_id: int,
    course_id: int,
    archive_id: int,
    submission_ids: list[int],
) -> None:
    async with session_maker() as session:
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
            delete(ArchiveSubmission).where(ArchiveSubmission.id.in_(submission_ids))
        )
        await session.execute(delete(Archive).where(Archive.id == archive_id))
        await session.execute(delete(Course).where(Course.id == course_id))
        await session.execute(
            delete(CourseCategoryConfig).where(CourseCategoryConfig.id == category_id)
        )
        await session.commit()


async def _create_racing_sibling(
    session_maker,
    *,
    archive: Archive,
    course: Course,
    requester_id: int,
    status: SubmissionStatus,
    lifecycle_reason: str | None,
) -> int:
    marker = uuid.uuid4().hex
    async with session_maker() as session:
        sibling = ArchiveSubmission(
            subject=course.name,
            category=course.category,
            name=f"Racing sibling {marker}",
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=f"archive/racing-sibling-{marker}.pdf",
            requester_id=requester_id,
            status=status,
            lifecycle_reason=lifecycle_reason,
            created_archive_id=archive.id,
        )
        session.add(sibling)
        await session.commit()
        await session.refresh(sibling)
        return sibling.id


def _resource_trace(plan):
    return [(resource.resource_class, resource.row_id) for resource in plan.resources]


@pytest.mark.asyncio
async def test_approve_existing_acquires_mutex_then_parent_first_shared_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
                    (
                        LifecycleResourceClass.ARCHIVE_SUBMISSION,
                        min(target.id, sibling.id),
                    ),
                    (
                        LifecycleResourceClass.ARCHIVE_SUBMISSION,
                        max(target.id, sibling.id),
                    ),
                ],
            ),
        ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
        )


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
async def test_archive_trash_and_restore_share_parent_first_plan(
    client,
    session_maker,
    make_user,
    monkeypatch,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
            (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                min(target.id, sibling.id),
            ),
            (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                max(target.id, sibling.id),
            ),
        ]
        assert trace == [expected, expected]

        async with session_maker() as session:
            stored = list(
                (
                    await session.execute(
                        select(ArchiveSubmission)
                        .where(ArchiveSubmission.id.in_([target.id, sibling.id]))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert [row.status for row in stored] == [
                SubmissionStatus.APPROVED,
                SubmissionStatus.APPROVED,
            ]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
            assert second.json()["detail"]["code"] == "archive_submission_stale_state"
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
            assert submission_ids == sorted([target.id, sibling.id])

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
            archive_count = int(
                await session.scalar(
                    select(func.count(Archive.id)).where(Archive.id == archive.id)
                )
                or 0
            )
        assert stored_archive.deleted_at is not None
        assert stored_target.status == SubmissionStatus.TAKEDOWN
        assert notification_count == (1 if first_operation == "approve" else 0)
        assert event_count == 0
        assert archive_count == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
            (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                min(target.id, sibling.id),
            ),
            (
                LifecycleResourceClass.ARCHIVE_SUBMISSION,
                max(target.id, sibling.id),
            ),
        ]

        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            statuses = list(
                (
                    await session.execute(
                        select(ArchiveSubmission.status)
                        .where(ArchiveSubmission.id.in_([target.id, sibling.id]))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id.in_([target.id, sibling.id]),
                    )
                )
                or 0
            )
        if first_operation == "trash":
            assert stored_archive.deleted_at is None
            assert statuses == [
                SubmissionStatus.APPROVED,
                SubmissionStatus.APPROVED,
            ]
        else:
            assert stored_archive.deleted_at is not None
            assert statuses == [
                SubmissionStatus.TAKEDOWN,
                SubmissionStatus.TAKEDOWN,
            ]
        assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
        )


@pytest.mark.asyncio
async def test_shared_archive_reverse_input_locks_same_canonical_order(
    session_maker,
    make_user,
):
    requester = await make_user()
    category, course, archive, target, sibling = await _create_shared_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted = asyncio.Event()
    traces = []
    sqlstates: list[str] = []

    async def worker(input_ids, *, first):
        plan = archive_lifecycle_locks.ArchiveLifecycleLockPlan.build(
            course_ids=[course.id],
            archive_ids=[archive.id],
            submission_ids=input_ids,
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
                assert [row.id for row in locked.submissions] == sorted(input_ids)
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
        first_task = asyncio.create_task(worker([sibling.id, target.id], first=True))
        await asyncio.wait_for(first_locked.wait(), timeout=10)
        second_task = asyncio.create_task(worker([target.id, sibling.id], first=False))
        await asyncio.wait_for(second_attempted.wait(), timeout=10)
        assert not second_task.done()
        release_first.set()
        await asyncio.wait_for(first_task, timeout=10)
        await asyncio.wait_for(second_task, timeout=10)
        assert traces[0] == traces[1]
        assert "40P01" not in sqlstates

        async with session_maker() as session:
            statuses = list(
                (
                    await session.execute(
                        select(ArchiveSubmission.status)
                        .where(ArchiveSubmission.id.in_([target.id, sibling.id]))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        assert statuses == [
            SubmissionStatus.PENDING,
            SubmissionStatus.APPROVED,
        ]
    finally:
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    created_submission_ids: list[int] = []
    discovery_ready = asyncio.Event()
    membership_committed = asyncio.Event()
    discovery_calls = 0
    original_discover = archive_lifecycle_locks.discover_exact_archive_lifecycle_plan

    async def observed_discover(db, *, archive_id):
        nonlocal discovery_calls
        plan = await original_discover(db, archive_id=archive_id)
        discovery_calls += 1
        if discovery_calls == 1:
            discovery_ready.set()
            await asyncio.wait_for(membership_committed.wait(), timeout=10)
        return plan

    async def mutate_membership_once():
        await asyncio.wait_for(discovery_ready.wait(), timeout=10)
        created_submission_ids.append(
            await _create_racing_sibling(
                session_maker,
                archive=archive,
                course=course,
                requester_id=requester.id,
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
        assert len(created_submission_ids) == 1

        all_submission_ids = [
            target.id,
            sibling.id,
            *created_submission_ids,
        ]
        async with session_maker() as session:
            stored_archive = await session.get(Archive, archive.id)
            statuses = list(
                (
                    await session.execute(
                        select(ArchiveSubmission.status)
                        .where(ArchiveSubmission.id.in_(all_submission_ids))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id.in_(all_submission_ids),
                    )
                )
                or 0
            )
            event_count = int(
                await session.scalar(
                    select(func.count(ArchiveSubmissionEvent.id)).where(
                        ArchiveSubmissionEvent.submission_id.in_(all_submission_ids)
                    )
                )
                or 0
            )
        if operation == "trash":
            assert stored_archive.deleted_at is not None
            assert statuses == [SubmissionStatus.TAKEDOWN] * 3
        else:
            assert stored_archive.deleted_at is None
            assert statuses == [SubmissionStatus.APPROVED] * 3
        assert notification_count == 0
        assert event_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[
                target.id,
                sibling.id,
                *created_submission_ids,
            ],
        )


@pytest.mark.parametrize("operation", ["trash", "restore"])
@pytest.mark.asyncio
async def test_archive_lifecycle_second_real_membership_change_returns_contract(
    client,
    session_maker,
    make_user,
    monkeypatch,
    operation,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, archive, target, sibling = await _create_shared_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    created_submission_ids: list[int] = []
    discovery_events = [asyncio.Event(), asyncio.Event()]
    membership_events = [asyncio.Event(), asyncio.Event()]
    discovery_calls = 0
    original_discover = archive_lifecycle_locks.discover_exact_archive_lifecycle_plan

    async def observed_discover(db, *, archive_id):
        nonlocal discovery_calls
        plan = await original_discover(db, archive_id=archive_id)
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
        for call_index in range(2):
            await asyncio.wait_for(
                discovery_events[call_index].wait(),
                timeout=10,
            )
            created_submission_ids.append(
                await _create_racing_sibling(
                    session_maker,
                    archive=archive,
                    course=course,
                    requester_id=requester.id,
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
            submissions_before = list(
                (
                    await session.execute(
                        select(ArchiveSubmission)
                        .where(ArchiveSubmission.id.in_([target.id, sibling.id]))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            before = (
                archive_before.deleted_at,
                archive_before.deleted_by_id,
                archive_before.deleted_reason,
                archive_before.restored_at,
                archive_before.restored_by_id,
                tuple(
                    (
                        item.status,
                        item.lifecycle_reason,
                        item.reviewed_at,
                        item.reviewer_id,
                    )
                    for item in submissions_before
                ),
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

        all_submission_ids = [
            target.id,
            sibling.id,
            *created_submission_ids,
        ]
        async with session_maker() as session:
            archive_after = await session.get(Archive, archive.id)
            submissions_after = list(
                (
                    await session.execute(
                        select(ArchiveSubmission)
                        .where(ArchiveSubmission.id.in_([target.id, sibling.id]))
                        .order_by(ArchiveSubmission.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            after = (
                archive_after.deleted_at,
                archive_after.deleted_by_id,
                archive_after.deleted_reason,
                archive_after.restored_at,
                archive_after.restored_by_id,
                tuple(
                    (
                        item.status,
                        item.lifecycle_reason,
                        item.reviewed_at,
                        item.reviewer_id,
                    )
                    for item in submissions_after
                ),
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id.in_(all_submission_ids),
                    )
                )
                or 0
            )
            event_count = int(
                await session.scalar(
                    select(func.count(ArchiveSubmissionEvent.id)).where(
                        ArchiveSubmissionEvent.submission_id.in_(all_submission_ids)
                    )
                )
                or 0
            )
        assert after == before
        assert notification_count == 0
        assert event_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[
                target.id,
                sibling.id,
                *created_submission_ids,
            ],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
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
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
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
    category, course, archive, target, sibling = await _create_shared_archive_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_user(
        intruder.id,
        is_admin=False,
    )
    original_acquire = archive_lifecycle_locks.acquire_exact_archive_lifecycle_locks
    calls = 0

    async def force_mismatch(db, *, archive_id):
        nonlocal calls
        calls += 1
        locked, revalidation = await original_acquire(
            db,
            archive_id=archive_id,
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
        await _cleanup_shared_archive_context(
            session_maker,
            category_id=category.id,
            course_id=course.id,
            archive_id=archive.id,
            submission_ids=[target.id, sibling.id],
        )
