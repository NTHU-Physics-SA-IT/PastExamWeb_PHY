from app.services.course_lifecycle_locks import (
    CourseArchiveMembership,
    CourseLifecycleFingerprint,
    CourseLifecycleOperation,
    CourseSubmissionMembership,
    build_course_lifecycle_plan,
)
from app.services.archive_lifecycle_locks import (
    LifecycleResourceClass,
    LifecycleResourceRef,
)


def test_course_trash_plan_with_no_children_locks_only_course() -> None:
    plan = build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.TRASH,
        course_id=7,
        category_id=None,
        archive_membership=(),
        submission_membership=(),
        mutable_archive_ids=(),
        mutable_submission_ids=(),
        blocked_archive_ids=(),
        course_name_key="linear algebra",
        course_category_key="freshman",
    )

    assert plan.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 7),
    )
    assert isinstance(plan.fingerprint, CourseLifecycleFingerprint)


def test_course_trash_plan_is_parent_first_sorted_and_deduplicated() -> None:
    plan = build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.TRASH,
        course_id=7,
        category_id=None,
        archive_membership=(
            CourseArchiveMembership(12, 7, False),
            CourseArchiveMembership(3, 7, False),
            CourseArchiveMembership(12, 7, False),
        ),
        submission_membership=(
            CourseSubmissionMembership(20, 12, "approved", False, None),
            CourseSubmissionMembership(9, 3, "pending", False, None),
            CourseSubmissionMembership(20, 12, "approved", False, None),
        ),
        mutable_archive_ids=(12, 3, 12),
        mutable_submission_ids=(20, 9, 20),
        blocked_archive_ids=(),
        course_name_key="linear algebra",
        course_category_key="freshman",
    )

    assert plan.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 3),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 12),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 9),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 20),
    )
    assert plan.mutable_archive_ids == (3, 12)
    assert plan.mutable_submission_ids == (9, 20)


def test_course_plan_locks_extra_archive_parent_course_first() -> None:
    plan = build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.TRASH,
        course_id=7,
        category_id=None,
        archive_membership=(
            CourseArchiveMembership(3, 7, False),
            CourseArchiveMembership(12, 4, True),
        ),
        submission_membership=(
            CourseSubmissionMembership(20, 12, "approved", False, None),
        ),
        mutable_archive_ids=(3,),
        mutable_submission_ids=(20,),
        blocked_archive_ids=(),
        course_name_key="linear algebra",
        course_category_key="freshman",
    )

    assert plan.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 4),
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 3),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 12),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 20),
    )


def test_course_restore_plan_locks_category_before_course() -> None:
    plan = build_course_lifecycle_plan(
        operation=CourseLifecycleOperation.RESTORE,
        course_id=7,
        category_id=2,
        archive_membership=(CourseArchiveMembership(3, 7, True),),
        submission_membership=(
            CourseSubmissionMembership(
                9,
                3,
                "takedown",
                False,
                "course_trashed|previous_status=approved|course_id=7|archive_id=3",
            ),
        ),
        mutable_archive_ids=(3,),
        mutable_submission_ids=(9,),
        blocked_archive_ids=(),
        course_name_key="linear algebra",
        course_category_key="freshman",
        category_state=(2, "freshman", True, False),
    )

    assert plan.operation is CourseLifecycleOperation.RESTORE
    assert plan.lock_plan.resources == (
        LifecycleResourceRef(LifecycleResourceClass.COURSE_CATEGORY, 2),
        LifecycleResourceRef(LifecycleResourceClass.COURSE, 7),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE, 3),
        LifecycleResourceRef(LifecycleResourceClass.ARCHIVE_SUBMISSION, 9),
    )


def test_course_plan_fingerprint_is_stable_for_reverse_input_order() -> None:
    kwargs = {
        "operation": CourseLifecycleOperation.TRASH,
        "course_id": 7,
        "category_id": None,
        "mutable_archive_ids": (12, 3),
        "mutable_submission_ids": (20, 9),
        "blocked_archive_ids": (),
        "course_name_key": "linear algebra",
        "course_category_key": "freshman",
    }
    forward = build_course_lifecycle_plan(
        archive_membership=(
            CourseArchiveMembership(3, 7, False),
            CourseArchiveMembership(12, 7, False),
        ),
        submission_membership=(
            CourseSubmissionMembership(9, 3, "pending", False, None),
            CourseSubmissionMembership(20, 12, "approved", False, None),
        ),
        **kwargs,
    )
    reverse = build_course_lifecycle_plan(
        archive_membership=(
            CourseArchiveMembership(12, 7, False),
            CourseArchiveMembership(3, 7, False),
        ),
        submission_membership=(
            CourseSubmissionMembership(20, 12, "approved", False, None),
            CourseSubmissionMembership(9, 3, "pending", False, None),
        ),
        **kwargs,
    )

    assert reverse == forward
    assert reverse.fingerprint.token == forward.fingerprint.token
