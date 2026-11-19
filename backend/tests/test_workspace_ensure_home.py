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
    await app_conn.execute(
        "SELECT workspace_membership_ensure_home($1, 'Fictional Cedar Tax Group')", ws_id
    )
    assert (
        await owner_conn.fetchval(
            "SELECT count(*) FROM workspace_membership WHERE workspace_id=$1", ws_id
        )
        == 1
    )
    assert (
        await owner_conn.fetchval(
            "SELECT count(*) FROM workspace_membership "
            "WHERE workspace_id=$1 AND user_uc_uid='fictional-caller-t9'", ws_id
        )
        == 0
    )
    assert await owner_conn.fetchval("SELECT count(*) FROM workspaces WHERE id=$1", ws_id) == 1


@pytest.mark.asyncio
async def test_ensure_home_null_actor_refused(app_conn, owner_conn) -> None:
    """A session with no uc_uid bound: the actor is NULL and the function
    refuses with 42501, writing nothing."""
    ws_id = str(uuid4())
    # Fail closed: with NO uc_uid bound at all (current_uc_uid() -> NULL) the
    # function refuses with 42501 and writes nothing.
    with pytest.raises(asyncpg.exceptions.PostgresError) as excinfo:
        await app_conn.execute(
            "SELECT workspace_membership_ensure_home($1, 'Fictional Cedar Tax Group')", ws_id
        )
    assert excinfo.value.sqlstate == "42501"
    assert await owner_conn.fetchval("SELECT count(*) FROM workspaces WHERE id=$1", ws_id) == 0
