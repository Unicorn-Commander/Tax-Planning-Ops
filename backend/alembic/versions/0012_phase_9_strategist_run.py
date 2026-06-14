"""phase 9 strategist_run — persisted AI-strategist run (findings + draft memo)

Revision ID: 0012_phase_9a
Revises: 0011_phase_3d
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_phase_9a"
down_revision: str | None = "0011_phase_3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["strategist_run"]


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
        "strategist_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("findings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("memo_text", sa.Text(), nullable=True),
        sa.Column("current_total_tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_savings_identified_cents", sa.BigInteger(), nullable=False),
        sa.Column("marginal_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("objectives_summary", sa.Text(), nullable=True),
        sa.Column("trajectory", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("disclaimer", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_uc_uid", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_strategist_run_workspace_id", "strategist_run", ["workspace_id"])
    op.create_index(
        "ix_strategist_run_tax_year", "strategist_run", ["client_tax_year_id", "created_at"]
    )
    for table in WORKSPACE_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    op.drop_table("strategist_run")
