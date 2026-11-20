"""Backfill workspaces.org_id from an operator-supplied mapping file (33982835).

Binds every workspace whose org_id is NULL (created before the entitlement
door, PR #15) to the Ops-Center org the OWNER of Ops-Center mapped it to.
Ops-Center serves no endpoint that answers, with an operator credential,
for OTHER users' orgs (its org routes answer only for the caller's own
session), so this script does NOT ask Ops-Center anything: it validates and
applies a mapping file (workspace_id -> org_id) produced by the Ops-Center
owner.

Mapping file — CSV with a ``workspace_id,org_id`` header:

  workspace_id,org_id
  0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d,11111111-2222-4333-8444-555555555555

or JSON: {"<workspace_id>": "<org_id>", ...} or
[{"workspace_id": ..., "org_id": ...}, ...]. Both ids lowercase-canonical UUIDs.

LIVE checks (what Tax owns): workspace exists, org_id NULL, owner-role
member present, org_id a canonical UUID, no workspace listed twice. Invalid
rows are refused, left NULL and listed with a reason. The Ops-Center side
(org exists, holds tax_ops_access, the owner is a member) is TRUSTED from
the mapping file — the run prints that note. Each bind is its own guarded
transaction (UPDATE ... WHERE id = $1 AND org_id IS NULL, exactly one row,
else rollback); a bound org is never overwritten. Idempotent: a re-run is a
no-op. Prints workspace ids and fixed reasons only — no emails, no bearer.

Run as the OWNER database role (the app role's RLS cannot see other
workspaces):

  export MIGRATION_DATABASE_URL=postgresql://tax_planning_ops_owner:REMOVED@host/db
  python scripts/backfill_workspace_org.py --mapping-file mapping.csv --dry-run
  python scripts/backfill_workspace_org.py --mapping-file mapping.csv

No network: the only writes are the guarded binds above.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.services.org_backfill import (  # noqa: E402
    TRUSTED_NOTE,
    BackfillResult,
    MappingFileError,
    Refusal,
    backfill_workspace_orgs,
    load_mapping,
)


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


def _report(result: BackfillResult, refused_at_load: list[Refusal], dry_run: bool) -> None:
    mode = "DRY RUN (nothing written)" if dry_run else "APPLIED"
    verb = "would bind" if dry_run else "bound"
    print(f"workspace-org backfill — {mode}")
    print(f"{verb} ({len(result.bound)}): " + (", ".join(str(v) for v in result.bound) or "-"))
    refused = [f"{r.ref}: {r.reason}" for r in refused_at_load] + [
        f"{r.ref}: {r.reason}" for r in result.refused
    ]
    print(f"refused, left NULL ({len(refused)}):")
    for line in refused:
        print(f"  {line}")
    print(f"trusted: {TRUSTED_NOTE}")


async def _run(database_url: str, mapping_path: Path, dry_run: bool) -> int:
    try:
        rows, refused_at_load = load_mapping(mapping_path)
    except MappingFileError as exc:
        print(f"mapping file refused: {exc}")
        return 2
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        result = await backfill_workspace_orgs(factory, rows, dry_run=dry_run)
    finally:
        await engine.dispose()
    _report(result, refused_at_load, dry_run)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--mapping-file",
        required=True,
        type=Path,
        help="CSV or JSON file mapping workspace_id -> org_id (from the Ops-Center owner)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report only; write nothing",
    )
    p.add_argument(
        "--database-url",
        default=None,
        help="owner-role DSN (default: $MIGRATION_DATABASE_URL; never $DATABASE_URL)",
    )
    args = p.parse_args()
    return asyncio.run(_run(_owner_url(args.database_url), args.mapping_file, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
