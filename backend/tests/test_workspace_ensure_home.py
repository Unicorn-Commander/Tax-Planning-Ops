"""ensure_home definer tests — run with the same env as the integration suite."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")


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


async def _set_guc(conn: asyncpg.Connection, uc_uid: str, workspace_id: str) -> None:
    await conn.execute("SELECT set_config('app.uc_uid', $1, false)", uc_uid)
    await conn.execute(
        "SELECT set_config('app.current_workspace', $1, false)", workspace_id
    )


async def _members(owner_conn: asyncpg.Connection, ws_id: str) -> set[tuple[str, str]]:
    rows = await owner_conn.fetch(
        "SELECT user_uc_uid, role FROM workspace_membership WHERE workspace_id = $1", ws_id
    )
    return {(r["user_uc_uid"], r["role"]) for r in rows}


_CALL = "SELECT workspace_membership_ensure_home($1, 'Fictional Cedar Tax Group', NULL)"


@pytest.mark.asyncio
async def test_ensure_home_occupied_id_no_row_no_error(app_conn, owner_conn) -> None:
    """A workspace id another user already holds: ensure_home writes NOTHING
    for the caller and raises no error (it must not join a foreign workspace)."""
    ws_id = str(uuid4())
    await owner_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, 'Fictional Cedar Tax Group')", ws_id
    )
    await owner_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), 'fictional-holder-t9', $1, 'Fictional Cedar Tax Group', 'owner')",
        ws_id,
    )
    await _set_guc(app_conn, "fictional-caller-t9", ws_id)
    assert await app_conn.fetchval(_CALL, ws_id) is False
    assert await _members(owner_conn, ws_id) == {("fictional-holder-t9", "owner")}
    assert await owner_conn.fetchval("SELECT count(*) FROM workspaces WHERE id=$1", ws_id) == 1


@pytest.mark.asyncio
async def test_c3_existing_workspace_without_members_is_not_claimed(
    app_conn, owner_conn
) -> None:
    """C3: a workspaces row that exists but has NO membership row (a managed
    workspace not yet seeded, or one whose members all left) was claimed as
    owner by any caller. It must never be claimed."""
    ws_id = str(uuid4())
    await owner_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, 'Fictional Foreign LLP')", ws_id
    )
    await _set_guc(app_conn, "fictional-intruder-t9", ws_id)
    assert await app_conn.fetchval(_CALL, ws_id) is False
    assert await _members(owner_conn, ws_id) == set()
    assert (
        await owner_conn.fetchval("SELECT name FROM workspaces WHERE id=$1", ws_id)
        == "Fictional Foreign LLP"
    )


@pytest.mark.asyncio
async def test_c3_fresh_workspace_is_created_and_claimed_once(app_conn, owner_conn) -> None:
    """The legitimate path: a workspace that does not exist yet is created and
    claimed by the caller in one call; a repeat call claims nothing more."""
    ws_id = str(uuid4())
    await _set_guc(app_conn, "fictional-newcomer-t9", ws_id)
    assert await app_conn.fetchval(_CALL, ws_id) is True
    assert await app_conn.fetchval(_CALL, ws_id) is False
    assert await _members(owner_conn, ws_id) == {("fictional-newcomer-t9", "owner")}
    # A second user arriving at the same id later claims nothing.
    await _set_guc(app_conn, "fictional-latecomer-t9", ws_id)
    assert await app_conn.fetchval(_CALL, ws_id) is False
    assert await _members(owner_conn, ws_id) == {("fictional-newcomer-t9", "owner")}


@pytest.mark.asyncio
async def test_c3_id_other_than_active_workspace_refused(app_conn, owner_conn) -> None:
    """The id must be the session's active workspace; any other id is 42501."""
    ws_id = str(uuid4())
    await _set_guc(app_conn, "fictional-caller-t9", str(uuid4()))
    with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
        await app_conn.fetchval(_CALL, ws_id)
    assert excinfo.value.sqlstate == "42501"
    assert await owner_conn.fetchval("SELECT count(*) FROM workspaces WHERE id=$1", ws_id) == 0


@pytest.mark.asyncio
async def test_ensure_home_null_actor_refused(app_conn, owner_conn) -> None:
    """A session with no uc_uid bound: the actor is NULL and the function
    refuses with 42501, writing nothing."""
    ws_id = str(uuid4())
    with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
        await app_conn.fetchval(_CALL, ws_id)
    assert excinfo.value.sqlstate == "42501"
    assert await owner_conn.fetchval("SELECT count(*) FROM workspaces WHERE id=$1", ws_id) == 0
