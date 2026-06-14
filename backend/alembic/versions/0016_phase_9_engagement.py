"""phase 9 engagement — advisory fee per client (net-of-fee framing)

Revision ID: 0016_phase_9e
Revises: 0015_phase_9d
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_phase_9e"
down_revision: str | None = "0015_phase_9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["engagement"]


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
        "engagement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fee_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("fee_basis", sa.String(length=16), nullable=False, server_default="flat"),
        sa.Column("fee_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_engagement_workspace_id", "engagement", ["workspace_id"])
    op.create_index("ix_engagement_client", "engagement", ["client_id"], unique=True)
    for table in WORKSPACE_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    op.drop_table("engagement")
