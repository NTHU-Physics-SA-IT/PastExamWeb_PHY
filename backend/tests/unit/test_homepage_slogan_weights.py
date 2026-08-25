from app.models.models import HomepageSloganOccurrenceLevel
from app.services.homepage_slogans import HOMEPAGE_SLOGAN_WEIGHTS


def test_homepage_slogan_occurrence_levels_have_canonical_relative_weights() -> None:
    assert HOMEPAGE_SLOGAN_WEIGHTS == {
        HomepageSloganOccurrenceLevel.SUPER_RARE.value: 1,
        HomepageSloganOccurrenceLevel.RARE.value: 2,
        HomepageSloganOccurrenceLevel.NORMAL.value: 4,
        HomepageSloganOccurrenceLevel.FREQUENT.value: 8,
        HomepageSloganOccurrenceLevel.SUPER_FREQUENT.value: 16,
    }
