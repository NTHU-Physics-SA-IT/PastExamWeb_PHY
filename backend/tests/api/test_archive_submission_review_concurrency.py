import asyncio
from dataclasses import dataclass
import uuid

import pytest
from sqlalchemy import delete, func
from sqlmodel import select

from app.api.services import archives as archives_service
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
from app.services import archive_submission_status as status_service
from app.utils.auth import get_current_user


@dataclass(frozen=True)
class ReviewRaceContext:
    submission_id: int
    category_key: str
    category_name: str
    course_name: str
    object_name: str


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


async def _create_race_context(
    session_maker,
    *,
    requester_id: int,
) -> ReviewRaceContext:
    marker = uuid.uuid4().hex
    category_key = f"race-{marker[:12]}"
    category_name = f"Race category {marker}"
    course_name = f"Race course {marker}"
    object_name = f"archive-submissions/review-race-{marker}.pdf"
    async with session_maker() as session:
        submission = ArchiveSubmission(
            subject=course_name,
            category=category_key,
            name=f"Race exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="Race Professor",
            has_answers=False,
            object_name=object_name,
            requested_course_name=course_name,
            requested_category_key=category_key,
            requested_category_name=category_name,
            requested_category_label=category_name,
            requested_category_icon="pi pi-book",
            requester_id=requester_id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(submission)

    return ReviewRaceContext(
        submission_id=submission.id,
        category_key=category_key,
        category_name=category_name,
        course_name=course_name,
        object_name=object_name,
    )


async def _race_snapshot(session_maker, context: ReviewRaceContext):
    async with session_maker() as session:
        submission = await session.get(ArchiveSubmission, context.submission_id)
        archive = (
            await session.get(Archive, submission.created_archive_id)
            if submission and submission.created_archive_id
            else None
        )
        notifications = list(
            (
                await session.execute(
                    select(PersonalNotification).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == context.submission_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            "submission": (
                submission.status,
                submission.reviewer_id,
                submission.reviewed_at,
                submission.review_note,
                submission.lifecycle_reason,
                submission.created_archive_id,
                submission.deleted_at,
                submission.restored_at,
            ),
            "archive": (
                None
                if archive is None
                else (
                    archive.id,
                    archive.course_id,
                    archive.name,
                    archive.academic_year,
                    archive.archive_type,
                    archive.professor,
                    archive.has_answers,
                    archive.object_name,
                    archive.uploader_id,
                    archive.deleted_at,
                    archive.updated_at,
                )
            ),
            "category_count": int(
                await session.scalar(
                    select(func.count(CourseCategoryConfig.id)).where(
                        CourseCategoryConfig.key == context.category_key
                    )
                )
                or 0
            ),
            "course_count": int(
                await session.scalar(
                    select(func.count(Course.id)).where(
                        Course.category == context.category_key,
                        Course.name == context.course_name,
                    )
                )
                or 0
            ),
            "archive_count": int(
                await session.scalar(
                    select(func.count(Archive.id)).where(
                        Archive.object_name == context.object_name
                    )
                )
                or 0
            ),
            "notifications": notifications,
            "event_count": int(
                await session.scalar(
                    select(func.count(ArchiveSubmissionEvent.id)).where(
                        ArchiveSubmissionEvent.submission_id == context.submission_id
                    )
                )
                or 0
            ),
        }


async def _cleanup_race_context(
    session_maker,
    context: ReviewRaceContext,
) -> None:
    async with session_maker() as session:
        await session.execute(
            delete(PersonalNotification).where(
                PersonalNotification.source_type == "archive_submission",
                PersonalNotification.source_id == context.submission_id,
            )
        )
        await session.execute(
            delete(ArchiveSubmissionEvent).where(
                ArchiveSubmissionEvent.submission_id == context.submission_id
            )
        )
        await session.execute(
            delete(ArchiveSubmission).where(
                ArchiveSubmission.id == context.submission_id
            )
        )
        await session.execute(
            delete(Archive).where(Archive.object_name == context.object_name)
        )
        await session.execute(
            delete(Course).where(
                Course.category == context.category_key,
                Course.name == context.course_name,
            )
        )
        await session.execute(
            delete(CourseCategoryConfig).where(
                CourseCategoryConfig.key == context.category_key
            )
        )
        await session.commit()


async def _run_deterministic_review_race(
    *,
    client,
    monkeypatch,
    submission_id: int,
    winner_action: str,
    loser_action: str,
):
    winner_at_commit_boundary = asyncio.Event()
    release_winner = asyncio.Event()
    loser_lock_attempted = asyncio.Event()
    notification_calls = 0
    lock_calls = 0
    request_session_ids: set[int] = set()
    attempted_session_ids: set[int] = set()

    original_lock = archive_lifecycle_locks.acquire_lifecycle_locks
    original_mutex = archive_lifecycle_locks.acquire_approval_namespace_mutex

    def observe_attempt(db) -> None:
        attempted_session_ids.add(id(db))
        if len(attempted_session_ids) == 2:
            loser_lock_attempted.set()

    async def observed_lock(db, plan):
        nonlocal lock_calls
        lock_calls += 1
        request_session_ids.add(id(db))
        observe_attempt(db)
        return await original_lock(db, plan)

    async def observed_mutex(db, **kwargs):
        observe_attempt(db)
        return await original_mutex(db, **kwargs)

    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_lifecycle_locks",
        observed_lock,
    )
    monkeypatch.setattr(
        archive_lifecycle_locks,
        "acquire_approval_namespace_mutex",
        observed_mutex,
    )

    notification_owner = (
        status_service if winner_action == "takedown" else archives_service
    )
    original_enqueue = notification_owner.enqueue_submission_status_notification

    async def enqueue_then_pause(db, submission, new_status):
        nonlocal notification_calls
        notification_calls += 1
        await original_enqueue(db, submission, new_status)
        await db.flush()
        winner_at_commit_boundary.set()
        await asyncio.wait_for(release_winner.wait(), timeout=5)

    monkeypatch.setattr(
        notification_owner,
        "enqueue_submission_status_notification",
        enqueue_then_pause,
    )

    winner_task = asyncio.create_task(
        client.post(
            f"/archives/admin/submissions/{submission_id}/{winner_action}",
            json={
                "note": f"winner:{winner_action}",
                "expected_status": "pending",
            },
        )
    )
    await asyncio.wait_for(winner_at_commit_boundary.wait(), timeout=5)

    loser_task = asyncio.create_task(
        client.post(
            f"/archives/admin/submissions/{submission_id}/{loser_action}",
            json={
                "note": f"loser:{loser_action}",
                "expected_status": "pending",
            },
        )
    )
    await asyncio.wait_for(loser_lock_attempted.wait(), timeout=5)
    assert not loser_task.done()

    release_winner.set()
    winner_response = await asyncio.wait_for(winner_task, timeout=5)
    loser_response = await asyncio.wait_for(loser_task, timeout=5)
    return {
        "winner_response": winner_response,
        "loser_response": loser_response,
        "notification_calls": notification_calls,
        "lock_calls": lock_calls,
        "request_session_ids": request_session_ids,
    }


@pytest.mark.parametrize(
    ("winner_action", "loser_action", "final_status"),
    [
        ("approve", "approve", SubmissionStatus.APPROVED),
        ("approve", "reject", SubmissionStatus.APPROVED),
        ("reject", "approve", SubmissionStatus.REJECTED),
        ("approve", "takedown", SubmissionStatus.APPROVED),
        ("takedown", "approve", SubmissionStatus.TAKEDOWN),
        ("reject", "takedown", SubmissionStatus.REJECTED),
        ("takedown", "reject", SubmissionStatus.TAKEDOWN),
    ],
)
@pytest.mark.asyncio
async def test_direct_review_races_are_deterministic_first_writer_wins(
    client,
    session_maker,
    make_user,
    monkeypatch,
    winner_action,
    loser_action,
    final_status,
):
    requester = await make_user()
    admin = await make_user(is_admin=True)
    context = await _create_race_context(
        session_maker,
        requester_id=requester.id,
    )
    before = await _race_snapshot(session_maker, context)
    assert before["category_count"] == 0
    assert before["course_count"] == 0
    assert before["archive_count"] == 0
    assert before["notifications"] == []
    assert before["event_count"] == 0

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        result = await _run_deterministic_review_race(
            client=client,
            monkeypatch=monkeypatch,
            submission_id=context.submission_id,
            winner_action=winner_action,
            loser_action=loser_action,
        )

        winner_response = result["winner_response"]
        loser_response = result["loser_response"]
        assert winner_response.status_code == 200
        assert winner_response.json()["changed"] is True
        assert winner_response.json()["status"] == final_status.value
        assert loser_response.status_code == 409
        assert loser_response.json()["detail"] == {
            "code": "archive_submission_stale_state",
            "message": "投稿狀態已變更，請重新載入後再操作。",
            "actual_status": final_status.value,
            "reload_required": True,
        }
        assert "changed" not in loser_response.json()
        assert result["notification_calls"] == 1
        assert result["lock_calls"] == (3 if winner_action == "approve" else 2)
        assert len(result["request_session_ids"]) == 2

        after = await _race_snapshot(session_maker, context)
        assert after["submission"][0] == final_status
        assert after["submission"][1] == admin.id
        assert after["submission"][2] is not None
        assert after["submission"][3] == f"winner:{winner_action}"
        assert after["submission"][4] is None
        assert after["submission"][6:] == (None, None)
        assert len(after["notifications"]) == 1
        assert after["event_count"] == 0

        expected_notification_type = {
            SubmissionStatus.APPROVED: "archive_submission_approved",
            SubmissionStatus.REJECTED: "archive_submission_rejected",
            SubmissionStatus.TAKEDOWN: "archive_submission_takedown",
        }[final_status]
        assert after["notifications"][0].notification_type == expected_notification_type

        if final_status == SubmissionStatus.APPROVED:
            assert after["category_count"] == 1
            assert after["course_count"] == 1
            assert after["archive_count"] == 1
            assert after["archive"] is not None
            assert after["submission"][5] == after["archive"][0]
            assert after["archive"][7] == context.object_name
        else:
            assert after["category_count"] == 0
            assert after["course_count"] == 0
            assert after["archive_count"] == 0
            assert after["archive"] is None
            assert after["submission"][5] is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup_race_context(session_maker, context)
