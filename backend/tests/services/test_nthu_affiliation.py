import pytest

from app.services.nthu_affiliation import (
    AffiliationStatus,
    NthuAffiliationKind,
    NthuAffiliationSource,
    classify_nthu_affiliation,
    department_by_code,
    parse_nthu_student_affiliation,
)


def test_parses_standard_nine_digit_student_id() -> None:
    affiliation = parse_nthu_student_affiliation("112022123")

    assert affiliation.status is AffiliationStatus.PARSED
    assert affiliation.admission_year == "112"
    assert affiliation.college_code == "02"
    assert affiliation.department_code == "022"
    assert affiliation.program_code == "0221"


def test_physics_department_is_owned_by_the_official_catalog() -> None:
    department = department_by_code("022")

    assert department is not None
    assert department.name == "物理學系"
    assert department.college_code == "02"
    assert department.college_name == "理學院"


@pytest.mark.parametrize(
    "student_id", ["11202212", "1120221234", "11202A123", "special", "", None]
)
def test_invalid_missing_or_nonstandard_student_id_is_unresolved(
    student_id: str | None,
) -> None:
    affiliation = parse_nthu_student_affiliation(student_id)

    assert affiliation.status is AffiliationStatus.UNRESOLVED
    assert affiliation.admission_year is None
    assert affiliation.college_code is None
    assert affiliation.department_code is None
    assert affiliation.program_code is None


@pytest.mark.parametrize(
    ("userid", "kind", "label", "department_code", "source"),
    [
        (
            "112022123",
            NthuAffiliationKind.STANDARD_STUDENT,
            "一般學生",
            "022",
            NthuAffiliationSource.STUDENT_ID_PARSER,
        ),
        (
            "112025123",
            NthuAffiliationKind.STANDARD_STUDENT,
            "一般學生",
            "025",
            NthuAffiliationSource.STUDENT_ID_PARSER,
        ),
        (
            "X1106099",
            NthuAffiliationKind.UNRESOLVED,
            "未解析",
            None,
            NthuAffiliationSource.UNCLASSIFIED,
        ),
        (
            "W90001",
            NthuAffiliationKind.STAFF,
            "教職員",
            None,
            NthuAffiliationSource.HEURISTIC,
        ),
        (
            "W90002",
            NthuAffiliationKind.STAFF,
            "教職員",
            None,
            NthuAffiliationSource.HEURISTIC,
        ),
        (
            None,
            NthuAffiliationKind.UNRESOLVED,
            "未解析",
            None,
            NthuAffiliationSource.UNCLASSIFIED,
        ),
        (
            "arbitrary",
            NthuAffiliationKind.UNRESOLVED,
            "未解析",
            None,
            NthuAffiliationSource.UNCLASSIFIED,
        ),
    ],
)
def test_classifies_nthu_affiliation_for_admin_display(
    userid: str | None,
    kind: NthuAffiliationKind,
    label: str,
    department_code: str | None,
    source: NthuAffiliationSource,
) -> None:
    affiliation = classify_nthu_affiliation(userid)

    assert affiliation.kind is kind
    assert affiliation.label == label
    assert affiliation.department_code == department_code
    assert affiliation.classification_source is source


def test_unknown_catalog_department_is_not_a_standard_student() -> None:
    affiliation = classify_nthu_affiliation("112999123")

    assert affiliation.kind is NthuAffiliationKind.UNRESOLVED
    assert affiliation.department_code is None
