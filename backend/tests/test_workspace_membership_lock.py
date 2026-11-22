"""Migration 0024 locks workspace_membership against the app role.

Writes must go through SECURITY DEFINER functions only; the app role loses
direct INSERT/UPDATE/DELETE on the table.  Every test here runs the raw SQL an
attacker (or a legacy code path) would use as the NOBYPASSRLS runtime role and
expects a Postgres error.  Seeds use the owner role (BYPASSRLS).  Skips unless
TPO_TEST_DATABASE_URL points at a migrated DB authenticating as
tax_planning_ops_app and TPO_TEST_OWNER_DATABASE_URL at the same DB as
tax_planning_ops_owner (all subjects/workspaces fictional).
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

OWNER_UID = "fictional-owner-t1"
OTHER_UID = "fictional-stranger-t1"


def _app_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_DATABASE_URL not set")
    return dsn


def _owner_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_OWNER_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_OWNER_DATABASE_URL not set")
    return dsn


def _app_async_dsn() -> str:
    dsn = _app_dsn()
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn.removeprefix("postgresql://")
    return dsn


@pytest.fixture
async def app_conn():
    # Each statement commits in its own implicit transaction, so session-scoped
    # GUCs (set_config ..., false) persist across statements on this connection.
    conn = await asyncpg.connect(_app_dsn())
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def app_session():
    """A SQLAlchemy AsyncSession over the app role (for the service paths)."""
    engine = create_async_engine(_app_async_dsn(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False, autoflush=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def owner_conn():
    conn = await asyncpg.connect(_owner_dsn())
    try:
        yield conn
    finally:
        await conn.close()


async def _seed(
    owner_conn: asyncpg.Connection,
    owner_uid: str,
    ws_id: str,
    workspace_name: str,
) -> None:
    """Commit the seed rows: the app-role session fixture rolls its transaction
    back, so uncommitted owner-side writes are invisible to it (FK checks bypass
    RLS, but SELECT is scoped)."""
    async with owner_conn.transaction():
        await owner_conn.execute(
            "INSERT INTO workspaces (id, name) VALUES ($1, $2) "
            "ON CONFLICT (id) DO NOTHING",
            ws_id,
            workspace_name,
        )
        await owner_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (gen_random_uuid(), $1, $2, $3, 'owner')",
            owner_uid,
            ws_id,
            workspace_name,
        )


async def _set_guc(conn: asyncpg.Connection, uc_uid: str, workspace_id: str) -> None:
    # LOCAL (true) scope dies with the implicit asyncpg transaction; use plain
    # session scope so the GUCs persist across statements on this connection.
    await conn.execute("SELECT set_config('app.uc_uid', $1, false)", uc_uid)
    await conn.execute(
        "SELECT set_config('app.current_workspace', $1, false)", workspace_id
    )


@pytest.mark.asyncio
async def test_app_cannot_insert_own_membership_anywhere(app_conn, owner_conn) -> None:
    """The 0022 hole: any session could insert a membership FOR ITSELF in ANY
    workspace with ANY role. After 0024 the app role has no INSERT at all."""
    ws_id = str(uuid4())
    foreign_ws = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await owner_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, 'Fictional Foreign LLP')", foreign_ws
    )
    await _set_guc(app_conn, OTHER_UID, foreign_ws)
    with pytest.raises(asyncpg.exceptions.PostgresError):
        await app_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (gen_random_uuid(), $1, $2, 'Fictional Foreign LLP', 'owner')",
            OTHER_UID,
            foreign_ws,
        )


@pytest.mark.asyncio
async def test_app_cannot_insert_another_users_membership_as_owner(
    app_conn, owner_conn
) -> None:
    """Even acting as a workspace owner (the 0022 owner clause), the app role
    may not insert another user's membership directly."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    with pytest.raises(asyncpg.exceptions.PostgresError):
        await app_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
            OTHER_UID,
            ws_id,
        )


@pytest.mark.asyncio
async def test_app_cannot_raise_own_role(app_conn, owner_conn) -> None:
    """The 0022 hole: a user could UPDATE their OWN row to role='owner'. After
    0024 the app role has no UPDATE at all."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    async with owner_conn.transaction():
        await owner_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
            OTHER_UID,
            ws_id,
        )
    await _set_guc(app_conn, OTHER_UID, ws_id)
    with pytest.raises(asyncpg.exceptions.PostgresError):
        await app_conn.execute(
            "UPDATE workspace_membership SET role = 'owner' "
            "WHERE user_uc_uid = $1 AND workspace_id = $2",
            OTHER_UID,
            ws_id,
        )


@pytest.mark.asyncio
async def test_app_cannot_delete_memberships(app_conn, owner_conn) -> None:
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    with pytest.raises(asyncpg.exceptions.PostgresError):
        await app_conn.execute(
            "DELETE FROM workspace_membership WHERE workspace_id = $1", ws_id
        )


@pytest.mark.asyncio
async def test_app_can_read_own_membership(app_conn, owner_conn) -> None:
    """Reads stay intact: the app role still sees exactly its own rows."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    assert (
        await app_conn.fetchval(
            "SELECT count(*) FROM workspace_membership "
            "WHERE user_uc_uid = $1 AND workspace_id = $2 AND deleted_at IS NULL",
            OWNER_UID,
            ws_id,
        )
        == 1
    )
    # RLS is user-scoped: no matter what uc_uid the session claims, another
    # user's rows are invisible.
    await _set_guc(app_conn, OTHER_UID, ws_id)
    assert (
        await app_conn.fetchval(
            "SELECT count(*) FROM workspace_membership "
            "WHERE workspace_id = $1 AND deleted_at IS NULL",
            ws_id,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_definer_functions_authorize_membership(app_conn, owner_conn) -> None:
    """The lock must not break reads of the is_member/is_owner policy helpers:
    the definer functions still answer correctly for an active owner."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    assert (
        await app_conn.fetchval(
            "SELECT workspace_membership_is_member($1)", ws_id
        )
        is True
    )
    assert (
        await app_conn.fetchval(
            "SELECT workspace_membership_is_owner($1)", ws_id
        )
        is True
    )
    assert (
        await app_conn.fetchval(
            "SELECT workspace_membership_is_member($1)", str(uuid4())
        )
        is False
    )


@pytest.mark.asyncio
async def test_app_direct_grants_revoked(app_conn) -> None:
    """The lock is enforced by REVOKED table grants, not just policy wording."""
    privileges = {
        r["privilege_type"]
        for r in await app_conn.fetch(
            """
            SELECT DISTINCT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public'
              AND table_name = 'workspace_membership'
               AND grantee = current_user
            """
        )
    }
    assert privileges == {"SELECT"}, f"unexpected grants: {privileges}"


@pytest.mark.asyncio
async def test_create_workspace_definer_mints_owner_row(app_session, owner_conn) -> None:
    """POST /workspaces path: the SECURITY DEFINER create function must still
    work for the app role — server-generated id, actor becomes owner."""
    from app.services.workspaces import create_workspace

    created = await create_workspace(uc_uid=OTHER_UID, name="Fictional New Co")
    assert created["role"] == "owner"
    new_ws: str = created["workspace_id"]
    assert UUID(new_ws) is not None
    role = await owner_conn.fetchval(
        "SELECT role FROM workspace_membership "
        "WHERE user_uc_uid = $1 AND workspace_id = $2",
        OTHER_UID,
        new_ws,
    )
    assert role == "owner"


@pytest.mark.asyncio
async def test_add_member_and_invitation_through_definer(app_session, owner_conn) -> None:
    """add_member (owner-gated) and accept_invitation still work after the
    lock, and a NON-owner is still refused by the function itself."""
    from app.services.members import (
        InvalidInvitationError,
        accept_invitation,
        add_member,
        create_invitation,
    )

    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await app_session.execute(text("SELECT set_config('app.uc_uid', :v, true)"), {"v": OWNER_UID})
    await app_session.execute(
        text("SELECT set_config('app.current_workspace', :v, true)"), {"v": ws_id}
    )
    added = await add_member(
        app_session, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OTHER_UID
    )
    assert added.role == "member"

    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
        "fictional-plain-t1",
        ws_id,
    )
    await app_session.execute(
        text("SELECT set_config('app.uc_uid', :v, true)"), {"v": "fictional-plain-t1"}
    )
    with pytest.raises(PermissionError):
        await add_member(
            app_session,
            workspace_id=UUID(ws_id),
            actor_uc_uid="fictional-plain-t1",
            member_uc_uid="fictional-visitor-t1",
        )

    await app_session.execute(text("SELECT set_config('app.uc_uid', :v, true)"), {"v": OWNER_UID})
    invitee = "fictional-invitee-t1"
    created = await create_invitation(
        app_session, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, invitee_uc_uid=invitee
    )
    accepted = await accept_invitation(
        app_session,
        workspace_id=UUID(ws_id),
        actor_uc_uid=invitee,
        raw_token=str(created["invitation_token"]),
    )
    assert accepted.user_uc_uid == invitee
    assert accepted.role == "member"

    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            app_session,
            workspace_id=UUID(ws_id),
            actor_uc_uid="fictional-late-t1",
            raw_token=str(created["invitation_token"]),
        )


@pytest.mark.asyncio
async def test_remove_member_through_definer(app_session, owner_conn) -> None:
    from app.services.members import LastOwnerError, remove_member

    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    async with owner_conn.transaction():
        await owner_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role) "
            "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
            OTHER_UID,
            ws_id,
        )
    await app_session.execute(text("SELECT set_config('app.uc_uid', :v, true)"), {"v": OWNER_UID})
    await app_session.execute(
        text("SELECT set_config('app.current_workspace', :v, true)"), {"v": ws_id}
    )
    removed = await remove_member(
        app_session, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OTHER_UID
    )
    assert removed.user_uc_uid == OTHER_UID
    with pytest.raises(LastOwnerError):
        await remove_member(
            app_session, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OWNER_UID
        )


@pytest.mark.asyncio
async def test_c1_owner_read_policies_scoped_and_app_has_no_write_policy(
    owner_conn,
) -> None:
    """C1: under FORCE RLS the NOBYPASSRLS definer owner needs SELECT (and the
    write) policies on workspace_membership and workspaces; they name ONLY the
    table owner. The app role keeps a single SELECT policy and no write one."""
    rows = await owner_conn.fetch(
        """
        SELECT tablename, policyname, cmd, roles::text[] AS roles
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN ('workspace_membership', 'workspaces')
        """
    )
    owner = await owner_conn.fetchval(
        "SELECT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE oid = 'workspace_membership'::regclass"
    )
    app_cmds = {
        (r["tablename"], r["cmd"]) for r in rows if "tax_planning_ops_app" in r["roles"]
    }
    assert ("workspace_membership", "SELECT") in app_cmds
    assert not {c for t, c in app_cmds if t == "workspace_membership"} - {"SELECT"}
    owner_cmds = {(r["tablename"], r["cmd"]) for r in rows if owner in r["roles"]}
    assert owner_cmds == {
        ("workspace_membership", "SELECT"),
        ("workspace_membership", "INSERT"),
        ("workspace_membership", "UPDATE"),
        ("workspaces", "SELECT"),
        ("workspaces", "INSERT"),
    }
    for r in rows:
        if owner in r["roles"]:
            assert r["roles"] == [owner], r
    # Every definer runs as the (NOBYPASSRLS) table owner.
    definer_owners = {
        r["owner"]
        for r in await owner_conn.fetch(
            "SELECT pg_get_userbyid(proowner) AS owner FROM pg_proc "
            "WHERE proname LIKE 'workspace_membership_%' AND prosecdef"
        )
    }
    assert definer_owners == {owner}


@pytest.mark.asyncio
async def test_c1_definers_work_with_nobypassrls_owner(app_conn, owner_conn) -> None:
    """C1: create_workspace, add_member and an occupied ensure_home ran into
    42501 under FORCE RLS; they must succeed as the app role."""
    await _set_guc(app_conn, OWNER_UID, str(uuid4()))
    new_ws = await app_conn.fetchval(
        "SELECT workspace_membership_create_workspace($1, 'Fictional Birch LLC', NULL)",
        OWNER_UID,
    )
    await _set_guc(app_conn, OWNER_UID, str(new_ws))
    await app_conn.execute(
        "SELECT workspace_membership_add_member($1, $2, 'Fictional Birch LLC')",
        new_ws,
        OTHER_UID,
    )
    # Occupied: the caller already owns it; idempotent, no error.
    assert (
        await app_conn.fetchval(
            "SELECT workspace_membership_ensure_home($1, 'Fictional Birch LLC', NULL)",
            new_ws,
        )
        is False
    )
    rows = await owner_conn.fetch(
        "SELECT user_uc_uid, role FROM workspace_membership WHERE workspace_id = $1",
        new_ws,
    )
    assert {(r["user_uc_uid"], r["role"]) for r in rows} == {
        (OWNER_UID, "owner"),
        (OTHER_UID, "member"),
    }


@pytest.mark.asyncio
async def test_c4_app_role_has_no_direct_invitation_access(app_conn, owner_conn) -> None:
    """C4: the app role could SELECT token_hash and INSERT/UPDATE invitations
    (mint an owner invitation, then accept it). It now has no table grant."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    privileges = await app_conn.fetch(
        "SELECT privilege_type FROM information_schema.table_privileges "
        "WHERE table_name = 'workspace_invitation' AND grantee = current_user"
    )
    assert privileges == []
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await app_conn.fetch("SELECT token_hash FROM workspace_invitation")
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await app_conn.execute(
            "INSERT INTO workspace_invitation "
            "(workspace_id, token_hash, role, expires_at, created_by_uc_uid) "
            "VALUES ($1, repeat('a', 64), 'owner', now() + interval '1 day', $2)",
            ws_id,
            OWNER_UID,
        )
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE workspace_invitation SET role = 'owner'")


@pytest.mark.asyncio
async def test_c4_accept_hashes_raw_token_in_definer(app_conn, owner_conn) -> None:
    """C4: acceptance used to trust a caller-supplied hash. Presenting the
    stored HASH as the token must fail; only the raw token works."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    raw = "fictional-raw-token-" + "x" * 32
    await _set_guc(app_conn, OWNER_UID, ws_id)
    await app_conn.fetchrow(
        "SELECT * FROM workspace_invitation_create($1, $2, 'fictional-invitee-c4')", ws_id, raw
    )
    stored = await owner_conn.fetchval(
        "SELECT token_hash FROM workspace_invitation WHERE workspace_id = $1", ws_id
    )
    from app.services.member_tokens import hash_invitation_token

    assert stored == hash_invitation_token(raw)
    await _set_guc(app_conn, "fictional-invitee-c4", ws_id)
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await app_conn.fetchval(
            "SELECT workspace_membership_accept_invitation($1, $2)", ws_id, stored
        )
    assert await app_conn.fetchval(
        "SELECT workspace_membership_accept_invitation($1, $2)", ws_id, raw
    )
    assert (
        await owner_conn.fetchval(
            "SELECT role FROM workspace_membership "
            "WHERE workspace_id = $1 AND user_uc_uid = 'fictional-invitee-c4'",
            ws_id,
        )
        == "member"
    )


@pytest.mark.asyncio
async def test_c4_only_active_owner_can_create_invitation(app_conn, owner_conn) -> None:
    """C4: invitation creation goes through a definer that checks the inviter
    is an ACTIVE owner; a member or a soft-deleted owner gets 42501."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    async with owner_conn.transaction():
        await owner_conn.execute(
            "INSERT INTO workspace_membership "
            "(id, user_uc_uid, workspace_id, workspace_name, role, deleted_at) VALUES "
            "(gen_random_uuid(), 'fictional-member-c4', $1, 'n', 'member', NULL), "
            "(gen_random_uuid(), 'fictional-gone-c4', $1, 'n', 'owner', now())",
            ws_id,
        )
    for uid in ("fictional-member-c4", "fictional-gone-c4", OTHER_UID):
        await _set_guc(app_conn, uid, ws_id)
        with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
            await app_conn.fetchrow(
                "SELECT * FROM workspace_invitation_create($1, $2, 'fictional-x-c4')",
                ws_id,
                "y" * 43,
            )
        assert excinfo.value.sqlstate == "42501"
    assert (
        await owner_conn.fetchval(
            "SELECT count(*) FROM workspace_invitation WHERE workspace_id = $1", ws_id
        )
        == 0
    )


@pytest.mark.asyncio
async def test_c5_invitation_bound_to_invitee(app_conn, owner_conn) -> None:
    """C5: an invitation had no recipient, so whoever held the token joined.
    It now names its invitee; anyone else is refused and the invitation stays
    unconsumed for the real invitee. A pre-0024 row (no invitee) is dead."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    raw = "fictional-bound-token-" + "z" * 32
    await _set_guc(app_conn, OWNER_UID, ws_id)
    await app_conn.fetchrow(
        "SELECT * FROM workspace_invitation_create($1, $2, 'fictional-intended-c5')", ws_id, raw
    )
    assert (
        await owner_conn.fetchval(
            "SELECT invitee_uc_uid FROM workspace_invitation WHERE workspace_id = $1", ws_id
        )
        == "fictional-intended-c5"
    )
    await _set_guc(app_conn, "fictional-thief-c5", ws_id)
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await app_conn.fetchval(
            "SELECT workspace_membership_accept_invitation($1, $2)", ws_id, raw
        )
    assert (
        await owner_conn.fetchval(
            "SELECT count(*) FROM workspace_membership "
            "WHERE workspace_id = $1 AND user_uc_uid = 'fictional-thief-c5'",
            ws_id,
        )
        == 0
    )
    await _set_guc(app_conn, "fictional-intended-c5", ws_id)
    assert await app_conn.fetchval(
        "SELECT workspace_membership_accept_invitation($1, $2)", ws_id, raw
    )

    # A legacy invitation with no invitee cannot be accepted by anyone.
    from app.services.member_tokens import hash_invitation_token

    legacy = "fictional-legacy-token-" + "q" * 32
    await owner_conn.execute(
        "INSERT INTO workspace_invitation "
        "(workspace_id, token_hash, role, expires_at, created_by_uc_uid) "
        "VALUES ($1, $2, 'member', now() + interval '1 day', $3)",
        ws_id,
        hash_invitation_token(legacy),
        OWNER_UID,
    )
    await _set_guc(app_conn, "fictional-anyone-c5", ws_id)
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await app_conn.fetchval(
            "SELECT workspace_membership_accept_invitation($1, $2)", ws_id, legacy
        )


@pytest.mark.asyncio
async def test_c5_service_wrong_user_cannot_accept(app_session, owner_conn) -> None:
    from app.services.members import (
        InvalidInvitationError,
        accept_invitation,
        create_invitation,
    )

    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    from app.db.session import bind_session_context

    await bind_session_context(app_session, ws_id, OWNER_UID)
    created = await create_invitation(
        app_session,
        workspace_id=UUID(ws_id),
        actor_uc_uid=OWNER_UID,
        invitee_uc_uid="fictional-intended-c5s",
    )
    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            app_session,
            workspace_id=UUID(ws_id),
            actor_uc_uid="fictional-other-c5s",
            raw_token=str(created["invitation_token"]),
        )


async def _seed_member(
    owner_conn: asyncpg.Connection, ws_id: str, uid: str, role: str, deleted: bool = False
) -> None:
    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role, deleted_at) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', $3, "
        "CASE WHEN $4 THEN now() END)",
        uid,
        ws_id,
        role,
        deleted,
    )


async def _active(owner_conn: asyncpg.Connection, ws_id: str) -> set[tuple[str, str]]:
    rows = await owner_conn.fetch(
        "SELECT user_uc_uid, role FROM workspace_membership "
        "WHERE workspace_id = $1 AND deleted_at IS NULL",
        ws_id,
    )
    return {(r["user_uc_uid"], r["role"]) for r in rows}


@pytest.mark.asyncio
async def test_c6_remove_reads_stored_role_not_argument(app_conn, owner_conn) -> None:
    """C6: the definer took the target's role as an argument, so passing
    'member' removed the sole owner. It now has no role argument and reads the
    stored role: the sole owner cannot remove itself."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    with pytest.raises(asyncpg.exceptions.UndefinedFunctionError):
        await app_conn.fetchval(
            "SELECT workspace_membership_remove_member($1, $2, 'member')", ws_id, OWNER_UID
        )
    with pytest.raises(asyncpg.exceptions.RaiseError, match="last owner"):
        await app_conn.fetchval(
            "SELECT workspace_membership_remove_member($1, $2)", ws_id, OWNER_UID
        )
    assert await _active(owner_conn, ws_id) == {(OWNER_UID, "owner")}


@pytest.mark.asyncio
async def test_c6_soft_deleted_owner_is_not_an_owner(app_conn, owner_conn) -> None:
    """C6: the actor's owner check omitted deleted_at IS NULL, so a removed
    owner could still remove members. A soft-deleted owner row counts for
    neither the actor check nor the owner count."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _seed_member(owner_conn, ws_id, "fictional-exowner-c6", "owner", deleted=True)
    await _seed_member(owner_conn, ws_id, OTHER_UID, "member")
    await _set_guc(app_conn, "fictional-exowner-c6", ws_id)
    with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
        await app_conn.fetchval(
            "SELECT workspace_membership_remove_member($1, $2)", ws_id, OTHER_UID
        )
    assert excinfo.value.sqlstate == "42501"
    # The deleted owner row does not make the live owner removable either.
    await _set_guc(app_conn, OWNER_UID, ws_id)
    with pytest.raises(asyncpg.exceptions.RaiseError, match="last owner"):
        await app_conn.fetchval(
            "SELECT workspace_membership_remove_member($1, $2)", ws_id, OWNER_UID
        )
    assert await _active(owner_conn, ws_id) == {(OWNER_UID, "owner"), (OTHER_UID, "member")}


@pytest.mark.asyncio
async def test_c6_concurrent_owner_removals_keep_one_owner(owner_conn) -> None:
    """C6: two owners removing each other at the same time both saw two
    owners. The owner rows are locked for the count, so the second call waits,
    re-counts and is refused: one owner always remains."""
    import asyncio

    ws_id = str(uuid4())
    a, b = "fictional-owner-a-c6", "fictional-owner-b-c6"
    await _seed(owner_conn, a, ws_id, "Fictional Cedar Tax Group")
    await _seed_member(owner_conn, ws_id, b, "owner")
    conn_a = await asyncpg.connect(_app_dsn())
    conn_b = await asyncpg.connect(_app_dsn())
    try:
        await _set_guc(conn_a, a, ws_id)
        await _set_guc(conn_b, b, ws_id)
        tx_a = conn_a.transaction()
        await tx_a.start()
        await conn_a.fetchval("SELECT workspace_membership_remove_member($1, $2)", ws_id, b)

        async def b_removes_a() -> object:
            try:
                return await conn_b.fetchval(
                    "SELECT workspace_membership_remove_member($1, $2)", ws_id, a
                )
            except asyncpg.exceptions.PostgresError as exc:
                return exc

        pending = asyncio.create_task(b_removes_a())
        await asyncio.sleep(0.3)
        assert not pending.done(), "second removal must wait on the owner-row lock"
        await tx_a.commit()
        outcome = await asyncio.wait_for(pending, timeout=10)
    finally:
        await conn_a.close()
        await conn_b.close()
    # b was removed by a; b is no longer an active owner, so b's call fails.
    assert isinstance(outcome, asyncpg.exceptions.PostgresError)
    assert await _active(owner_conn, ws_id) == {(a, "owner")}


@pytest.mark.asyncio
async def test_c7_add_member_never_demotes_an_owner(app_conn, owner_conn) -> None:
    """C7: add_member on an existing owner set role='member', including on
    the sole owner (an owner could demote itself or a co-owner). Active rows
    keep their role; the call is a no-op for them."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _seed_member(owner_conn, ws_id, "fictional-coowner-c7", "owner")
    await _set_guc(app_conn, OWNER_UID, ws_id)
    for target in (OWNER_UID, "fictional-coowner-c7"):
        await app_conn.fetchval(
            "SELECT workspace_membership_add_member($1, $2, 'Fictional Cedar Tax Group')",
            ws_id,
            target,
        )
    assert await _active(owner_conn, ws_id) == {
        (OWNER_UID, "owner"),
        ("fictional-coowner-c7", "owner"),
    }


@pytest.mark.asyncio
async def test_c7_soft_deleted_owner_cannot_add(app_conn, owner_conn) -> None:
    """C7: the actor's owner check omitted deleted_at IS NULL."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _seed_member(owner_conn, ws_id, "fictional-exowner-c7", "owner", deleted=True)
    await _set_guc(app_conn, "fictional-exowner-c7", ws_id)
    with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
        await app_conn.fetchval(
            "SELECT workspace_membership_add_member($1, 'fictional-friend-c7', 'n')", ws_id
        )
    assert excinfo.value.sqlstate == "42501"
    assert await _active(owner_conn, ws_id) == {(OWNER_UID, "owner")}


@pytest.mark.asyncio
async def test_c7_removed_owner_is_restored_as_member(app_conn, owner_conn) -> None:
    """Re-adding a soft-deleted row restores it as a plain member (it is not
    an active owner, so nothing is demoted)."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await _seed_member(owner_conn, ws_id, "fictional-back-c7", "owner", deleted=True)
    await _set_guc(app_conn, OWNER_UID, ws_id)
    await app_conn.fetchval(
        "SELECT workspace_membership_add_member($1, 'fictional-back-c7', 'n')", ws_id
    )
    assert ("fictional-back-c7", "member") in await _active(owner_conn, ws_id)
