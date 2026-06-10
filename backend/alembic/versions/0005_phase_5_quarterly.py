"""phase 5 quarterly

Revision ID: 0005_phase_5
Revises: 0004_phase_4
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase_5"
down_revision: str | None = "0004_phase_4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quarterly_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_income_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("period_withholding_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ytd_income_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("annualized_income_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("required_payment_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("safe_harbor_basis", sa.String(length=32), nullable=False),
        sa.Column("payment_made_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unpaid_rollforward_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="projected"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_quarterly_record_workspace_id", "quarterly_record", ["workspace_id"])
    op.create_index(
        "ix_quarterly_record_plan_quarter",
        "quarterly_record",
        ["client_tax_year_id", "quarter"],
        unique=True,
    )
    op.execute("ALTER TABLE quarterly_record OWNER TO tax_planning_ops_owner")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON quarterly_record TO tax_planning_ops_app")
    op.execute("ALTER TABLE quarterly_record ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE quarterly_record FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY quarterly_record_workspace_isolation ON quarterly_record
        FOR ALL TO tax_planning_ops_app
        USING (workspace_id = current_workspace_id())
        WITH CHECK (workspace_id = current_workspace_id())
        """
    )


def downgrade() -> None:
    op.drop_table("quarterly_record")
