"""phase 9 implementation_task — 5-field contracts on accepted strategies

Revision ID: 0014_phase_9c
Revises: 0013_phase_9b
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_phase_9c"
down_revision: str | None = "0013_phase_9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["implementation_task"]


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
        "implementation_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False, server_default="advisor"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("statutory_key", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("evidence_blob_key", sa.Text(), nullable=True),
        sa.Column("evidence_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_strategy_id"], ["client_strategy.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_implementation_task_workspace_id", "implementation_task", ["workspace_id"]
    )
    op.create_index(
        "ix_implementation_task_tax_year", "implementation_task", ["client_tax_year_id"]
    )
    op.create_index(
        "ix_implementation_task_strategy", "implementation_task", ["client_strategy_id"]
    )
    for table in WORKSPACE_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    op.drop_table("implementation_task")
