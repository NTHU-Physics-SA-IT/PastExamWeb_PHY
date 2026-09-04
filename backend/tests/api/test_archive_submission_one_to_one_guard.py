from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.services import archives as archives_service
from app.api.services import courses as courses_service
from app.api.services import trash as trash_service
from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveSubmissionEvent,
    ArchiveType,
    Course,
    CourseCategory,
    PersonalNotification,
    SubmissionStatus,
    UserRoles,
)
from app.services.archive_submission_links import (
    ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL,
    ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT,
    ArchiveSubmissionOneToOneInvariantError,
    archive_submission_link_conflict,
    ensure_archive_submission_link_available,
    is_archive_submission_link_unique_violation,
)
from app.services.archive_submission_review_revision import (
    compute_archive_submission_review_revision,
)
from app.utils.auth import get_current_user


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


def _snapshot(instance) -> dict:
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
    }


class _NamedUniqueViolation(Exception):
    sqlstate = "23505"
    constraint_name = ARCHIVE_SUBMISSION_LINK_UNIQUE_CONSTRAINT


async def _cleanup(
    session_maker,
    *,
    submission_ids: list[int],
    archive_ids: list[int],
    course_ids: list[int],
) -> None:
    async with session_maker() as session:
        discovered_archive_ids = {
            archive_id
            for archive_id in (
                await session.execute(
                    select(ArchiveSubmission.created_archive_id).where(
                        ArchiveSubmission.id.in_(submission_ids),
                        ArchiveSubmission.created_archive_id.is_not(None),
                    )
                )
            ).scalars()
            if archive_id is not None
        }
        all_archive_ids = set(archive_ids) | discovered_archive_ids
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
        if all_archive_ids:
            await session.execute(
                delete(Archive).where(Archive.id.in_(all_archive_ids))
            )
        await session.execute(delete(Course).where(Course.id.in_(course_ids)))
        await session.commit()


@pytest.mark.parametrize("failure_source", ["precheck", "named_constraint"])
@pytest.mark.asyncio
async def test_approval_link_conflict_rolls_back_all_side_effects(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
    failure_source: str,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-admin-{marker[:8]}", is_admin=True)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Approval Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"O2 Approval Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Professor",
            object_name=f"archive-submissions/o2-approval-{marker}.pdf",
            requester_id=requester.id,
            status=SubmissionStatus.PENDING,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)
        course_id = course.id
        submission_id = submission.id
        before = _snapshot(submission)

    async def conflict_guard(*_args, **_kwargs):
        if failure_source == "named_constraint":
            raise IntegrityError(
                "sanitized statement",
                {},
                _NamedUniqueViolation("sanitized database error"),
            )
        raise archive_submission_link_conflict()

    monkeypatch.setattr(
        archives_service,
        "ensure_archive_submission_link_available",
        conflict_guard,
        raising=False,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            f"/archives/admin/submissions/{submission_id}/approve",
            json={
                "expected_status": "pending",
                "expected_revision": compute_archive_submission_review_revision(
                    submission
                ),
            },
        )

        assert response.status_code == 409
        assert response.json() == {"detail": ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL}
        assert str(submission_id) not in response.text

        async with session_maker() as session:
            stored = await session.get(ArchiveSubmission, submission_id)
            archive_count = int(
                await session.scalar(
                    select(func.count(Archive.id)).where(
                        Archive.object_name
                        == f"archive-submissions/o2-approval-{marker}.pdf"
                    )
                )
                or 0
            )
            notification_count = int(
                await session.scalar(
                    select(func.count(PersonalNotification.id)).where(
                        PersonalNotification.source_type == "archive_submission",
                        PersonalNotification.source_id == submission_id,
                    )
                )
                or 0
            )
            assert _snapshot(stored) == before
            assert archive_count == 0
            assert notification_count == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_submission_restore_accepts_its_exact_retained_link(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-exact-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-exact-admin-{marker[:8]}", is_admin=True)
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Exact Restore Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Exact Restore Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Exact Professor",
            object_name=f"archive-submissions/o2-exact-{marker}.pdf",
            uploader_id=requester.id,
            deleted_at=deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
            delete_reason="admin deleted",
            owner_self_delete_consumed=True,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_id = submission.id

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/trash/restore",
            json={
                "item_type": "archive_submission",
                "item_id": submission_id,
            },
        )

        assert response.status_code == 200
        async with session_maker() as session:
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )
            stored_archive = await session.get(Archive, archive_id)
            assert stored_submission.created_archive_id == archive_id
            assert stored_submission.status == SubmissionStatus.APPROVED
            assert stored_submission.deleted_at is None
            assert stored_submission.previous_status is None
            assert stored_submission.owner_self_delete_consumed is True
            assert stored_archive.deleted_at is None
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission_id,
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
                            ArchiveSubmissionEvent.submission_id == submission_id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[archive_id],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_submission_restore_uses_no_metadata_fallback_for_null_link(
    client: AsyncClient,
    session_maker,
    make_user,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-null-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-null-admin-{marker[:8]}", is_admin=True)
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Null Restore Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Null Restore Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Null Professor",
            object_name=f"archive-submissions/o2-null-{marker}.pdf",
            uploader_id=requester.id,
            deleted_at=deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            created_archive_id=None,
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
            delete_reason="admin deleted",
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_id = submission.id

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/trash/restore",
            json={
                "item_type": "archive_submission",
                "item_id": submission_id,
            },
        )

        assert response.status_code == 200
        async with session_maker() as session:
            stored_submission = await session.get(
                ArchiveSubmission,
                submission_id,
            )
            stored_archive = await session.get(Archive, archive_id)
            assert stored_submission.created_archive_id is None
            assert stored_submission.status == SubmissionStatus.PENDING
            assert stored_submission.deleted_at is None
            assert stored_archive.deleted_at == deleted_at
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[archive_id],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_restore_link_conflict_is_409_without_lifecycle_mutation(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-restore-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-restore-admin-{marker[:8]}", is_admin=True)
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Restore Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Restore Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Restore Professor",
            object_name=f"archive-submissions/o2-restore-{marker}.pdf",
            uploader_id=requester.id,
            deleted_at=deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            created_archive_id=archive.id,
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
            delete_reason="admin deleted",
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_id = submission.id
        submission_before = _snapshot(submission)
        archive_before = _snapshot(archive)

    async def conflict_guard(*_args, **_kwargs):
        raise archive_submission_link_conflict()

    monkeypatch.setattr(
        trash_service,
        "ensure_archive_submission_link_available",
        conflict_guard,
        raising=False,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        response = await client.post(
            "/trash/restore",
            json={
                "item_type": "archive_submission",
                "item_id": submission_id,
            },
        )

        assert response.status_code == 409
        assert response.json() == {"detail": ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL}
        async with session_maker() as session:
            assert (
                _snapshot(await session.get(ArchiveSubmission, submission_id))
                == submission_before
            )
            assert _snapshot(await session.get(Archive, archive_id)) == archive_before
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[archive_id],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_submission_restore_rolls_back_status_provenance_and_archive(
    client: AsyncClient,
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-rollback-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-rollback-admin-{marker[:8]}", is_admin=True)
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Rollback Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Rollback Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Rollback Professor",
            object_name=f"archive-submissions/o2-rollback-{marker}.pdf",
            uploader_id=requester.id,
            deleted_at=deleted_at,
        )
        session.add(archive)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=archive.name,
            academic_year=archive.academic_year,
            archive_type=archive.archive_type,
            professor=archive.professor,
            object_name=archive.object_name,
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            previous_status=SubmissionStatus.APPROVED,
            created_archive_id=archive.id,
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
            delete_reason="admin deleted",
            owner_self_delete_consumed=True,
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_id = submission.id
        archive_before = _snapshot(archive)
        submission_before = _snapshot(submission)

    original_restore = trash_service.restore_archive_submission_group

    async def fail_after_restore(*args, **kwargs):
        await original_restore(*args, **kwargs)
        raise RuntimeError("injected restore failure")

    monkeypatch.setattr(
        trash_service,
        "restore_archive_submission_group",
        fail_after_restore,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        with pytest.raises(RuntimeError, match="injected restore failure"):
            await client.post(
                "/trash/restore",
                json={
                    "item_type": "archive_submission",
                    "item_id": submission_id,
                },
            )

        async with session_maker() as session:
            assert (
                _snapshot(await session.get(ArchiveSubmission, submission_id))
                == submission_before
            )
            assert _snapshot(await session.get(Archive, archive_id)) == archive_before
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_type == "archive_submission",
                            PersonalNotification.source_id == submission_id,
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
                            ArchiveSubmissionEvent.submission_id == submission_id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[archive_id],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_restore_internal_invariant_uses_generic_500(
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = uuid.uuid4().hex
    requester = await make_user(name=f"o2-anomaly-requester-{marker[:8]}")
    admin = await make_user(name=f"o2-anomaly-admin-{marker[:8]}", is_admin=True)
    deleted_at = datetime.now(UTC)
    async with session_maker() as session:
        course = Course(
            name=f"O2 Anomaly Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        submission = ArchiveSubmission(
            subject=course.name,
            category=CourseCategory.FRESHMAN.value,
            name=f"O2 Anomaly Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Anomaly Professor",
            object_name=f"archive-submissions/o2-anomaly-{marker}.pdf",
            requester_id=requester.id,
            status=SubmissionStatus.DELETED,
            deleted_at=deleted_at,
            deleted_by_id=admin.id,
            delete_reason="admin deleted",
        )
        session.add(submission)
        await session.commit()
        await session.refresh(course)
        await session.refresh(submission)
        course_id = course.id
        submission_id = submission.id
        submission_before = _snapshot(submission)

    async def invariant_guard(*_args, **_kwargs):
        raise ArchiveSubmissionOneToOneInvariantError("sanitized one-to-one invariant")

    monkeypatch.setattr(
        trash_service,
        "ensure_archive_submission_link_available",
        invariant_guard,
        raising=False,
    )
    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as non_raising_client:
            response = await non_raising_client.post(
                "/trash/restore",
                json={
                    "item_type": "archive_submission",
                    "item_id": submission_id,
                },
            )

        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert str(submission_id) not in response.text
        async with session_maker() as session:
            assert (
                _snapshot(await session.get(ArchiveSubmission, submission_id))
                == submission_before
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[submission_id],
            archive_ids=[],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_source_submission_multi_result_uses_generic_500(
    session_maker,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = uuid.uuid4().hex
    user = await make_user(name=f"o2-source-user-{marker[:8]}")
    async with session_maker() as session:
        course = Course(
            name=f"O2 Source Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Source Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Source Professor",
            object_name=f"archives/o2-source-{marker}.pdf",
            uploader_id=user.id,
        )
        session.add(archive)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        course_id = course.id
        archive_id = archive.id

    def invariant_source_rows(*_args, **_kwargs):
        raise ArchiveSubmissionOneToOneInvariantError("sanitized one-to-one invariant")

    monkeypatch.setattr(
        courses_service,
        "validate_archive_source_submission_rows",
        invariant_source_rows,
        raising=False,
    )

    async def current_user():
        return UserRoles(user_id=user.id, is_admin=True)

    app.dependency_overrides[get_current_user] = current_user
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as non_raising_client:
            response = await non_raising_client.get(f"/courses/{course_id}/archives")

        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert str(archive_id) not in response.text
        assert "source_submission_id" not in response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(
            session_maker,
            submission_ids=[],
            archive_ids=[archive_id],
            course_ids=[course_id],
        )


@pytest.mark.asyncio
async def test_postgresql_concurrent_archive_claim_has_one_success_and_one_409(
    session_maker,
    make_user,
) -> None:
    marker = uuid.uuid4().hex
    requester_a = await make_user(name=f"o2-race-a-{marker[:8]}")
    requester_b = await make_user(name=f"o2-race-b-{marker[:8]}")
    async with session_maker() as session:
        course = Course(
            name=f"O2 Race Course {marker}",
            category=CourseCategory.FRESHMAN,
        )
        session.add(course)
        await session.flush()
        archive = Archive(
            course_id=course.id,
            name=f"O2 Race Exam {marker}",
            academic_year=2026,
            archive_type=ArchiveType.FINAL,
            professor="O2 Race Professor",
            object_name=f"archives/o2-race-{marker}.pdf",
            uploader_id=requester_a.id,
        )
        session.add(archive)
        await session.flush()
        submissions = [
            ArchiveSubmission(
                subject=course.name,
                category=CourseCategory.FRESHMAN.value,
                name=f"O2 Race Submission {suffix} {marker}",
                academic_year=2026,
                archive_type=ArchiveType.FINAL,
                professor="O2 Race Professor",
                object_name=f"archive-submissions/o2-race-{suffix}-{marker}.pdf",
                requester_id=requester_id,
                status=SubmissionStatus.PENDING,
            )
            for suffix, requester_id in (
                ("a", requester_a.id),
                ("b", requester_b.id),
            )
        ]
        session.add_all(submissions)
        await session.commit()
        await session.refresh(course)
        await session.refresh(archive)
        for submission in submissions:
            await session.refresh(submission)
        course_id = course.id
        archive_id = archive.id
        submission_ids = [submission.id for submission in submissions]

    ready_count = 0
    ready_lock = asyncio.Lock()
    both_prechecked = asyncio.Event()
    release_writes = asyncio.Event()

    async def claim(submission_id: int) -> tuple[str, dict | None]:
        nonlocal ready_count
        async with session_maker() as session:
            submission = await session.get(ArchiveSubmission, submission_id)
            await ensure_archive_submission_link_available(
                session,
                submission_id=submission.id,
                current_archive_id=submission.created_archive_id,
                target_archive_id=archive_id,
                operation="approval",
            )
            async with ready_lock:
                ready_count += 1
                if ready_count == 2:
                    both_prechecked.set()
            await release_writes.wait()
            submission.created_archive_id = archive_id
            try:
                await session.flush()
                await session.commit()
                return "success", None
            except IntegrityError as error:
                await session.rollback()
                if is_archive_submission_link_unique_violation(error):
                    conflict = archive_submission_link_conflict()
                    return "conflict", conflict.detail
                raise

    first = asyncio.create_task(claim(submission_ids[0]))
    second = asyncio.create_task(claim(submission_ids[1]))
    try:
        await asyncio.wait_for(both_prechecked.wait(), timeout=5)
        release_writes.set()
        results = await asyncio.wait_for(
            asyncio.gather(first, second),
            timeout=10,
        )

        assert sorted(result[0] for result in results) == ["conflict", "success"]
        assert [result[1] for result in results if result[0] == "conflict"] == [
            ARCHIVE_SUBMISSION_LINK_CONFLICT_DETAIL
        ]

        async with session_maker() as session:
            linked_ids = list(
                (
                    await session.execute(
                        select(ArchiveSubmission.id).where(
                            ArchiveSubmission.created_archive_id == archive_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(linked_ids) == 1
            assert linked_ids[0] in submission_ids
            assert (
                int(
                    await session.scalar(
                        select(func.count(Course.id)).where(Course.id == course_id)
                    )
                    or 0
                )
                == 1
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(Archive.id)).where(Archive.id == archive_id)
                    )
                    or 0
                )
                == 1
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(PersonalNotification.id)).where(
                            PersonalNotification.source_id.in_(submission_ids)
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
                            ArchiveSubmissionEvent.submission_id.in_(submission_ids)
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await _cleanup(
            session_maker,
            submission_ids=submission_ids,
            archive_ids=[archive_id],
            course_ids=[course_id],
        )
