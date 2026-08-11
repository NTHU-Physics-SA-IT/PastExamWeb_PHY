import pytest

from app.services.nthu_access_policy import (
    NthuAccessMode,
    NthuAccessPolicy,
    NthuAccessPolicyValidationError,
    NthuStaffAccess,
    ensure_profile_matches_access_policy,
    normalize_nthu_access_policy,
)
from app.services.nthu_oauth import NthuOAuthBusinessError, NthuProfile


def _profile(
    *,
    student_id: str | None = "112022123",
    inschool: bool = True,
) -> NthuProfile:
    return NthuProfile(
        uuid="stable-uuid",
        userid=student_id,
        name="NTHU Student",
        email="student@example.com",
        inschool=inschool,
    )


def test_all_nthu_allows_an_eligible_student_with_special_userid() -> None:
    policy = NthuAccessPolicy(mode=NthuAccessMode.ALL_NTHU)

    ensure_profile_matches_access_policy(_profile(student_id="special"), policy)


def test_selected_physics_department_allows_physics_student() -> None:
    policy = NthuAccessPolicy(
        mode=NthuAccessMode.SELECTED_DEPARTMENTS,
        allowed_department_codes=("022",),
    )

    ensure_profile_matches_access_policy(_profile(), policy)


def test_selected_staff_allowlist_allows_exact_provider_userid() -> None:
    policy = NthuAccessPolicy(
        mode=NthuAccessMode.SELECTED_DEPARTMENTS,
        staff_access=NthuStaffAccess.ALLOWLIST,
        allowed_staff_userids=("W90001",),
    )

    ensure_profile_matches_access_policy(_profile(student_id="W90001"), policy)


def test_selected_staff_allowlist_is_case_sensitive() -> None:
    policy = NthuAccessPolicy(
        mode=NthuAccessMode.SELECTED_DEPARTMENTS,
        staff_access=NthuStaffAccess.ALLOWLIST,
        allowed_staff_userids=("W90001",),
    )

    with pytest.raises(NthuOAuthBusinessError):
        ensure_profile_matches_access_policy(_profile(student_id="w90001"), policy)


@pytest.mark.parametrize(
    "student_id",
    ["112023123", "special", "", "11202A123", None],
)
def test_selected_department_denies_other_or_unknown_affiliation(
    student_id: str | None,
) -> None:
    policy = NthuAccessPolicy(
        mode=NthuAccessMode.SELECTED_DEPARTMENTS,
        allowed_department_codes=("022",),
    )

    with pytest.raises(NthuOAuthBusinessError) as exc_info:
        ensure_profile_matches_access_policy(_profile(student_id=student_id), policy)

    assert exc_info.value.code == "oauth_department_not_allowed"


def test_not_in_school_is_denied_before_department_policy() -> None:
    policy = NthuAccessPolicy(
        mode=NthuAccessMode.SELECTED_DEPARTMENTS,
        allowed_department_codes=("022",),
    )

    with pytest.raises(NthuOAuthBusinessError) as exc_info:
        ensure_profile_matches_access_policy(_profile(inschool=False), policy)

    assert exc_info.value.code == "oauth_not_in_school"


def test_policy_normalization_deduplicates_and_orders_codes() -> None:
    policy = normalize_nthu_access_policy(
        {
            "mode": "selected_departments",
            "allowed_department_codes": ["025", "022", "022"],
        }
    )

    assert policy.allowed_department_codes == ("022", "025")
    assert policy.staff_access is NthuStaffAccess.NONE
    assert policy.allowed_staff_userids == ()


def test_policy_normalization_supports_staff_only_and_trims_userids() -> None:
    policy = normalize_nthu_access_policy(
        {
            "mode": "selected_departments",
            "allowed_department_codes": [],
            "staff_access": "allowlist",
            "allowed_staff_userids": [" W90001 ", "W90002"],
        }
    )

    assert policy.staff_access is NthuStaffAccess.ALLOWLIST
    assert policy.allowed_staff_userids == ("W90001", "W90002")
    assert policy.as_storage_value() == {
        "mode": "selected_departments",
        "allowed_department_codes": [],
        "staff_access": "allowlist",
        "allowed_staff_userids": ["W90001", "W90002"],
    }


def test_all_nthu_canonicalizes_ignored_custom_fields() -> None:
    policy = normalize_nthu_access_policy(
        {
            "mode": "all_nthu",
            "allowed_department_codes": ["022"],
            "staff_access": "allowlist",
            "allowed_staff_userids": [],
        }
    )

    assert policy == NthuAccessPolicy(mode=NthuAccessMode.ALL_NTHU)


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "invalid", "allowed_department_codes": []},
        {"mode": "selected_departments", "allowed_department_codes": []},
        {"mode": "selected_departments", "allowed_department_codes": ["999"]},
        {
            "mode": "selected_departments",
            "allowed_department_codes": [],
            "staff_access": "allowlist",
            "allowed_staff_userids": [],
        },
        {
            "mode": "selected_departments",
            "allowed_department_codes": [],
            "staff_access": "allowlist",
            "allowed_staff_userids": ["W90001", "W90001"],
        },
        {
            "mode": "selected_departments",
            "allowed_department_codes": [],
            "staff_access": "allowlist",
            "allowed_staff_userids": ["bad\nvalue"],
        },
        {
            "mode": "selected_departments",
            "allowed_department_codes": [],
            "staff_access": "allowlist",
            "allowed_staff_userids": [123],
        },
    ],
)
def test_invalid_policy_is_rejected(payload: object) -> None:
    with pytest.raises(NthuAccessPolicyValidationError):
        normalize_nthu_access_policy(payload)
