"""phase 3 c-corp fields on business_entity

Revision ID: 0009_phase_3b
Revises: 0008_phase_3
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_phase_3b"
down_revision: str | None = "0008_phase_3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "business_entity",
        sa.Column("dividends_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "business_entity",
        sa.Column("nol_available_cents", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("business_entity", "nol_available_cents")
    op.drop_column("business_entity", "dividends_cents")
