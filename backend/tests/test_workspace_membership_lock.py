"""Migration 0023 locks workspace_membership against the app role.

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


@pytest.fixture
async def app_conn():
    conn = await asyncpg.connect(_app_dsn())
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def owner_conn():
    conn = await asyncpg.connect(_owner_dsn())
    try:
        yield conn
    finally:
        await conn.close()


async def _seed(
    owner_conn: asyncpg.Connection, owner_uid: str, ws_id: str, workspace_name: str
) -> None:
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
    await conn.execute("SELECT set_config('app.uc_uid', $1, true)", uc_uid)
    await conn.execute("SELECT set_config('app.current_workspace', $1, true)", workspace_id)


@pytest.mark.asyncio
async def test_app_cannot_insert_own_membership_anywhere(app_conn, owner_conn) -> None:
    """The 0022 hole: any session could insert a membership FOR ITSELF in ANY
    workspace with ANY role. After 0023 the app role has no INSERT at all."""
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
    0023 the app role has no UPDATE at all."""
    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
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
            "WHERE user_uc_uid = $1 AND deleted_at IS NULL",
            OWNER_UID,
        )
        == 1
    )
    assert (
        await app_conn.fetchval(
            "SELECT count(*) FROM workspace_membership "
            "WHERE user_uc_uid = $1 AND deleted_at IS NULL",
            OTHER_UID,
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
    privileges = set(
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
    )
    assert privileges == {"SELECT"}, f"unexpected grants: {privileges}"


@pytest.mark.asyncio
async def test_create_workspace_definer_mints_owner_row(app_conn, owner_conn) -> None:
    """POST /workspaces path: the SECURITY DEFINER create function must still
    work for the app role — server-generated id, actor becomes owner."""
    import uuid

    from app.services.workspaces import create_workspace

    async with app_conn.transaction():
        created = await create_workspace(uc_uid=OTHER_UID, name="Fictional New Co")
        assert created["role"] == "owner"
        new_ws: str = created["workspace_id"]
        assert UUID(new_ws) == uuid.UUID(new_ws)
        role = await owner_conn.fetchval(
            "SELECT role FROM workspace_membership "
            "WHERE user_uc_uid = $1 AND workspace_id = $2",
            OTHER_UID,
            new_ws,
        )
        assert role == "owner"


@pytest.mark.asyncio
async def test_add_member_and_invitation_through_definer(app_conn, owner_conn) -> None:
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
    added = await add_member(
        app_conn, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OTHER_UID
    )
    assert added.role == "member"

    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
        "fictional-plain-t1",
        ws_id,
    )
    with pytest.raises(PermissionError):
        await add_member(
            app_conn,
            workspace_id=UUID(ws_id),
            actor_uc_uid="fictional-plain-t1",
            member_uc_uid="fictional-visitor-t1",
        )

    created = await create_invitation(app_conn, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID)
    invitee = "fictional-invitee-t1"
    accepted = await accept_invitation(
        app_conn,
        workspace_id=UUID(ws_id),
        actor_uc_uid=invitee,
        raw_token=str(created["invitation_token"]),
    )
    assert accepted.user_uc_uid == invitee
    assert accepted.role == "member"

    with pytest.raises(InvalidInvitationError):
        await accept_invitation(
            app_conn,
            workspace_id=UUID(ws_id),
            actor_uc_uid="fictional-late-t1",
            raw_token=str(created["invitation_token"]),
        )


@pytest.mark.asyncio
async def test_remove_member_through_definer(app_conn, owner_conn) -> None:
    from app.services.members import LastOwnerError, remove_member

    ws_id = str(uuid4())
    await _seed(owner_conn, OWNER_UID, ws_id, "Fictional Cedar Tax Group")
    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, 'Fictional Cedar Tax Group', 'member')",
        OTHER_UID,
        ws_id,
    )
    removed = await remove_member(
        app_conn, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OTHER_UID
    )
    assert removed.user_uc_uid == OTHER_UID
    with pytest.raises(LastOwnerError):
        await remove_member(
            app_conn, workspace_id=UUID(ws_id), actor_uc_uid=OWNER_UID, member_uc_uid=OWNER_UID
        )
