import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlmodel import select

from app.api.services import courses as courses_service
from app.models.models import (
    Course,
    CourseCategory,
    CourseSubmission,
    CourseSubmissionCreate,
    SubmissionDecision,
    SubmissionStatus,
    UserRoles,
)
from app.services import archive_lifecycle_locks
from app.utils.course_text import (
    normalize_course_search_text,
    normalized_course_text_expr,
)


async def _create_pending_request(
    session_maker,
    *,
    requester_id: int,
    name: str,
    category: str = CourseCategory.FRESHMAN.value,
) -> int:
    async with session_maker() as session:
        submission = CourseSubmission(
            name=name,
            category=category,
            requester_id=requester_id,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)
        return submission.id


async def _identity_snapshot(session_maker, *, name: str, category: str):
    normalized_name = normalize_course_search_text(name)
    async with session_maker() as session:
        submissions = list(
            (
                await session.execute(
                    select(CourseSubmission)
                    .where(
                        normalized_course_text_expr(CourseSubmission.name)
                        == normalized_name,
                        CourseSubmission.category == category,
                    )
                    .order_by(CourseSubmission.id)
                )
            )
            .scalars()
            .all()
        )
        courses = list(
            (
                await session.execute(
                    select(Course)
                    .where(
                        normalized_course_text_expr(Course.name) == normalized_name,
                        Course.category == category,
                    )
                    .order_by(Course.id)
                )
            )
            .scalars()
            .all()
        )
        return submissions, courses


async def _cleanup_identity(session_maker, *, name: str, category: str) -> None:
    normalized_name = normalize_course_search_text(name)
    async with session_maker() as session:
        await session.execute(
            delete(CourseSubmission).where(
                normalized_course_text_expr(CourseSubmission.name) == normalized_name,
                CourseSubmission.category == category,
            )
        )
        await session.execute(
            delete(Course).where(
                normalized_course_text_expr(Course.name) == normalized_name,
                Course.category == category,
            )
        )
        await session.commit()


async def _run_serialized_approvals(
    monkeypatch,
    session_maker,
    *,
    request_ids: tuple[int, int],
    admin_id: int,
):
    first_has_mutex = asyncio.Event()
    release_first = asyncio.Event()
    second_attempted_mutex = asyncio.Event()
    calls = 0
    original_mutex = archive_lifecycle_locks.acquire_approval_namespace_mutex

    async def observed_mutex(db, **kwargs):
        nonlocal calls
        calls += 1
        call_number = calls
        if call_number == 2:
            second_attempted_mutex.set()
        scope = await original_mutex(db, **kwargs)
        if call_number == 1:
            first_has_mutex.set()
            await asyncio.wait_for(release_first.wait(), timeout=10)
        return scope

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_approval_namespace_mutex",
        observed_mutex,
    )
    admin = UserRoles(user_id=admin_id, is_admin=True)

    async with session_maker() as first_session, session_maker() as second_session:
        first_task = asyncio.create_task(
            courses_service.approve_course_request(
                request_id=request_ids[0],
                decision=SubmissionDecision(note="first approval"),
                current_user=admin,
                db=first_session,
            )
        )
        try:
            await asyncio.wait_for(first_has_mutex.wait(), timeout=2)
        except TimeoutError:
            await first_task
            return False, None

        second_task = asyncio.create_task(
            courses_service.approve_course_request(
                request_id=request_ids[1],
                decision=SubmissionDecision(note="second approval"),
                current_user=admin,
                db=second_session,
            )
        )
        await asyncio.wait_for(second_attempted_mutex.wait(), timeout=5)
        assert not second_task.done()
        release_first.set()
        return True, await asyncio.gather(first_task, second_task)


@pytest.mark.asyncio
async def test_repeat_approval_is_business_idempotent(
    session_maker,
    make_user,
):
    requester = await make_user()
    first_admin = await make_user(is_admin=True)
    second_admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A repeat {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )

    try:
        async with session_maker() as session:
            await courses_service.approve_course_request(
                request_id=request_id,
                decision=SubmissionDecision(note="established note"),
                current_user=UserRoles(user_id=first_admin.id, is_admin=True),
                db=session,
            )
        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        established = submissions[0]
        established_shape = (
            established.status,
            established.reviewer_id,
            established.review_note,
            established.reviewed_at,
            established.created_course_id,
        )

        async with session_maker() as session:
            repeated = await courses_service.approve_course_request(
                request_id=request_id,
                decision=SubmissionDecision(note="must not replace"),
                current_user=UserRoles(user_id=second_admin.id, is_admin=True),
                db=session,
            )

        submissions, repeated_courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        repeated_shape = (
            submissions[0].status,
            submissions[0].reviewer_id,
            submissions[0].review_note,
            submissions[0].reviewed_at,
            submissions[0].created_course_id,
        )
        assert repeated.id == request_id
        assert repeated_shape == established_shape
        assert len(courses) == len(repeated_courses) == 1
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
async def test_concurrent_same_request_approval_converges(
    monkeypatch,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A same request {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )

    try:
        mutex_used, results = await _run_serialized_approvals(
            monkeypatch,
            session_maker,
            request_ids=(request_id, request_id),
            admin_id=admin.id,
        )
        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert mutex_used, "approval did not acquire the shared namespace mutex"
        assert results is not None
        assert {result.id for result in results} == {request_id}
        assert len(submissions) == 1
        assert submissions[0].status == SubmissionStatus.APPROVED
        assert len(courses) == 1
        assert submissions[0].created_course_id == courses[0].id
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
async def test_concurrent_distinct_requests_share_normalized_course(
    monkeypatch,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    marker = uuid.uuid4().hex
    first_name = f"D2A Shared ({marker})"
    second_name = f"  d2a shared（{marker}）  "
    assert normalize_course_search_text(first_name) == normalize_course_search_text(
        second_name
    )
    first_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=first_name,
        category=category,
    )
    second_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=second_name,
        category=category,
    )

    try:
        mutex_used, results = await _run_serialized_approvals(
            monkeypatch,
            session_maker,
            request_ids=(first_id, second_id),
            admin_id=admin.id,
        )
        submissions, courses = await _identity_snapshot(
            session_maker, name=first_name, category=category
        )
        assert mutex_used, "approval did not acquire the shared namespace mutex"
        assert results is not None
        assert {result.id for result in results} == {first_id, second_id}
        assert len(submissions) == 2
        assert {item.status for item in submissions} == {SubmissionStatus.APPROVED}
        assert len(courses) == 1
        assert {item.created_course_id for item in submissions} == {courses[0].id}
    finally:
        await _cleanup_identity(session_maker, name=first_name, category=category)


@pytest.mark.asyncio
async def test_approval_flush_failure_rolls_back_course_and_request(
    monkeypatch,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A approval rollback {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )
    caught = False

    try:
        async with session_maker() as session:
            original_flush = session.flush

            async def flush_then_fail(*args, **kwargs):
                await original_flush(*args, **kwargs)
                raise RuntimeError("D2A deterministic post-flush failure")

            monkeypatch.setattr(session, "flush", flush_then_fail)
            try:
                await courses_service.approve_course_request(
                    request_id=request_id,
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            except RuntimeError:
                caught = True

        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert caught
        assert len(courses) == 0
        assert len(submissions) == 1
        assert submissions[0].status == SubmissionStatus.PENDING
        assert submissions[0].reviewer_id is None
        assert submissions[0].reviewed_at is None
        assert submissions[0].review_note is None
        assert submissions[0].created_course_id is None
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
async def test_admin_direct_approval_flush_failure_is_atomic(
    monkeypatch,
    session_maker,
    make_user,
):
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A admin rollback {uuid.uuid4().hex}"
    caught = False

    try:
        async with session_maker() as session:
            original_flush = session.flush

            async def flush_then_fail(*args, **kwargs):
                await original_flush(*args, **kwargs)
                raise RuntimeError("D2A deterministic admin post-flush failure")

            monkeypatch.setattr(session, "flush", flush_then_fail)
            try:
                await courses_service.create_course_request(
                    course_data=CourseSubmissionCreate(name=name, category=category),
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            except RuntimeError:
                caught = True

        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert caught
        assert submissions == []
        assert courses == []
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
@pytest.mark.parametrize("category_state", ["inactive", "deleted"])
async def test_approval_revalidates_category_eligibility_without_mutation(
    session_maker,
    make_user,
    category_state,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A category blocked {category_state} {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )

    async with session_maker() as session:
        category_row = await session.scalar(
            select(courses_service.CourseCategoryConfig).where(
                courses_service.CourseCategoryConfig.key == category
            )
        )
        original_active = category_row.is_active
        original_deleted_at = category_row.deleted_at
        category_row.is_active = False
        if category_state == "deleted":
            category_row.deleted_at = datetime.now(UTC)
        await session.commit()

    try:
        async with session_maker() as session:
            with pytest.raises(HTTPException) as error:
                await courses_service.approve_course_request(
                    request_id=request_id,
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            assert error.value.status_code == 400
        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert len(courses) == 0
        assert submissions[0].status == SubmissionStatus.PENDING
        assert submissions[0].created_course_id is None
    finally:
        async with session_maker() as session:
            category_row = await session.scalar(
                select(courses_service.CourseCategoryConfig).where(
                    courses_service.CourseCategoryConfig.key == category
                )
            )
            category_row.is_active = original_active
            category_row.deleted_at = original_deleted_at
            await session.commit()
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
async def test_incoherent_approved_request_fails_closed(
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A incoherent approved {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )
    async with session_maker() as session:
        submission = await session.get(CourseSubmission, request_id)
        submission.status = SubmissionStatus.APPROVED
        submission.reviewer_id = admin.id
        submission.reviewed_at = datetime.now(UTC)
        await session.commit()

    try:
        async with session_maker() as session:
            with pytest.raises(HTTPException) as error:
                await courses_service.approve_course_request(
                    request_id=request_id,
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            assert error.value.status_code == 409
        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert courses == []
        assert submissions[0].status == SubmissionStatus.APPROVED
        assert submissions[0].created_course_id is None
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)


@pytest.mark.asyncio
async def test_rejected_request_remains_non_approvable(
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category = CourseCategory.FRESHMAN.value
    name = f"D2A rejected {uuid.uuid4().hex}"
    request_id = await _create_pending_request(
        session_maker,
        requester_id=requester.id,
        name=name,
        category=category,
    )
    async with session_maker() as session:
        submission = await session.get(CourseSubmission, request_id)
        submission.status = SubmissionStatus.REJECTED
        submission.reviewer_id = admin.id
        submission.reviewed_at = datetime.now(UTC)
        await session.commit()

    try:
        async with session_maker() as session:
            with pytest.raises(HTTPException) as error:
                await courses_service.approve_course_request(
                    request_id=request_id,
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            assert error.value.status_code == 400
        submissions, courses = await _identity_snapshot(
            session_maker, name=name, category=category
        )
        assert courses == []
        assert submissions[0].status == SubmissionStatus.REJECTED
        assert submissions[0].created_course_id is None
    finally:
        await _cleanup_identity(session_maker, name=name, category=category)
