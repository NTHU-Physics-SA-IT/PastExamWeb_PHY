"""Canonical homepage-slogan occurrence levels and weighted selection."""

from sqlalchemy import case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.models import (
    HomepageSloganOccurrenceLevel,
    HomepageSloganStatus,
    HomepageSloganSubmission,
)

HOMEPAGE_SLOGAN_WEIGHTS = {
    HomepageSloganOccurrenceLevel.SUPER_RARE.value: 1,
    HomepageSloganOccurrenceLevel.RARE.value: 2,
    HomepageSloganOccurrenceLevel.NORMAL.value: 4,
    HomepageSloganOccurrenceLevel.FREQUENT.value: 8,
    HomepageSloganOccurrenceLevel.SUPER_FREQUENT.value: 16,
}


async def select_weighted_enabled_slogan(
    db: AsyncSession,
) -> HomepageSloganSubmission | None:
    """Select one enabled row without loading the complete candidate set."""
    weight = case(
        HOMEPAGE_SLOGAN_WEIGHTS,
        value=HomepageSloganSubmission.occurrence_level,
        else_=HOMEPAGE_SLOGAN_WEIGHTS[
            HomepageSloganOccurrenceLevel.NORMAL.value
        ],
    )
    weighted_score = -func.ln(func.greatest(func.random(), 0.000000000001)) / weight
    return (
        await db.execute(
            select(HomepageSloganSubmission)
            .where(
                HomepageSloganSubmission.status
                == HomepageSloganStatus.ENABLED.value
            )
            .order_by(weighted_score, HomepageSloganSubmission.id)
            .limit(1)
        )
    ).scalar_one_or_none()
