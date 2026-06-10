"""phase 8 lifecycle

Revision ID: 0007_phase_8
Revises: 0006_phase_6
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase_8"
down_revision: str | None = "0006_phase_6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("client_tax_year", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("client_tax_year", sa.Column("pinned_bracket_config", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_tax_year", "pinned_bracket_config")
    op.drop_column("client_tax_year", "finalized_at")
