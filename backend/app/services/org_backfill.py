"""Workspace-org backfill (task 33982835): bind pre-#15 workspaces to their
owner's Ops-Center org, guarded and idempotent.

Workspaces created before the entitlement door (PR #15, alembic 0023) have
``workspaces.org_id`` NULL and are refused once ``ENTITLEMENT_CHECK_ENABLED``
is on. This backfill binds each such workspace to its OWNER's org ONLY when
that is unambiguous:

* the workspace has exactly one owner-role member (``workspace_membership``,
  ``role = 'owner'``, not deleted); and
* Ops-Center answers exactly ONE org where that owner is owner or admin
  (``ask_orgs`` — the same read-only trust model as the door; the org is
  never taken from a request or argument value).

Anything ambiguous (no owner, 2+ owners, 0 or 2+ orgs) leaves the workspace
NULL and lists it. A failed Ops-Center read SKIPS the workspace (retryable;
distinct from "ambiguous"). Each write is its own guarded transaction:
``UPDATE workspaces SET org_id = :org WHERE id = :ws AND org_id IS NULL`` —
exactly one row or rollback; a non-NULL org_id is never overwritten (the
0023 trigger forbids changing a bound org too). A re-run finds no NULL rows
and is a no-op. ``dry_run`` reads and asks but writes nothing.

Runs as the OWNER database role (the app role's RLS cannot see other
workspaces); the CLI lives in scripts/backfill_workspace_org.py. No migration,
no data change here — this module only implements the guarded procedure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# uc_uid -> the canonical org uuids where they are owner/admin, or None when
# Ops-Center gave no answer to trust (refused/unreachable/malformed).
AskOrgs = Callable[[str], Awaitable["list[str] | None"]]

_SELECT_UNBOUND = text("SELECT id FROM workspaces WHERE org_id IS NULL ORDER BY id")

_SELECT_OWNERS = text(
    "SELECT DISTINCT user_uc_uid FROM workspace_membership "
    "WHERE workspace_id = :ws AND role = 'owner' AND deleted_at IS NULL"
)

# Guarded bind: the WHERE repeats the NULL precondition, so a row bound by
# someone else in between matches zero rows and rolls the transaction back.
_BIND = text("UPDATE workspaces SET org_id = :org WHERE id = :ws AND org_id IS NULL")


@dataclass
class BackfillResult:
    """Workspace ids per outcome (ids only — never emails or owner names)."""

    bound: list[UUID] = field(default_factory=list)
    ambiguous: list[UUID] = field(default_factory=list)
    skipped: list[UUID] = field(default_factory=list)


async def _unbound_ids(session: AsyncSession) -> list[UUID]:
    rows = await session.execute(_SELECT_UNBOUND)
    return [row[0] for row in rows.all()]


async def _owner_uids(session: AsyncSession, workspace_id: UUID) -> Sequence[str]:
    rows = await session.execute(_SELECT_OWNERS, {"ws": str(workspace_id)})
    return [row[0] for row in rows.all()]


async def backfill_workspace_orgs(
    session_factory: async_sessionmaker[AsyncSession],
    ask_orgs: AskOrgs,
    *,
    dry_run: bool = False,
) -> BackfillResult:
    """Bind every unbound workspace whose owner's org is unambiguous.

    ``session_factory`` must be bound to the OWNER role (RLS bypass);
    ``ask_orgs`` is the read-only Ops-Center question (None = no answer to
    trust). One guarded transaction per workspace; never overwrites a bound
    org; idempotent; ``dry_run`` writes nothing."""
    result = BackfillResult()
    async with session_factory() as session:
        workspace_ids = await _unbound_ids(session)

    for workspace_id in workspace_ids:
        async with session_factory() as session:
            owners = await _owner_uids(session, workspace_id)
        if len(owners) != 1:
            # No owner, or several: whose org would it be? Ambiguous by design.
            result.ambiguous.append(workspace_id)
            continue
        orgs = await ask_orgs(owners[0])
        if orgs is None:
            # Ops-Center gave no answer to trust: skip (retryable), leave NULL.
            result.skipped.append(workspace_id)
            continue
        if len(orgs) != 1:
            result.ambiguous.append(workspace_id)
            continue
        if dry_run:
            result.bound.append(workspace_id)
            continue
        async with session_factory() as session:
            outcome = cast(
                CursorResult[Any],
                await session.execute(_BIND, {"org": orgs[0], "ws": str(workspace_id)}),
            )
            if outcome.rowcount == 1:
                await session.commit()
                result.bound.append(workspace_id)
            else:
                # Someone bound it in between (or it vanished): roll back, skip.
                await session.rollback()
                result.skipped.append(workspace_id)
    return result
