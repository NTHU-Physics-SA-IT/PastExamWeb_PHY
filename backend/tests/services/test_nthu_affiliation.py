import pytest

from app.services.nthu_affiliation import (
    AffiliationStatus,
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
def test_invalid_missing_or_special_student_id_is_unknown(
    student_id: str | None,
) -> None:
    affiliation = parse_nthu_student_affiliation(student_id)

    assert affiliation.status is AffiliationStatus.UNKNOWN_SPECIAL
    assert affiliation.admission_year is None
    assert affiliation.college_code is None
    assert affiliation.department_code is None
    assert affiliation.program_code is None
