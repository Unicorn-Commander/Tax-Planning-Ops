"""phase 3 business entity (multi-entity intake)

Revision ID: 0008_phase_3
Revises: 0007_phase_8
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_phase_3"
down_revision: str | None = "0007_phase_8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["business_entity"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "business_entity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("w2_wages_paid_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ubia_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("guaranteed_payments_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shareholder_w2_wages_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("is_general_partner", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_sstb", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_qbi", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_business_entity_workspace_id", "business_entity", ["workspace_id"])
    op.create_index("ix_business_entity_tax_year", "business_entity", ["client_tax_year_id"])

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
    op.drop_table("business_entity")
