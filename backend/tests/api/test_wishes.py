import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.main import app
from app.models.models import (
    Archive,
    ArchiveSubmission,
    ArchiveWish,
    ArchiveWishHeart,
    ArchiveWishReport,
    Course,
    SubmissionStatus,
    UserRoles,
)
from app.utils.auth import get_current_user


def _override_user(user_id: int, *, is_admin: bool = False):
    async def _get_current_user():
        return UserRoles(user_id=user_id, is_admin=is_admin)

    return _get_current_user


@pytest.mark.asyncio
async def test_wish_new_course_category_keeps_review_snapshot_and_requires_bilingual_data(
    client: AsyncClient,
    session_maker,
    make_user,
):
    user = await make_user()
    app.dependency_overrides[get_current_user] = _override_user(user.id)
    payload = {
        "title": "Need a new quantum information exam",
        "course_id": None,
        "subject": "量子資訊",
        "category": "quantum-information",
        "professor": "Professor Quantum",
        "academic_year": 1141,
        "archive_type": "final",
        "name": "final",
        "requested_course_name": "量子資訊",
        "requested_category_key": "quantum-information",
        "requested_category_name": "量子資訊",
        "requested_category_name_en": "Quantum Information",
        "requested_category_label": "量資",
        "requested_category_label_en": "QInfo",
    }
    try:
        missing_english = await client.post("/wishes", json=payload)
        assert missing_english.status_code == 422

        created = await client.post(
            "/wishes",
            json={**payload, "requested_course_name_en": "Quantum Information"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["course_id"] is None
        assert body["requested_course_name"] == "量子資訊"
        assert body["requested_course_name_en"] == "Quantum Information"
        assert body["requested_category_key"] == "quantum-information"

        async with session_maker() as session:
            course = await session.scalar(
                select(Course).where(Course.name == "量子資訊")
            )
            assert course is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(
                delete(ArchiveWish).where(ArchiveWish.creator_id == user.id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_wish_duplicate_heart_fulfillment_report_and_admin_delete(
    client: AsyncClient,
    session_maker,
    make_user,
):
    wisher = await make_user(name="wish-owner", nickname="許願者甲")
    reporter = await make_user(name="wish-reporter", nickname="回報者乙")
    admin = await make_user(is_admin=True)
    async with session_maker() as session:
        course = Course(name="Wish Test Course", category="required")
        session.add(course)
        await session.commit()
        await session.refresh(course)

    payload = {
        "title": "Need midterm one",
        "course_id": course.id,
        "subject": course.name,
        "category": course.category,
        "professor": "Professor Wish",
        "academic_year": 1141,
        "archive_type": "midterm",
        "name": "midterm1",
    }
    try:
        app.dependency_overrides[get_current_user] = _override_user(wisher.id)
        created = await client.post("/wishes", json=payload)
        assert created.status_code == 201
        wish_id = created.json()["id"]
        assert created.json()["category"] == course.category.value
        assert created.json()["heart_count"] == 0
        duplicate = await client.post("/wishes", json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["existing_wish_id"] == wish_id

        hearted = await client.post(f"/wishes/{wish_id}/heart")
        assert hearted.json() == {"hearted": True, "heart_count": 1}
        unhearted = await client.post(f"/wishes/{wish_id}/heart")
        assert unhearted.json() == {"hearted": False, "heart_count": 0}

        listed = await client.get("/wishes", params={"limit": 100})
        assert listed.status_code == 200
        assert listed.json()["items"][0]["fulfilled"] is False

        async with session_maker() as session:
            archive = Archive(
                course_id=course.id,
                name="midterm1",
                professor="Professor Wish",
                archive_type="midterm",
                academic_year=1141,
                object_name="wish-test.pdf",
                uploader_id=admin.id,
            )
            session.add(archive)
            await session.commit()
            await session.refresh(archive)
            submission = ArchiveSubmission(
                subject=course.name,
                category=course.category,
                name="midterm1",
                academic_year=1141,
                archive_type="midterm",
                professor="Professor Wish",
                object_name="wish-test.pdf",
                requester_id=wisher.id,
                created_archive_id=archive.id,
                status=SubmissionStatus.PENDING,
            )
            session.add(submission)
            await session.commit()
            await session.refresh(submission)
            submission_id = submission.id
        listed = await client.get("/wishes")
        assert listed.json()["items"][0]["fulfilled"] is False

        async with session_maker() as session:
            submission = await session.get(ArchiveSubmission, submission_id)
            submission.status = SubmissionStatus.REJECTED
            session.add(submission)
            await session.commit()
        listed = await client.get("/wishes")
        assert listed.json()["items"][0]["fulfilled"] is False

        async with session_maker() as session:
            submission = await session.get(ArchiveSubmission, submission_id)
            submission.status = SubmissionStatus.APPROVED
            session.add(submission)
            await session.commit()
        listed = await client.get("/wishes")
        assert listed.json()["items"][0]["fulfilled"] is True

        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        report = await client.post(
            f"/wishes/{wish_id}/reports",
            json={"report_reason": "misinformation", "custom_message": "Wrong target"},
        )
        assert report.status_code == 201
        first_report_id = report.json()["id"]

        app.dependency_overrides[get_current_user] = _override_user(reporter.id)
        second_payload = {**payload, "title": "Need final", "name": "final"}
        second_wish = await client.post("/wishes", json=second_payload)
        assert second_wish.status_code == 201
        second_wish_id = second_wish.json()["id"]
        app.dependency_overrides[get_current_user] = _override_user(wisher.id)
        second_report = await client.post(
            f"/wishes/{second_wish_id}/reports",
            json={"report_reason": "spam_or_duplicate"},
        )
        assert second_report.status_code == 201
        second_report_id = second_report.json()["id"]

        app.dependency_overrides[get_current_user] = _override_user(
            admin.id, is_admin=True
        )
        reports = await client.get("/wishes/admin/reports")
        assert reports.status_code == 200
        report_item = next(
            item for item in reports.json()["items"] if item["wish_id"] == wish_id
        )
        assert report_item["wish_id"] == wish_id
        assert report_item["reporter_name"] == reporter.nickname
        assert report_item["wisher_name"] == wisher.nickname
        assert report_item["reporter_name"] != report_item["wisher_name"]
        ascending = await client.get(
            "/wishes/admin/reports",
            params={"sort_by": "created_at", "sort_order": "asc"},
        )
        descending = await client.get(
            "/wishes/admin/reports",
            params={"sort_by": "created_at", "sort_order": "desc"},
        )
        assert [item["id"] for item in ascending.json()["items"]] == [
            first_report_id,
            second_report_id,
        ]
        assert [item["id"] for item in descending.json()["items"]] == [
            second_report_id,
            first_report_id,
        ]
        for sort_by in ("created_at", "reason", "wisher", "wish_target", "status"):
            sorted_reports = await client.get(
                "/wishes/admin/reports",
                params={"sort_by": sort_by, "sort_order": "asc"},
            )
            assert sorted_reports.status_code == 200
        invalid_sort = await client.get(
            "/wishes/admin/reports", params={"sort_by": "actions"}
        )
        assert invalid_sort.status_code == 422
        assert (await client.delete(f"/wishes/{wish_id}")).status_code == 204
        assert (await client.delete(f"/wishes/{second_wish_id}")).status_code == 204
        assert (await client.get("/wishes")).json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        async with session_maker() as session:
            await session.execute(delete(ArchiveWishHeart))
            await session.execute(delete(ArchiveWishReport))
            await session.execute(delete(ArchiveWish))
            await session.execute(
                delete(ArchiveSubmission).where(ArchiveSubmission.requester_id == wisher.id)
            )
            await session.execute(delete(Archive).where(Archive.course_id == course.id))
            await session.execute(delete(Course).where(Course.id == course.id))
            await session.commit()
