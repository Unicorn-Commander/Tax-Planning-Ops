"""phase 0 foundation

Revision ID: 0001_phase_0
Revises:
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase_0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_TABLES = ["client"]


def upgrade() -> None:
    op.execute("CREATE ROLE tax_planning_ops_owner LOGIN BYPASSRLS")
    op.execute(
        """
        CREATE ROLE tax_planning_ops_app
        LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_workspace_id() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('app.current_workspace', true), '')::uuid $$
        """
    )

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("entitlement_flags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "client",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("filing_status_default", sa.String(length=16), nullable=False),
        sa.Column("primary_state", sa.String(length=2), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_client_workspace_id", "client", ["workspace_id"])

    op.execute("ALTER TABLE workspaces OWNER TO tax_planning_ops_owner")
    op.execute("ALTER TABLE client OWNER TO tax_planning_ops_owner")
    op.execute("GRANT USAGE ON SCHEMA public TO tax_planning_ops_app")
    op.execute("GRANT SELECT ON workspaces TO tax_planning_ops_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON client TO tax_planning_ops_app")

    for table in WORKSPACE_TABLES:
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
    for table in reversed(WORKSPACE_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_client_workspace_id", table_name="client")
    op.drop_table("client")
    op.drop_table("workspaces")
    op.execute("DROP FUNCTION IF EXISTS current_workspace_id()")
    op.execute("DROP ROLE IF EXISTS tax_planning_ops_app")
    op.execute("DROP ROLE IF EXISTS tax_planning_ops_owner")
