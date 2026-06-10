"""Workspace-isolation regression against a real Postgres as the NOBYPASSRLS
app role (spec DoD: prove workspace A cannot read/alter workspace B, even with
a forged id). Skips unless TPO_TEST_DATABASE_URL points at a migrated DB whose
DSN authenticates as the runtime (tax_planning_ops_app) role.

CI runs this via `pytest -m integration` with a Postgres service; the default
suite skips it so it stays portable.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

DSN = os.environ.get("TPO_TEST_DATABASE_URL")  # e.g. postgresql://tax_planning_ops_app:REMOVED@localhost:55432/tax_planning_ops
WS_A = "11111111-1111-1111-1111-1111111111aa"
WS_B = "22222222-2222-2222-2222-2222222222bb"


async def _conn():  # type: ignore[no-untyped-def]
    if not DSN:
        pytest.skip("TPO_TEST_DATABASE_URL not set")
    try:
        return await asyncpg.connect(DSN)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB unreachable: {exc}")


@pytest.mark.asyncio
async def test_rls_blocks_cross_workspace_read_and_write() -> None:
    conn = await _conn()
    try:
        # Seed workspace A + a client, as the app role under A's GUC.
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_workspace', $1, true)", WS_A)
            await conn.execute(
                "INSERT INTO workspaces (id, name) VALUES ($1, 'A') ON CONFLICT DO NOTHING", WS_A
            )
            client_id = str(uuid4())
            await conn.execute(
                "INSERT INTO client (id, workspace_id, display_name, filing_status_default, status) "
                "VALUES ($1,$2,'Alice','single','active')",
                client_id,
                WS_A,
            )

        # Under workspace B's GUC: cannot see A's client, by listing or by id.
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_workspace', $1, true)", WS_B)
            await conn.execute(
                "INSERT INTO workspaces (id, name) VALUES ($1, 'B') ON CONFLICT DO NOTHING", WS_B
            )
            assert await conn.fetchval("SELECT count(*) FROM client") == 0
            assert (
                await conn.fetchval("SELECT count(*) FROM client WHERE id = $1", client_id) == 0
            )
            # Forged cross-tenant UPDATE affects zero rows (invisible to B).
            tag = await conn.execute(
                "UPDATE client SET notes='pwned' WHERE id = $1", client_id
            )
            assert tag.endswith(" 0")
            # WITH CHECK blocks inserting a row into a foreign workspace.
            with pytest.raises(asyncpg.exceptions.PostgresError):
                await conn.execute(
                    "INSERT INTO client (id, workspace_id, display_name, filing_status_default, status) "
                    "VALUES ($1,$2,'Mallory','single','active')",
                    str(uuid4()),
                    WS_A,
                )

        # No GUC at all: zero rows (fail closed).
        assert await conn.fetchval("SELECT count(*) FROM client") == 0
    finally:
        await conn.close()
