"""0024 downgrade restores exactly 0022's catalog (C2).

DESTRUCTIVE to the target database's schema: it walks alembic down to 0021
and back up. It runs only when TPO_TEST_MIGRATION_DATABASE_URL is set to a
SCRATCH database (the migration/owner role; same DB the other integration
URLs use is fine, it ends at head again). Steps:

1. downgrade 0021, upgrade 0022 -> snapshot A (0022's own upgrade built it);
2. upgrade head, downgrade 0022 -> snapshot B (0024's downgrade built it);
3. assert A == B, then upgrade head.

The snapshot covers the policies on workspace_membership, workspaces and
workspace_invitation, the app role's table and column grants on them, the
columns of workspace_invitation, and every workspace_membership_* /
workspace_invitation_* function with its ACL.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

BACKEND = Path(__file__).resolve().parents[1]
TABLES = ("workspace_membership", "workspaces", "workspace_invitation")


def _migration_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_MIGRATION_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_MIGRATION_DATABASE_URL not set (scratch DB only)")
    return dsn


def _plain(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _alembic(dsn: str, *args: str) -> None:
    env = {**os.environ, "MIGRATION_DATABASE_URL": dsn}
    # Fixed argv: this interpreter + alembic + revision ids from this file.
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )


async def _snapshot(dsn: str) -> dict[str, Any]:
    conn = await asyncpg.connect(_plain(dsn))
    try:
        policies = await conn.fetch(
            """
            SELECT tablename, policyname, permissive, cmd, roles::text[] AS roles,
                   qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = ANY($1::text[])
            ORDER BY tablename, policyname
            """,
            list(TABLES),
        )
        grants = await conn.fetch(
            """
            SELECT table_name, privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public' AND grantee = 'tax_planning_ops_app'
              AND table_name = ANY($1::text[])
            ORDER BY 1, 2
            """,
            list(TABLES),
        )
        column_grants = await conn.fetch(
            """
            SELECT table_name, column_name, privilege_type
            FROM information_schema.column_privileges
            WHERE table_schema = 'public' AND grantee = 'tax_planning_ops_app'
              AND table_name = ANY($1::text[])
            ORDER BY 1, 2, 3
            """,
            list(TABLES),
        )
        columns = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'workspace_invitation'
            ORDER BY ordinal_position
            """
        )
        functions = await conn.fetch(
            """
            SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args,
                   p.prosecdef, coalesce(p.proacl::text[], '{}') AS acl
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND (p.proname LIKE 'workspace_membership_%'
                   OR p.proname LIKE 'workspace_invitation_%')
            ORDER BY 1, 2
            """
        )
        rls = await conn.fetch(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class WHERE relname = ANY($1::text[]) ORDER BY 1
            """,
            list(TABLES),
        )
    finally:
        await conn.close()
    return {
        "policies": [dict(r) for r in policies],
        "grants": [dict(r) for r in grants],
        "column_grants": [dict(r) for r in column_grants],
        "invitation_columns": [dict(r) for r in columns],
        "functions": [dict(r) for r in functions],
        "rls": [dict(r) for r in rls],
    }


def test_c2_downgrade_restores_exact_0022_catalog() -> None:
    dsn = _migration_dsn()
    try:
        _alembic(dsn, "downgrade", "0021_personal_access_tokens")
        _alembic(dsn, "upgrade", "0022_member_invitations")
        at_0022 = asyncio.run(_snapshot(dsn))
        _alembic(dsn, "upgrade", "head")
        at_head = asyncio.run(_snapshot(dsn))
        _alembic(dsn, "downgrade", "0022_member_invitations")
        after_downgrade = asyncio.run(_snapshot(dsn))
    finally:
        _alembic(dsn, "upgrade", "head")
    # The 0022 write policies are really part of the reference ...
    cmds = {
        (p["policyname"], p["cmd"])
        for p in at_0022["policies"]
        if p["tablename"] == "workspace_membership"
    }
    assert {c for _, c in cmds} == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    # ... head really differs from it ...
    assert at_head != at_0022
    # ... and the downgrade restores it exactly.
    for key in at_0022:
        assert after_downgrade[key] == at_0022[key], key
