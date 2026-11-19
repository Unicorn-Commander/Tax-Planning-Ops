"""Lock workspace_membership: app role keeps SELECT only, writes go through
SECURITY DEFINER functions.

0022 left two holes for the NOBYPASSRLS app role: the INSERT policy's
``user_uc_uid = current_uc_uid()`` clause let any session insert a membership
FOR ITSELF in ANY workspace with ANY role, and the UPDATE policy's same clause
let a user raise its OWN role to owner.  The header fallback in the auth
middleware then authorized off that forged row (see DEPS-346).

This migration closes both:

* REVOKE INSERT/UPDATE/DELETE on workspace_membership from the app role (and
  from PUBLIC, where they were implicit); no session may write the table at
  all, including raising its own role.
* Writes happen ONLY through SECURITY DEFINER functions (create_workspace,
  add_member, accept_invitation, remove_member).  Every function:
  - checks the ACTOR in the database against current_uc_uid() (a function
    never trusts its workspace/role arguments for authorization),
  - uses SET search_path = public, pg_temp (no user-writable objects resolve
    into the function's lookups),
  - REVOKE ALL FROM PUBLIC, GRANT EXECUTE to the app role.
* Definer writes run with the table owner's privileges (the functions are
  owned by the migration role), so they bypass the app role's revoked grants
  and its RLS entirely — authorization happens in the function body against
  current_uc_uid().

Downgrade restores the 0022 grant set (the original holes come back with it —
only run in controlled environments).

Revision ID: 0023_membership_lock
Revises: 0022_member_invitations
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_membership_lock"
down_revision: str | None = "0022_member_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "tax_planning_ops_app"

_FUNCTIONS = (
    "workspace_membership_create_workspace(text, text)",
    "workspace_membership_add_member(uuid, text, text)",
    "workspace_membership_accept_invitation(uuid, text)",
    "workspace_membership_remove_member(uuid, text, text)",
)


def _create_write_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_create_workspace(
            p_owner text, p_name text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_new_id uuid;
            v_uc_uid text := current_uc_uid();
        BEGIN
            IF p_owner IS DISTINCT FROM v_uc_uid
               OR v_uc_uid IS NULL OR p_name IS NULL OR p_name = '' THEN
                RAISE EXCEPTION 'workspace_membership_create_workspace: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            v_new_id := gen_random_uuid();
            INSERT INTO workspaces (id, name) VALUES (v_new_id, p_name);
            INSERT INTO workspace_membership
                (id, user_uc_uid, workspace_id, workspace_name, role)
            VALUES (gen_random_uuid(), v_uc_uid, v_new_id, p_name, 'owner');
            RETURN v_new_id;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_add_member(
            p_workspace uuid, p_member text, p_workspace_name text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
            v_row workspace_membership;
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_add_member: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM workspace_membership
                WHERE workspace_id = p_workspace
                  AND user_uc_uid = v_uc_uid
                  AND role = 'owner'
                  AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'workspace_membership_add_member: workspace owner required'
                    USING ERRCODE = '42501';
            END IF;
            SELECT * INTO v_row
            FROM workspace_membership
            WHERE workspace_id = p_workspace AND user_uc_uid = p_member;
            IF v_row IS NOT NULL THEN
                UPDATE workspace_membership
                SET deleted_at = NULL, workspace_name = p_workspace_name, role = 'member'
                WHERE id = v_row.id;
            ELSE
                INSERT INTO workspace_membership
                    (id, user_uc_uid, workspace_id, workspace_name, role)
                VALUES (gen_random_uuid(), p_member, p_workspace, p_workspace_name, 'member');
            END IF;
            RETURN (SELECT id FROM workspace_membership
                    WHERE workspace_id = p_workspace AND user_uc_uid = p_member);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_accept_invitation(
            p_workspace uuid, p_raw_token text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
            v_invitation workspace_invitation;
            v_row workspace_membership;
            v_token_hash text := encode(digest(p_raw_token, 'sha256'), 'hex');
            v_now timestamptz := now();
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_accept_invitation: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            SELECT * INTO v_invitation
            FROM workspace_invitation
            WHERE token_hash = v_token_hash
            FOR UPDATE;
            IF v_invitation IS NULL
               OR v_invitation.consumed_at IS NOT NULL
               OR v_invitation.expires_at <= v_now
               OR v_invitation.workspace_id IS DISTINCT FROM p_workspace THEN
                RAISE EXCEPTION 'invitation is invalid or expired'
                    USING ERRCODE = 'P0001';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM workspaces WHERE id = p_workspace) THEN
                RAISE EXCEPTION 'invitation is invalid or expired' USING ERRCODE = 'P0001';
            END IF;
            SELECT * INTO v_row
            FROM workspace_membership
            WHERE workspace_id = p_workspace AND user_uc_uid = v_uc_uid;
            IF v_row IS NOT NULL THEN
                UPDATE workspace_membership
                SET deleted_at = NULL,
                    workspace_name = (SELECT name FROM workspaces WHERE id = p_workspace),
                    role = COALESCE(v_invitation.role, 'member')
                WHERE id = v_row.id;
            ELSE
                INSERT INTO workspace_membership
                    (id, user_uc_uid, workspace_id, workspace_name, role)
                VALUES (
                    gen_random_uuid(),
                    v_uc_uid,
                    p_workspace,
                    (SELECT name FROM workspaces WHERE id = p_workspace),
                    COALESCE(v_invitation.role, 'member')
                );
            END IF;
            UPDATE workspace_invitation
            SET consumed_at = v_now
            WHERE id = v_invitation.id AND consumed_at IS NULL;
            RETURN (SELECT id FROM workspace_membership
                    WHERE workspace_id = p_workspace AND user_uc_uid = v_uc_uid);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_remove_member(
            p_workspace uuid, p_member text, p_role text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
            v_owner_count integer;
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_remove_member: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM workspace_membership
                WHERE workspace_id = p_workspace
                  AND user_uc_uid = v_uc_uid
                  AND role = 'owner'
                  AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'workspace_membership_remove_member: workspace owner required'
                    USING ERRCODE = '42501';
            END IF;
            SELECT count(*) INTO v_owner_count
            FROM workspace_membership
            WHERE workspace_id = p_workspace
              AND role = 'owner'
              AND deleted_at IS NULL;
            IF p_role = 'owner' AND v_owner_count <= 1 THEN
                RAISE EXCEPTION 'cannot remove the last owner' USING ERRCODE = 'P0001';
            END IF;
            UPDATE workspace_membership
            SET deleted_at = now()
            WHERE workspace_id = p_workspace AND user_uc_uid = p_member;
            RETURN (SELECT id FROM workspace_membership
                    WHERE workspace_id = p_workspace AND user_uc_uid = p_member);
        END
        $$
        """
    )
    for signature in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {RUNTIME_ROLE}")


def _lock_policies() -> None:
    op.execute("DROP POLICY IF EXISTS workspace_membership_select ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_insert ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_update ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_delete ON workspace_membership")
    # SELECT keeps the 0022 shape: own rows always; the roster (flag-gated) read
    # needs the member view. INSERT/UPDATE/DELETE get NO policy at all, so with
    # the revoked grants no session can write the table by any path. The
    # SECURITY DEFINER functions bypass RLS entirely (owner privileges).
    op.execute(
        f"""
        CREATE POLICY workspace_membership_select ON workspace_membership
        FOR SELECT TO {RUNTIME_ROLE}
        USING (
            user_uc_uid = current_uc_uid()
            OR (
                current_setting('app.membership_read', true) = '1'
                AND workspace_membership_is_member(workspace_id)
            )
        )
        """
    )


def upgrade() -> None:
    # 1. Revoke every write path from the app role (and PUBLIC).
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON workspace_membership FROM {RUNTIME_ROLE}")
    op.execute("REVOKE ALL ON workspace_membership FROM PUBLIC")
    # 2. Lock policies (SELECT stays user-scoped; definer clause for FORCE RLS).
    _lock_policies()
    # 3. The only write paths: SECURITY DEFINER functions.
    _create_write_functions()


def downgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME_ROLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute("DROP POLICY IF EXISTS workspace_membership_select ON workspace_membership")
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
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_membership TO {RUNTIME_ROLE}"
    )
