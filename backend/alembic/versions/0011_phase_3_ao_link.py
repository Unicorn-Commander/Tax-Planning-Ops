"""phase 3 accounting-ops link on business_entity

Revision ID: 0011_phase_3d
Revises: 0010_phase_3c
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_phase_3d"
down_revision: str | None = "0010_phase_3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "business_entity",
        sa.Column("accounting_ops_workspace_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("business_entity", "accounting_ops_workspace_id")
