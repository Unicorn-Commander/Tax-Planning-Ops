"""accounting-ops entity-level link — scope a linked entity's P&L to one AO entity

A business entity already carries ``accounting_ops_workspace_id`` (which AO
workspace's books to pull). But an AO workspace can hold SEVERAL entities (e.g.
Aaron's workspace holds Magic Unicorn Inc, the LLC, a JV, and a personal book),
so the workspace-level consolidated P&L would mix them. This adds an optional
``accounting_ops_entity_id`` so the sync can request a single AO entity's P&L
(``/reports/pl?entity_id=...``). Nullable: unset → the existing workspace-level
(consolidated) behaviour. Additive column on the already-RLS-scoped
``business_entity`` table — no policy/grant change needed.

Revision ID: 0018_acctops_entity
Revises: 0017_phase_10a
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_acctops_entity"
down_revision: str | None = "0017_phase_10a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "business_entity",
        sa.Column("accounting_ops_entity_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("business_entity", "accounting_ops_entity_id")
