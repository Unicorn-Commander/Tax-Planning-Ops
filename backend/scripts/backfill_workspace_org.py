"""Backfill workspaces.org_id from each owner's Ops-Center org (task 33982835).

Binds every workspace whose org_id is NULL (created before the entitlement
door, PR #15) to its OWNER's Ops-Center org, ONLY when unambiguous: exactly
one owner-role member, and Ops-Center answers exactly one org where that
owner is owner or admin. Ambiguous workspaces (no owner, 2+ owners, 0 or 2+
orgs) are left NULL and listed; an Ops-Center failure skips the workspace.
Each bind is its own guarded transaction (UPDATE ... WHERE id = $1 AND
org_id IS NULL, exactly one row, else rollback); a bound org is never
overwritten. Idempotent: a re-run is a no-op. Prints a summary with workspace
ids only — no emails, no owner names, no bearer.

Run as the OWNER database role (the app role's RLS cannot see other
workspaces), with the Ops-Center URL configured and an operator bearer that
Ops-Center accepts for org-membership reads:

  export MIGRATION_DATABASE_URL=postgresql://tax_planning_ops_owner:REMOVED@host/db
  export OPS_CENTER_URL=https://ops-center.example.com
  export OPS_CENTER_BEARER=<operator token>   # env only: never argv, never printed
  python scripts/backfill_workspace_org.py --dry-run   # counts only, writes nothing
  python scripts/backfill_workspace_org.py             # the guarded backfill

Read-only against Ops-Center; the only writes are the guarded binds above.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.control_plane import owner_admin_orgs  # noqa: E402
from app.services.org_backfill import backfill_workspace_orgs  # noqa: E402


def _owner_url(explicit: str | None) -> str:
    # Deliberately NO DATABASE_URL fallback: that is the NOBYPASSRLS app role,
    # whose RLS would silently show zero unbound workspaces.
    url = explicit or os.environ.get("MIGRATION_DATABASE_URL") or ""
    if not url:
        print("Set MIGRATION_DATABASE_URL (owner role) or pass --database-url.")
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def _ids(label: str, values: list[Any]) -> str:
    return f"{label} ({len(values)}): " + (", ".join(str(v) for v in values) if values else "-")


async def _run(database_url: str, dry_run: bool) -> int:
    settings = get_settings()
    bearer = os.environ.get("OPS_CENTER_BEARER", "")
    if not settings.OPS_CENTER_URL.strip():
        print("OPS_CENTER_URL is not set: nothing can be asked, refusing to run.")
        return 2
    if not bearer:
        print("OPS_CENTER_BEARER is not set: nothing can be asked, refusing to run.")
        return 2

    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:

        async def ask_orgs(uc_uid: str) -> list[str] | None:
            return await owner_admin_orgs(bearer=bearer, uc_uid=uc_uid, settings=settings)

        result = await backfill_workspace_orgs(factory, ask_orgs, dry_run=dry_run)
    finally:
        await engine.dispose()

    mode = "DRY RUN (nothing written)" if dry_run else "APPLIED"
    print(f"workspace-org backfill — {mode}")
    print(_ids("bound", result.bound))
    print(_ids("ambiguous (left NULL)", result.ambiguous))
    print(_ids("skipped (Ops-Center unavailable, left NULL)", result.skipped))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="read and ask only; print counts, write nothing",
    )
    p.add_argument(
        "--database-url",
        default=None,
        help="owner-role DSN (default: $MIGRATION_DATABASE_URL; never $DATABASE_URL)",
    )
    args = p.parse_args()
    return asyncio.run(_run(_owner_url(args.database_url), args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
