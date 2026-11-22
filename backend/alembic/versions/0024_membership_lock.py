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
    "workspace_membership_ensure_home(uuid, text, uuid)",
    "workspace_membership_add_member(uuid, text, text)",
    "workspace_membership_accept_invitation(uuid, text)",
    "workspace_invitation_create(uuid, text, text)",
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
        -- Self-serve home: CREATE-AND-CLAIM only. The workspaces row and the
        -- caller's owner membership are written in one statement pair, and
        -- the membership is written ONLY when this call itself inserted the
        -- workspaces row (ON CONFLICT DO NOTHING + FOUND): an existing
        -- workspace is never claimed, whether or not anyone is a member of
        -- it. The id must be the session's active workspace (the same bound
        -- 0001's workspaces policy enforces on the app role). The API calls
        -- this before any other write to a self-serve workspace, so the home
        -- row is always created here. Returns true when it claimed.
        CREATE OR REPLACE FUNCTION workspace_membership_ensure_home(
            p_workspace_id uuid, p_name text, p_org_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
        BEGIN
            IF v_uc_uid IS NULL OR p_workspace_id IS NULL
               OR p_workspace_id IS DISTINCT FROM current_workspace_id() THEN
                RAISE EXCEPTION 'workspace_membership_ensure_home: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            IF p_name IS NULL OR p_name = '' THEN
                RAISE EXCEPTION 'workspace_membership_ensure_home: workspace name required'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO workspaces (id, name, org_id)
            VALUES (p_workspace_id, p_name, p_org_id)
            ON CONFLICT (id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            INSERT INTO workspace_membership
                (id, user_uc_uid, workspace_id, workspace_name, role)
            VALUES (gen_random_uuid(), v_uc_uid, p_workspace_id, p_name, 'owner');
            RETURN true;
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
        -- Invitations are created ONLY here: the actor must be an active
        -- owner of the workspace, the stored hash is computed from the raw
        -- token inside the function, the role is always 'member' and the
        -- expiry is fixed (7 days). Returns the new invitation's id/expiry.
        CREATE OR REPLACE FUNCTION workspace_invitation_create(
            p_workspace uuid, p_raw_token text, p_invitee_uc_uid text,
            OUT o_id uuid, OUT o_expires_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            v_uc_uid text := current_uc_uid();
        BEGIN
            IF v_uc_uid IS NULL OR NOT EXISTS (
                SELECT 1 FROM workspace_membership
                WHERE workspace_id = p_workspace
                  AND user_uc_uid = v_uc_uid
                  AND role = 'owner'
                  AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'workspace_invitation_create: workspace owner required'
                    USING ERRCODE = '42501';
            END IF;
            IF p_invitee_uc_uid IS NULL OR btrim(p_invitee_uc_uid) = '' THEN
                RAISE EXCEPTION 'workspace_invitation_create: invitee required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_raw_token IS NULL OR length(p_raw_token) < 32 THEN
                RAISE EXCEPTION 'workspace_invitation_create: token too short'
                    USING ERRCODE = '22023';
            END IF;
            o_id := gen_random_uuid();
            o_expires_at := now() + interval '7 days';
            INSERT INTO workspace_invitation
                (id, workspace_id, token_hash, role, expires_at, created_by_uc_uid,
                 invitee_uc_uid)
            VALUES (
                o_id, p_workspace,
                encode(sha256(convert_to(p_raw_token, 'UTF8')), 'hex'),
                'member', o_expires_at, v_uc_uid, btrim(p_invitee_uc_uid)
            );
        END
        $$
        """
    )
    op.execute(
        """
        -- Accept: the raw token is hashed HERE and compared with the stored
        -- hash (a caller cannot present a hash it read). Only 'member'
        -- invitations are honoured, and only by their bound invitee
        -- (invitee_uc_uid = current_uc_uid()); a pre-0024 invitation has no
        -- invitee and can no longer be accepted. An active member keeps its stored role;
        -- a soft-deleted one is restored as a member. Returns the consumed
        -- invitation's id.
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
            v_name text;
        BEGIN
            IF v_uc_uid IS NULL THEN
                RAISE EXCEPTION 'workspace_membership_accept_invitation: actor not authorized'
                    USING ERRCODE = '42501';
            END IF;
            IF p_raw_token IS NULL OR p_raw_token = '' THEN
                RAISE EXCEPTION 'invitation is invalid or expired' USING ERRCODE = 'P0001';
            END IF;
            SELECT * INTO v_invitation
            FROM workspace_invitation
            WHERE token_hash = encode(sha256(convert_to(p_raw_token, 'UTF8')), 'hex')
            FOR UPDATE;
            IF NOT FOUND
               OR v_invitation.consumed_at IS NOT NULL
               OR v_invitation.expires_at <= now()
               OR v_invitation.role IS DISTINCT FROM 'member'
               OR v_invitation.invitee_uc_uid IS DISTINCT FROM v_uc_uid
               OR v_invitation.workspace_id IS DISTINCT FROM p_workspace THEN
                RAISE EXCEPTION 'invitation is invalid or expired' USING ERRCODE = 'P0001';
            END IF;
            SELECT name INTO v_name FROM workspaces WHERE id = p_workspace;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'invitation is invalid or expired' USING ERRCODE = 'P0001';
            END IF;
            SELECT * INTO v_row
            FROM workspace_membership
            WHERE workspace_id = p_workspace AND user_uc_uid = v_uc_uid
            FOR UPDATE;
            IF NOT FOUND THEN
                INSERT INTO workspace_membership
                    (id, user_uc_uid, workspace_id, workspace_name, role)
                VALUES (gen_random_uuid(), v_uc_uid, p_workspace, v_name, 'member');
            ELSIF v_row.deleted_at IS NOT NULL THEN
                UPDATE workspace_membership
                SET deleted_at = NULL, workspace_name = v_name, role = 'member'
                WHERE id = v_row.id;
            END IF;
            UPDATE workspace_invitation SET consumed_at = now() WHERE id = v_invitation.id;
            RETURN v_invitation.id;
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
    # Invitations: no direct read (token_hash) or write for the app role; they
    # are created and consumed only through the definers below.
    op.execute(f"REVOKE ALL ON workspace_invitation FROM {RUNTIME_ROLE}")
    op.execute("REVOKE ALL ON workspace_invitation FROM PUBLIC")
    # Every invitation names its invitee; acceptance requires a match.
    op.execute("ALTER TABLE workspace_invitation ADD COLUMN invitee_uc_uid varchar(255)")
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
    for signature in list(_FUNCTIONS) + ["workspace_membership_accept_invitation(uuid, text, text)"]:
        _drop_if_exists(signature)
    op.execute("ALTER TABLE workspace_invitation DROP COLUMN IF EXISTS invitee_uc_uid")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON workspace_invitation TO {RUNTIME_ROLE}")
    # Drop every 0024 policy, then recreate 0022's exact policy set (the
    # SELECT policy plus the INSERT/UPDATE/DELETE policies of
    # 0022_member_invitations) and its table grants. The original holes come
    # back with it: only downgrade in controlled environments.
    for policy, table in _OWNER_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    for cmd in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS workspace_membership_{cmd} ON workspace_membership")
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
    op.execute(
        f"""
        CREATE POLICY workspace_membership_insert ON workspace_membership
        FOR INSERT TO {RUNTIME_ROLE}
        WITH CHECK (
            user_uc_uid = current_uc_uid()
            OR workspace_membership_is_owner(workspace_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY workspace_membership_update ON workspace_membership
        FOR UPDATE TO {RUNTIME_ROLE}
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
        f"""
        CREATE POLICY workspace_membership_delete ON workspace_membership
        FOR DELETE TO {RUNTIME_ROLE}
        USING (workspace_membership_is_owner(workspace_id))
        """
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_membership TO {RUNTIME_ROLE}"
    )
