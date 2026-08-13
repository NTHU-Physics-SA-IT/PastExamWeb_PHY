import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveType,
    Course,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user

_DEFAULT_REQUESTED_COURSE_NAME = object()


def _override_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=True)

    return _get_current_user


def _override_non_admin(user_id: int):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=False)

    return _get_current_user


class ComparisonFixture:
    def __init__(self, session_maker):
        self.session_maker = session_maker
        self.submission_ids: list[int] = []
        self.archive_ids: list[int] = []
        self.course_ids: list[int] = []

    async def create_course(self, *, name: str, category: str) -> Course:
        async with self.session_maker() as session:
            course = Course(name=name, category=category)
            session.add(course)
            await session.commit()
            await session.refresh(course)
        self.course_ids.append(course.id)
        return course

    async def create_archive(
        self,
        *,
        course_id: int,
        requester_id: int,
        marker: str,
        name: str,
        academic_year: int,
        professor: str,
    ) -> Archive:
        async with self.session_maker() as session:
            archive = Archive(
                course_id=course_id,
                name=name,
                academic_year=academic_year,
                archive_type=ArchiveType.FINAL,
                professor=professor,
                object_name=f"archive-submissions/comparison-archive-{marker}.pdf",
                uploader_id=requester_id,
            )
            session.add(archive)
            await session.commit()
            await session.refresh(archive)
        self.archive_ids.append(archive.id)
        return archive

    async def create_submission(
        self,
        *,
        requester_id: int,
        marker: str,
        status: SubmissionStatus,
        course_name: str,
        category: str,
        name: str,
        academic_year: int,
        professor: str,
        created_archive_id: int | None = None,
        requested_course_name: str | None | object = _DEFAULT_REQUESTED_COURSE_NAME,
    ) -> ArchiveSubmission:
        async with self.session_maker() as session:
            resolved_requested_course_name = (
                course_name
                if requested_course_name is _DEFAULT_REQUESTED_COURSE_NAME
                else requested_course_name
            )
            submission = ArchiveSubmission(
                subject=course_name,
                category=category,
                name=name,
                academic_year=academic_year,
                archive_type=ArchiveType.FINAL,
                professor=professor,
                object_name=f"archive-submissions/comparison-submission-{marker}.pdf",
                requested_course_name=resolved_requested_course_name,
                requested_category_key=category,
                requester_id=requester_id,
                status=status,
                created_archive_id=created_archive_id,
                deleted_at=(
                    datetime.now(UTC)
                    if status == SubmissionStatus.DELETED
                    else None
                ),
            )
            session.add(submission)
            await session.commit()
            await session.refresh(submission)
        self.submission_ids.append(submission.id)
        return submission

    async def cleanup(self) -> None:
        async with self.session_maker() as session:
            if self.submission_ids:
                await session.execute(
                    delete(ArchiveSubmission).where(
                        ArchiveSubmission.id.in_(self.submission_ids)
                    )
                )
            if self.archive_ids:
                await session.execute(
                    delete(Archive).where(Archive.id.in_(self.archive_ids))
                )
            if self.course_ids:
                await session.execute(
                    delete(Course).where(Course.id.in_(self.course_ids))
                )
            await session.commit()


@pytest_asyncio.fixture
async def comparison_fixture(session_maker, make_user):
    fixture = ComparisonFixture(session_maker)
    yield fixture
    await fixture.cleanup()


async def _list_comparisons(client, *, submission_id: int, admin_id: int):
    app.dependency_overrides[get_current_user] = _override_admin(admin_id)
    try:
        response = await client.get(
            f"/archives/admin/submissions/{submission_id}/comparisons"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_pending_submission_includes_approved_candidate_from_same_requester(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-requester-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    course = await comparison_fixture.create_course(
        name=course_name,
        category=category,
    )
    candidate_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=requester.id,
        marker=f"approved-{unique}",
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-pending-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    candidate = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"candidate-approved-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        created_archive_id=candidate_archive.id,
    )

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in rows] == [candidate.id]
    assert rows[0]["status"] == SubmissionStatus.APPROVED.value
    assert rows[0]["can_takedown"] is True
    assert current.id not in {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_approved_submission_includes_pending_candidate_from_same_requester(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-requester-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    course = await comparison_fixture.create_course(
        name=course_name,
        category=category,
    )
    current_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=requester.id,
        marker=f"current-approved-{unique}",
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-approved-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        created_archive_id=current_archive.id,
    )
    candidate = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"candidate-pending-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in rows] == [candidate.id]
    assert rows[0]["status"] == SubmissionStatus.PENDING.value
    assert rows[0]["can_takedown"] is True
    assert current.id not in {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_subject_only_pending_and_approved_match_bidirectionally(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-requester-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    course = await comparison_fixture.create_course(
        name=course_name,
        category=category,
    )
    approved_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=requester.id,
        marker=f"approved-{unique}",
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    pending = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"pending-subject-only-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        requested_course_name=None,
    )
    approved = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"approved-subject-only-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        created_archive_id=approved_archive.id,
        requested_course_name=None,
    )

    pending_rows = await _list_comparisons(
        client,
        submission_id=pending.id,
        admin_id=admin.id,
    )
    approved_rows = await _list_comparisons(
        client,
        submission_id=approved.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in pending_rows] == [approved.id]
    assert [row["id"] for row in approved_rows] == [pending.id]
    assert pending.id not in {row["id"] for row in pending_rows}
    assert approved.id not in {row["id"] for row in approved_rows}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_course_name",
    [None, "", "   ", "\u3000\t"],
    ids=["null", "empty", "spaces", "unicode-whitespace"],
)
async def test_first_nonblank_course_identity_matches_bidirectionally(
    client,
    comparison_fixture,
    make_user,
    requested_course_name,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"愛情必修課 {unique}"
    exam_name = f"final {unique}"
    professor = f"牛逼 {unique}"
    requester = await make_user(name=f"comparison-requester-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    course = await comparison_fixture.create_course(
        name=course_name,
        category=category,
    )
    linked_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=requester.id,
        marker=f"linked-{unique}",
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    subject_only = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"subject-only-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        requested_course_name=requested_course_name,
    )
    linked_requested = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"linked-requested-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        created_archive_id=linked_archive.id,
    )

    subject_only_rows = await _list_comparisons(
        client,
        submission_id=subject_only.id,
        admin_id=admin.id,
    )
    linked_rows = await _list_comparisons(
        client,
        submission_id=linked_requested.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in subject_only_rows] == [linked_requested.id]
    assert [row["id"] for row in linked_rows] == [subject_only.id]
    assert subject_only.id not in {row["id"] for row in subject_only_rows}
    assert linked_requested.id not in {row["id"] for row in linked_rows}


@pytest.mark.asyncio
async def test_same_existing_course_id_matches_without_snapshot_fallback(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"控制課程 {unique}"
    exam_name = f"midterm1 {unique}"
    professor = f"控制教師 {unique}"
    requester = await make_user(name=f"comparison-current-{unique[:8]}")
    candidate_owner = await make_user(name=f"comparison-owner-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    course = await comparison_fixture.create_course(
        name=course_name,
        category=category,
    )
    current_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=requester.id,
        marker=f"current-{unique}",
        name=exam_name,
        academic_year=1121,
        professor=professor,
    )
    candidate_archive = await comparison_fixture.create_archive(
        course_id=course.id,
        requester_id=candidate_owner.id,
        marker=f"candidate-{unique}",
        name=exam_name,
        academic_year=1121,
        professor=professor,
    )
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=f"stale current snapshot {unique}",
        category=category,
        name=exam_name,
        academic_year=1121,
        professor=professor,
        created_archive_id=current_archive.id,
        requested_course_name=None,
    )
    candidate = await comparison_fixture.create_submission(
        requester_id=candidate_owner.id,
        marker=f"candidate-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=f"stale candidate snapshot {unique}",
        category=category,
        name=exam_name,
        academic_year=1121,
        professor=professor,
        created_archive_id=candidate_archive.id,
        requested_course_name=None,
    )

    current_rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )
    candidate_rows = await _list_comparisons(
        client,
        submission_id=candidate.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in current_rows] == [candidate.id]
    assert [row["id"] for row in candidate_rows] == [current.id]


@pytest.mark.asyncio
async def test_subject_fallback_does_not_match_a_different_course(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"正確課程 {unique}"
    exam_name = f"final {unique}"
    professor = f"教師 {unique}"
    requester = await make_user(name=f"comparison-current-{unique[:8]}")
    candidate_owner = await make_user(name=f"comparison-owner-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        requested_course_name=None,
    )
    candidate = await comparison_fixture.create_submission(
        requester_id=candidate_owner.id,
        marker=f"different-course-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=f"不同課程 {unique}",
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
        requested_course_name=None,
    )

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )

    assert rows == []
    assert candidate.id not in {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_comparisons_include_takedown_and_exclude_rejected_and_deleted(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-current-{unique[:8]}")
    candidate_owner = await make_user(name=f"comparison-owner-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    takedown = await comparison_fixture.create_submission(
        requester_id=candidate_owner.id,
        marker=f"takedown-{unique}",
        status=SubmissionStatus.TAKEDOWN,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    rejected = await comparison_fixture.create_submission(
        requester_id=candidate_owner.id,
        marker=f"rejected-{unique}",
        status=SubmissionStatus.REJECTED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    deleted = await comparison_fixture.create_submission(
        requester_id=candidate_owner.id,
        marker=f"deleted-{unique}",
        status=SubmissionStatus.DELETED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )

    assert [row["id"] for row in rows] == [takedown.id]
    assert rows[0]["can_takedown"] is False
    assert rejected.id not in {row["id"] for row in rows}
    assert deleted.id not in {row["id"] for row in rows}


@pytest.mark.asyncio
async def test_comparisons_exclude_only_current_and_preserve_distinct_submissions(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-requester-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    candidate_pending = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"candidate-pending-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    candidate_approved = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"candidate-approved-{unique}",
        status=SubmissionStatus.APPROVED,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )
    result_ids = [row["id"] for row in rows]

    assert result_ids == [candidate_pending.id, candidate_approved.id]
    assert len(result_ids) == 2
    assert current.id not in result_ids


@pytest.mark.asyncio
async def test_comparisons_exclude_each_nonmatching_dimension(
    client,
    comparison_fixture,
    make_user,
):
    unique = uuid.uuid4().hex
    category = f"comparison-{unique[:12]}"
    course_name = f"普通物理（一） {unique}"
    exam_name = f"final {unique}"
    professor = f"王進維 {unique}"
    requester = await make_user(name=f"comparison-current-{unique[:8]}")
    candidate_owner = await make_user(name=f"comparison-owner-{unique[:8]}")
    admin = await make_user(name=f"comparison-admin-{unique[:8]}", is_admin=True)
    current = await comparison_fixture.create_submission(
        requester_id=requester.id,
        marker=f"current-{unique}",
        status=SubmissionStatus.PENDING,
        course_name=course_name,
        category=category,
        name=exam_name,
        academic_year=1131,
        professor=professor,
    )
    candidates = [
        await comparison_fixture.create_submission(
            requester_id=candidate_owner.id,
            marker=f"different-course-{unique}",
            status=SubmissionStatus.PENDING,
            course_name=f"{course_name} different",
            category=category,
            name=exam_name,
            academic_year=1131,
            professor=professor,
        ),
        await comparison_fixture.create_submission(
            requester_id=candidate_owner.id,
            marker=f"different-professor-{unique}",
            status=SubmissionStatus.PENDING,
            course_name=course_name,
            category=category,
            name=exam_name,
            academic_year=1131,
            professor=f"{professor} different",
        ),
        await comparison_fixture.create_submission(
            requester_id=candidate_owner.id,
            marker=f"different-term-{unique}",
            status=SubmissionStatus.PENDING,
            course_name=course_name,
            category=category,
            name=exam_name,
            academic_year=1132,
            professor=professor,
        ),
        await comparison_fixture.create_submission(
            requester_id=candidate_owner.id,
            marker=f"different-exam-{unique}",
            status=SubmissionStatus.PENDING,
            course_name=course_name,
            category=category,
            name=f"{exam_name} different",
            academic_year=1131,
            professor=professor,
        ),
    ]

    rows = await _list_comparisons(
        client,
        submission_id=current.id,
        admin_id=admin.id,
    )

    assert rows == []
    assert not (
        {candidate.id for candidate in candidates} & {row["id"] for row in rows}
    )


@pytest.mark.asyncio
async def test_comparison_endpoint_preserves_authorization_and_not_found(
    client,
    make_user,
):
    user = await make_user(name=f"comparison-user-{uuid.uuid4().hex[:8]}")
    admin = await make_user(
        name=f"comparison-admin-{uuid.uuid4().hex[:8]}",
        is_admin=True,
    )

    app.dependency_overrides[get_current_user] = _override_non_admin(user.id)
    try:
        forbidden = await client.get("/archives/admin/submissions/999999/comparisons")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    app.dependency_overrides[get_current_user] = _override_admin(admin.id)
    try:
        missing = await client.get("/archives/admin/submissions/999999/comparisons")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert forbidden.status_code == 403
    assert missing.status_code == 404
