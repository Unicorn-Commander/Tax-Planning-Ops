"""phase 9 memo — versioned, signable advisor memorandum

Revision ID: 0013_phase_9b
Revises: 0012_phase_9a
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_phase_9b"
down_revision: str | None = "0012_phase_9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["memo"]


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
        "memo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_tax_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategist_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("signed_by", sa.String(length=255), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("audit_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supersedes_version", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_tax_year_id"], ["client_tax_year.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategist_run_id"], ["strategist_run.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_memo_workspace_id", "memo", ["workspace_id"])
    op.create_index(
        "ix_memo_tax_year_version", "memo", ["client_tax_year_id", "version"], unique=True
    )
    op.create_index("ix_memo_status", "memo", ["workspace_id", "status"])
    for table in WORKSPACE_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    op.drop_table("memo")
