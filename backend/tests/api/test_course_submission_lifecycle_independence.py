from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete
from sqlmodel import select

from app.api.services import courses as courses_service
from app.api.services import trash as trash_service
from app.main import app
from app.models.models import (
    Course,
    CourseCategoryConfig,
    CourseSubmission,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_user(user):
    async def _get_current_user():
        return UserRoles(user_id=user.id, is_admin=user.is_admin)

    return _get_current_user


async def _create_context(
    session_maker,
    *,
    requester_id: int,
    status: SubmissionStatus = SubmissionStatus.PENDING,
    with_course: bool = False,
):
    suffix = uuid.uuid4().hex[:10]
    category = CourseCategoryConfig(
        key=f"d2b-{suffix}",
        name=f"D2B Category {suffix}",
    )
    async with session_maker() as session:
        session.add(category)
        await session.flush()
        course = None
        if with_course:
            course = Course(name=f"D2B Course {suffix}", category=category.key)
            session.add(course)
            await session.flush()
        submission = CourseSubmission(
            name=f"D2B Request {suffix}",
            category=category.key,
            status=status,
            requester_id=requester_id,
            created_course_id=course.id if course else None,
            reviewed_at=(
                datetime.now(UTC)
                if status in {SubmissionStatus.APPROVED, SubmissionStatus.REJECTED}
                else None
            ),
        )
        session.add(submission)
        await session.commit()
        await session.refresh(category)
        await session.refresh(submission)
        if course:
            await session.refresh(course)
        return category, course, submission


async def _cleanup_context(session_maker, *, category_id: int) -> None:
    async with session_maker() as session:
        category = await session.get(CourseCategoryConfig, category_id)
        if category is None:
            return
        await session.execute(
            delete(CourseSubmission).where(
                CourseSubmission.category == category.key,
            )
        )
        await session.execute(delete(Course).where(Course.category == category.key))
        await session.delete(category)
        await session.commit()


@pytest.mark.asyncio
async def test_soft_delete_pending_is_historical_and_hidden_from_active_lists(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, _, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        response = await client.delete(f"/courses/admin/requests/{submission.id}")
        assert response.status_code == 200

        async with session_maker() as session:
            stored = await session.get(CourseSubmission, submission.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status == SubmissionStatus.PENDING
            assert stored.deleted_at is not None
            assert stored.deleted_by_id == admin.id

        async with session_maker() as session:
            mine = await courses_service.list_my_course_requests(
                current_user=UserRoles(user_id=requester.id),
                db=session,
            )
            assert all(item.id != submission.id for item in mine)
            admin_rows = await courses_service.list_course_requests_for_admin(
                current_user=UserRoles(user_id=admin.id, is_admin=True),
                db=session,
            )
            assert all(item.id != submission.id for item in admin_rows)

        trash = await client.get("/trash", params={"item_type": "course_submission"})
        assert trash.status_code == 200
        assert any(item["id"] == submission.id for item in trash.json())
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_restore_exact_approved_state_without_parent_inference(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.APPROVED,
        with_course=True,
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        assert (
            await client.delete(f"/courses/admin/requests/{submission.id}")
        ).status_code == 200
        async with session_maker() as session:
            stored_course = await session.get(Course, course.id)
            assert stored_course is not None
            await session.delete(stored_course)
            await session.commit()

        response = await client.post(
            "/trash/restore",
            json={"item_type": "course_submission", "item_id": submission.id},
        )
        assert response.status_code == 200
        async with session_maker() as session:
            restored = await session.get(CourseSubmission, submission.id)
            assert restored.status == SubmissionStatus.APPROVED
            assert restored.previous_status is None
            assert restored.deleted_at is None
            assert restored.created_course_id is None
            assert (
                not (
                    await session.execute(
                        select(Course).where(Course.category == category.key)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_course_permanent_delete_detaches_but_preserves_submission(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.APPROVED,
        with_course=True,
    )
    async with session_maker() as session:
        stored_course = await session.get(Course, course.id)
        stored_course.deleted_at = datetime.now(UTC)
        stored_course.deleted_by_id = admin.id
        await session.commit()

    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        response = await client.delete(f"/trash/course/{course.id}")
        assert response.status_code == 200
        async with session_maker() as session:
            assert await session.get(Course, course.id) is None
            historical = await session.get(CourseSubmission, submission.id)
            assert historical is not None
            assert historical.status == SubmissionStatus.APPROVED
            assert historical.created_course_id is None

            with pytest.raises(HTTPException) as error:
                await courses_service.approve_course_request(
                    request_id=submission.id,
                    current_user=UserRoles(user_id=admin.id, is_admin=True),
                    db=session,
                )
            assert error.value.status_code == 409
            assert (
                not (
                    await session.execute(
                        select(Course).where(Course.category == category.key)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_permanent_delete_submission_never_deletes_course(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.APPROVED,
        with_course=True,
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        assert (
            await client.delete(f"/courses/admin/requests/{submission.id}")
        ).status_code == 200
        response = await client.delete(f"/trash/course_submission/{submission.id}")
        assert response.status_code == 200
        async with session_maker() as session:
            assert await session.get(CourseSubmission, submission.id) is None
            assert await session.get(Course, course.id) is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_category_blockers_include_only_active_pending_requests(
    session_maker,
    make_user,
):
    requester = await make_user()
    category, _, pending = await _create_context(
        session_maker,
        requester_id=requester.id,
    )
    try:
        async with session_maker() as session:
            for status_value in (
                SubmissionStatus.APPROVED,
                SubmissionStatus.REJECTED,
                SubmissionStatus.DELETED,
            ):
                session.add(
                    CourseSubmission(
                        name=f"D2B terminal {status_value.value} {uuid.uuid4().hex}",
                        category=category.key,
                        requester_id=requester.id,
                        status=status_value,
                    )
                )
            await session.commit()
            stored_category = await session.get(CourseCategoryConfig, category.id)
            blockers = await trash_service._get_active_category_submission_blockers(
                session, stored_category
            )
            course_submission_blockers = [
                item for item in blockers if item["type"] == "course_submission"
            ]
            assert [item["id"] for item in course_submission_blockers] == [pending.id]
    finally:
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_legacy_deleted_request_is_non_restorable_but_permanently_deletable(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, _, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.DELETED,
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        trash = await client.get("/trash", params={"item_type": "course_submission"})
        assert trash.status_code == 200
        item = next(item for item in trash.json() if item["id"] == submission.id)
        assert item["canRestore"] is False

        restore = await client.post(
            "/trash/restore",
            json={"item_type": "course_submission", "item_id": submission.id},
        )
        assert restore.status_code == 409
        async with session_maker() as session:
            stored = await session.get(CourseSubmission, submission.id)
            assert stored.status == SubmissionStatus.DELETED
            assert stored.previous_status is None

        deleted = await client.delete(f"/trash/course_submission/{submission.id}")
        assert deleted.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)


@pytest.mark.asyncio
async def test_course_soft_trash_restore_does_not_rewrite_submission(
    client: AsyncClient,
    session_maker,
    make_user,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    category, course, submission = await _create_context(
        session_maker,
        requester_id=requester.id,
        status=SubmissionStatus.APPROVED,
        with_course=True,
    )
    app.dependency_overrides[get_current_user] = _override_user(admin)
    try:
        assert (
            await client.delete(f"/courses/admin/courses/{course.id}")
        ).status_code == 200
        async with session_maker() as session:
            historical = await session.get(CourseSubmission, submission.id)
            assert historical.status == SubmissionStatus.APPROVED
            assert historical.deleted_at is None
            assert historical.created_course_id == course.id

        assert (
            await client.post(
                "/trash/restore",
                json={"item_type": "course", "item_id": course.id},
            )
        ).status_code == 200
        async with session_maker() as session:
            historical = await session.get(CourseSubmission, submission.id)
            assert historical.status == SubmissionStatus.APPROVED
            assert historical.deleted_at is None
            assert historical.created_course_id == course.id
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_context(session_maker, category_id=category.id)
