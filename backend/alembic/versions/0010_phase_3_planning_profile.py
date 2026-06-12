"""phase 3 client planning profile (goals / objectives intake)

Revision ID: 0010_phase_3c
Revises: 0009_phase_3b
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_phase_3c"
down_revision: str | None = "0009_phase_3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["client_planning_profile"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "client_planning_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_objective", sa.String(length=32), nullable=False, server_default="no_preference"),
        sa.Column("retirement_target_year", sa.Integer(), nullable=True),
        sa.Column("liquidity_event", sa.String(length=24), nullable=False, server_default="none"),
        sa.Column("liquidity_event_year", sa.Integer(), nullable=True),
        sa.Column("liquidity_event_amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("charitable_intent", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("annual_giving_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("estate_priority", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("planned_relocation_state", sa.String(length=2), nullable=True),
        sa.Column("relocation_year", sa.Integer(), nullable=True),
        sa.Column("roth_preference", sa.String(length=20), nullable=False, server_default="no_preference"),
        sa.Column("risk_tolerance", sa.String(length=16), nullable=False, server_default="moderate"),
        sa.Column("cash_flow_sensitivity", sa.String(length=8), nullable=False, server_default="medium"),
        sa.Column("education_funding", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("business_succession", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_client_planning_profile_workspace_id", "client_planning_profile", ["workspace_id"]
    )
    op.create_index(
        "ix_client_planning_profile_client", "client_planning_profile", ["client_id"], unique=True
    )

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
    op.drop_table("client_planning_profile")
