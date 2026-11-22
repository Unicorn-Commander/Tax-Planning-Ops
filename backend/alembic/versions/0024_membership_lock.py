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

Revision ID: 0024_membership_lock
Revises: 0023_workspace_org_binding
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_membership_lock"
down_revision: str | None = "0023_workspace_org_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "tax_planning_ops_app"

_FUNCTIONS = (
    "workspace_membership_create_workspace(text, text, uuid)",
    "workspace_membership_ensure_home(uuid, text)",
    "workspace_membership_add_member(uuid, text, text)",
    "workspace_membership_accept_invitation(uuid, text, text)",
    "workspace_membership_remove_member(uuid, text, text)",
)


def _create_write_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION workspace_membership_create_workspace(
            p_owner text, p_name text, p_org_id uuid
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
            INSERT INTO workspaces (id, name, org_id) VALUES (v_new_id, p_name, p_org_id);
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
        -- Self-serve home row: claim an UNOCCUPIED workspace id as the actor's
        -- home. create_workspace mints a fresh uuid, but the self-serve home is
        -- derived (uuid5 of the subject) and the caller must get a row in THAT
        -- workspace. The guard is the only claim: an owner membership for the
        -- actor is inserted only when NO membership row of ANY user exists for
        -- p_workspace_id — it can never join a workspace someone else has.
        -- If the actor already has a row (idempotent re-call) it does nothing;
        -- if anyone else has one it does nothing, no error.
        CREATE OR REPLACE FUNCTION workspace_membership_ensure_home(
            p_workspace_id uuid, p_name text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
            v_claimable boolean;
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_ensure_home: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            SELECT NOT EXISTS (
                SELECT 1 FROM workspace_membership WHERE workspace_id = p_workspace_id
            ) INTO v_claimable;
            IF NOT v_claimable THEN
                RETURN;
            END IF;
            IF p_name IS NULL OR p_name = '' THEN
                RAISE EXCEPTION 'workspace_membership_ensure_home: workspace name required'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO workspaces (id, name)
            VALUES (p_workspace_id, p_name)
            ON CONFLICT (id) DO NOTHING;
            INSERT INTO workspace_membership
                (id, user_uc_uid, workspace_id, workspace_name, role)
            VALUES (gen_random_uuid(), v_uc_uid, p_workspace_id, p_name, 'owner');
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
            p_workspace uuid, p_raw_token text, p_token_hash text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
            v_invitation workspace_invitation;
            v_row workspace_membership;
            v_now timestamptz := now();
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_accept_invitation: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            -- The hash is computed in the service with the same function it
            -- stores on create; the raw token stays out of the persisted row.
            IF p_token_hash IS NULL OR p_token_hash = '' THEN
                RAISE EXCEPTION 'invitation is invalid or expired'
                    USING ERRCODE = 'P0001';
            END IF;
            SELECT * INTO v_invitation
            FROM workspace_invitation
            WHERE token_hash = p_token_hash
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


def _lock_policies(owner_role: str, workspaces_owner: str) -> None:
    op.execute("DROP POLICY IF EXISTS workspace_membership_select ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_insert ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_update ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_delete ON workspace_membership")
    # The app role keeps the 0022 SELECT shape (own rows always; the roster
    # read behind the transaction-local flag) and gets NO write policy and NO
    # write grant.
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
    # FORCE RLS applies to the table owner too, and a NOBYPASSRLS owner is the
    # role every SECURITY DEFINER function here (and 0022's is_member/is_owner
    # helpers) runs as. A definer reads before it writes (owner checks, the
    # occupied check, UPDATE ... WHERE), so it needs READ policies as well as
    # write policies. They are scoped to the owner role only (no app/PUBLIC
    # role is named) and to the commands the definers use: SELECT, INSERT,
    # UPDATE (soft delete). No DELETE policy: nothing hard-deletes.
    # Authorization against current_uc_uid() lives in the function bodies.
    op.execute(
        f"""
        CREATE POLICY workspace_membership_owner_select ON workspace_membership
        FOR SELECT TO {owner_role}
        USING (true)
        """
    )
    op.execute(
        f"""
        CREATE POLICY workspace_membership_owner_insert ON workspace_membership
        FOR INSERT TO {owner_role}
        WITH CHECK (true)
        """
    )
    op.execute(
        f"""
        CREATE POLICY workspace_membership_owner_update ON workspace_membership
        FOR UPDATE TO {owner_role}
        USING (true)
        WITH CHECK (true)
        """
    )
    # workspaces (0001: FORCE RLS, one FOR ALL policy for the app role): the
    # create/ensure-home definers provision the row and read it back.
    op.execute(
        f"""
        CREATE POLICY workspaces_owner_select ON workspaces
        FOR SELECT TO {workspaces_owner}
        USING (true)
        """
    )
    op.execute(
        f"""
        CREATE POLICY workspaces_owner_insert ON workspaces
        FOR INSERT TO {workspaces_owner}
        WITH CHECK (true)
        """
    )


_OWNER_POLICIES = (
    ("workspace_membership_owner_select", "workspace_membership"),
    ("workspace_membership_owner_insert", "workspace_membership"),
    ("workspace_membership_owner_update", "workspace_membership"),
    ("workspaces_owner_select", "workspaces"),
    ("workspaces_owner_insert", "workspaces"),
)


def _owner_role(table: str = "workspace_membership") -> str:
    """The table's actual owner, read at migration time. The definer functions
    are re-owned to it (below), so they run as that role and, under FORCE RLS,
    pass exactly the policies whose TO clause names it."""
    bind = op.get_bind()
    row: tuple[str, ...] = bind.exec_driver_sql(
        f"SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = '{table}'::regclass"
    ).one()
    return str(row[0])


def upgrade() -> None:
    owner_role = _owner_role()
    # 1. Revoke every write path from the app role (and PUBLIC).
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON workspace_membership FROM {RUNTIME_ROLE}")
    op.execute("REVOKE ALL ON workspace_membership FROM PUBLIC")
    # 2. Lock policies: SELECT stays user-scoped; the INSERT/UPDATE/DELETE
    #    policies name the table owner (a role with no app grants) so the
    #    definer functions — owned by the migration role — pass FORCE RLS.
    _lock_policies(owner_role, _owner_role("workspaces"))
    # 3. The only write paths: SECURITY DEFINER functions, owned by the table
    #    owner whatever role runs the migration (so the owner policies apply).
    _create_write_functions()
    for signature in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {owner_role}")


def _drop_if_exists(signature: str) -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {signature}")


def _revoke_if_exists(signature: str) -> None:
    parts = signature.split("(", 1)
    name, args = parts[0].strip(), parts[1].rstrip(")")
    name_q = name.replace("'", "''")
    args_q = args.replace("'", "''")
    exists = (
        op.get_bind()
        .exec_driver_sql(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname = '{name_q}'
                  AND pg_catalog.pg_get_function_identity_arguments(p.oid) = '{args_q}'
            )
            """
        )
        .scalar()
    )
    if exists:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME_ROLE}")


def downgrade() -> None:
    # REVOKE the still-existing signatures (no-op when none are granted), then
    # DROP (never fails on a missing function).  An in-flight 0023 deployed
    # with an older accept_invitation arity downgrades cleanly too.
    for signature in _FUNCTIONS:
        _revoke_if_exists(signature)
    for signature in list(_FUNCTIONS) + ["workspace_membership_accept_invitation(uuid, text)"]:
        _drop_if_exists(signature)
    # Drop the 0023 owner-scoped write policies (they do not exist under 0022),
    # then restore 0022's exact policy set: no write policies at all — the
    # INSERT/UPDATE/DELETE paths come back with the granted table privileges,
    # exactly as 0022 left them.
    op.execute("DROP POLICY IF EXISTS workspace_membership_select ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_insert ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_update ON workspace_membership")
    op.execute("DROP POLICY IF EXISTS workspace_membership_delete ON workspace_membership")
    for policy, table in _OWNER_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
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
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_membership TO {RUNTIME_ROLE}"
    )
