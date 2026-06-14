"""phase 10 workspace_membership — a user's owned/joined workspaces (multi-tenant)

Adds real multi-workspace support on top of the SSO: a user (Keycloak sub /
uc_uid) can belong to several named workspaces and switch between them. The
membership table is keyed by USER, not workspace, so its RLS is scoped to the
caller's uc_uid via a new ``current_uc_uid()`` function (mirroring
``current_workspace_id()``) reading the ``app.uc_uid`` GUC that
``bind_session_context`` already sets. The workspace name is denormalised onto
the row so the switcher can list a user's workspaces without a cross-RLS join.

Revision ID: 0017_phase_10a
Revises: 0016_phase_9e
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_phase_10a"
down_revision: str | None = "0016_phase_9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The user-scoped analogue of current_workspace_id(): reads the uc_uid GUC.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_uc_uid() RETURNS text
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('app.uc_uid', true), '') $$
        """
    )

    # Renaming a workspace needs UPDATE on the workspaces table; 0001 only granted
    # SELECT+INSERT. The RLS policy still scopes any UPDATE to the active workspace
    # (id = current_workspace_id()), so this only lets a user rename a workspace
    # they're currently bound to.
    op.execute("GRANT UPDATE ON workspaces TO tax_planning_ops_app")

    op.create_table(
        "workspace_membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_uc_uid", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalised so a user can list their workspaces without reading the
        # RLS-protected workspaces table (which is scoped to the active one).
        sa.Column("workspace_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_uc_uid", "workspace_id", name="uq_membership_user_workspace"),
    )
    op.create_index("ix_workspace_membership_user", "workspace_membership", ["user_uc_uid"])
    op.create_index("ix_workspace_membership_workspace", "workspace_membership", ["workspace_id"])

    table = "workspace_membership"
    op.execute(f"ALTER TABLE {table} OWNER TO tax_planning_ops_owner")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO tax_planning_ops_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    # User isolation: a caller only ever sees / writes their OWN memberships.
    op.execute(
        f"""
        CREATE POLICY {table}_user_isolation ON {table}
        FOR ALL TO tax_planning_ops_app
        USING (user_uc_uid = current_uc_uid())
        WITH CHECK (user_uc_uid = current_uc_uid())
        """
    )


def downgrade() -> None:
    op.drop_table("workspace_membership")
    op.execute("DROP FUNCTION IF EXISTS current_uc_uid()")
