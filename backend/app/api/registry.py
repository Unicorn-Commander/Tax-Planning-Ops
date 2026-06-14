"""Agent registry + door-usage read API (spec §9.6).

Two read endpoints that make the firm shell's Desk "duty band" and Staff "door
usage" panel real instead of fixtures:

* ``GET /agents/registry`` — the app's agent-backed capability roster with
  per-capability activity derived from the audit journal.
* ``GET /agents/door-stats`` — mutating journal events grouped by the door
  (gui/console/mcp/api) they came through, over a window.

Both read REAL state (see ``app.services.registry``); nothing is fabricated.
This router only reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.registry import AgentCard, DoorCount, DoorStatsOut, RegistryOut
from app.services.registry import agent_registry, door_stats

router = APIRouter(prefix="/agents", tags=["registry"])


@router.get("/registry", response_model=RegistryOut)
async def get_registry(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> RegistryOut:
    """The roster of agent-backed capabilities (Strategist, Book Scanner, Plan
    Proposer, Intake/OCR, Quarterly) with each one's latest journal activity and
    available/idle status. RLS scopes the journal read to the caller's workspace.
    """
    roster = await agent_registry(db, workspace_id=ctx.workspace_id)
    return RegistryOut(agents=[AgentCard.model_validate(row) for row in roster])


@router.get("/door-stats", response_model=DoorStatsOut)
async def get_door_stats(
    window_days: int = Query(
        30, ge=1, le=365, description="Look-back window in days for journal events."
    ),
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> DoorStatsOut:
    """Mutating journal events grouped by the door they came through, over the
    last ``window_days``. Provenance of mutating actions (signs, reconciles,
    confirms, plan writes) — not all read traffic. RLS scopes the read."""
    stats = await door_stats(db, workspace_id=ctx.workspace_id, window_days=window_days)
    return DoorStatsOut(
        total=stats["total"],
        by_door=[DoorCount(**item) for item in stats["by_door"]],
        window_days=stats["window_days"],
    )
