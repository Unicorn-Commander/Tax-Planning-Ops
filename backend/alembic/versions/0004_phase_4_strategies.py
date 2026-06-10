"""phase 4 strategies

Revision ID: 0004_phase_4
Revises: 0003_phase_2
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase_4"
down_revision: str | None = "0003_phase_2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["strategy_library", "client_strategy"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "strategy_library",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("client_facing_copy", sa.Text(), nullable=False),
        sa.Column("default_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("savings_method", sa.String(length=32), nullable=False),
        sa.Column("custom_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("applicability_rules", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("statutory_cap_cents", sa.BigInteger(), nullable=True),
        sa.Column("citation", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_year_applicability", postgresql.JSONB(), nullable=False, server_default="[]"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_strategy_library_workspace_id", "strategy_library", ["workspace_id"])

    op.create_table(
        "client_strategy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("disposition", sa.String(length=24), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("effective_rate_used", sa.Numeric(8, 6), nullable=False),
        sa.Column("estimated_savings_cents", sa.BigInteger(), nullable=False),
        sa.Column("status_flag", sa.String(length=32), nullable=False),
        sa.Column("advisor_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_library.id"]),
    )
    op.create_index("ix_client_strategy_workspace_id", "client_strategy", ["workspace_id"])

    for table in WORKSPACE_TABLES:
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


def downgrade() -> None:
    op.drop_table("client_strategy")
    op.drop_table("strategy_library")
