"""workspace member management and single-use invitations

Revision ID: 0022_workspace_member_invitations
Revises: 0021_personal_access_tokens
Create Date: 2026-11-03

The original workspace-membership policy intentionally exposed only the
current user's rows.  Member management needs two narrower capabilities:

* an active member may list the roster for a workspace they belong to;
* only an owner may insert, update, or delete another user's membership.

The policy functions are SECURITY DEFINER functions owned by the migration
role, so the runtime role never gets a general RLS bypass.  The API sets the
transaction-local ``app.membership_read`` flag only for the roster query; the
existing workspace switcher remains user-row scoped.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_workspace_member_invitations"
down_revision: str | None = "0021_personal_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "tax_planning_ops_app"
OWNER_ROLE = "tax_planning_ops_owner"


def _create_membership_policy_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_is_member(target_workspace uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM workspace_membership
                WHERE workspace_id = target_workspace
                  AND user_uc_uid = current_uc_uid()
                  AND deleted_at IS NULL
            )
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_is_owner(target_workspace uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM workspace_membership
                WHERE workspace_id = target_workspace
                  AND user_uc_uid = current_uc_uid()
                  AND role = 'owner'
                  AND deleted_at IS NULL
            )
        $$
        """
    )
    for name in ("workspace_membership_is_member", "workspace_membership_is_owner"):
        op.execute(f"REVOKE ALL ON FUNCTION {name}(uuid) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {name}(uuid) TO {RUNTIME_ROLE}")


def _restore_user_membership_policy() -> None:
    op.execute("DROP POLICY IF EXISTS workspace_membership_select ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_insert ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_update ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_delete ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_user_isolation ON workspace_membership")
    op.execute(
        """
        CREATE POLICY workspace_membership_user_isolation ON workspace_membership
        FOR ALL TO tax_planning_ops_app
        USING (user_uc_uid = current_uc_uid())
        WITH CHECK (user_uc_uid = current_uc_uid())
        """
    )


def upgrade() -> None:
    # Replace the one FOR ALL policy with command-specific policies.  The
    # read flag prevents the existing all-workspaces switcher query from
    # accidentally seeing other users' rows after roster reads are enabled.
    op.execute("DROP POLICY IF EXISTS workspace_membership_user_isolation ON workspace_membership")
    _create_membership_policy_functions()
    op.execute(
        """
        CREATE POLICY workspace_membership_select ON workspace_membership
        FOR SELECT TO tax_planning_ops_app
        USING (
            user_uc_uid = current_uc_uid()
            OR (
                current_setting('app.membership_read', true) = '1'
                AND workspace_membership_is_member(workspace_id)
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY workspace_membership_insert ON workspace_membership
        FOR INSERT TO tax_planning_ops_app
        WITH CHECK (
            user_uc_uid = current_uc_uid()
            OR workspace_membership_is_owner(workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY workspace_membership_update ON workspace_membership
        FOR UPDATE TO tax_planning_ops_app
        USING (
            user_uc_uid = current_uc_uid()
            OR workspace_membership_is_owner(workspace_id)
        )
        WITH CHECK (
            user_uc_uid = current_uc_uid()
            OR workspace_membership_is_owner(workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY workspace_membership_delete ON workspace_membership
        FOR DELETE TO tax_planning_ops_app
        USING (workspace_membership_is_owner(workspace_id))
        """
    )

    # Invitation rows are global lookup records, like personal_access_token:
    # acceptance happens before the invitee is a workspace member.  Only the
    # SHA-256 hash is stored; the raw token exists only in the create response.
    op.create_table(
        "workspace_invitation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_uc_uid", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitation_token_hash"),
    )
    op.create_index(
        "ix_workspace_invitation_workspace_id",
        "workspace_invitation",
        ["workspace_id"],
    )
    op.execute(f"ALTER TABLE workspace_invitation OWNER TO {OWNER_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON workspace_invitation TO {RUNTIME_ROLE}"
    )


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON workspace_invitation FROM {RUNTIME_ROLE}")
    op.drop_index("ix_workspace_invitation_workspace_id", table_name="workspace_invitation")
    op.drop_table("workspace_invitation")
    _restore_user_membership_policy()
    op.execute("DROP FUNCTION IF EXISTS workspace_membership_is_owner(uuid)")
    op.execute("DROP FUNCTION IF EXISTS workspace_membership_is_member(uuid)")
