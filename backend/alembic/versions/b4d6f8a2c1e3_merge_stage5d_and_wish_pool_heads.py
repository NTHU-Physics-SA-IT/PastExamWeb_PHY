"""merge Stage 5D and Wish Pool migration heads

Revision ID: b4d6f8a2c1e3
Revises: a9c2e5f7b1d4, a9c4e7b2d6f1
Create Date: 2026-08-19 02:00:00.000000
"""

from collections.abc import Sequence

revision: str = "b4d6f8a2c1e3"
down_revision: str | Sequence[str] | None = (
    "a9c2e5f7b1d4",
    "a9c4e7b2d6f1",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the already-applied sibling histories without additional DDL."""


def downgrade() -> None:
    """Restore the two sibling heads without changing schema or data."""
