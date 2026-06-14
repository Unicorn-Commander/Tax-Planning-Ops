"""phase 9 realized_outcome — next-year actuals vs plan per strategy

Revision ID: 0015_phase_9d
Revises: 0014_phase_9c
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_phase_9d"
down_revision: str | None = "0014_phase_9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["realized_outcome"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _apply_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} OWNER TO tax_planning_ops_owner")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO tax_planning_ops_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_isolation ON {table}
        FOR ALL TO tax_planning_ops_app
        USING (workspace_id = current_workspace_id())
        WITH CHECK (workspace_id = current_workspace_id())
        """
    )


def upgrade() -> None:
    op.create_table(
        "realized_outcome",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("realized_tax_year", sa.Integer(), nullable=False),
        sa.Column("planned_savings_cents", sa.BigInteger(), nullable=False),
        sa.Column("realized_savings_cents", sa.BigInteger(), nullable=True),
        sa.Column("realized_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("basis", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("source_detail", postgresql.JSONB(), nullable=True),
        sa.Column("reconciled_by", sa.String(length=255), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_strategy_id"], ["client_strategy.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_realized_outcome_workspace_id", "realized_outcome", ["workspace_id"])
    op.create_index(
        "ix_realized_outcome_tax_year", "realized_outcome", ["client_tax_year_id"]
    )
    op.create_index(
        "ix_realized_outcome_strategy", "realized_outcome", ["client_strategy_id"]
    )
    for table in WORKSPACE_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    op.drop_table("realized_outcome")
