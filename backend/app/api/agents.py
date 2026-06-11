from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.services.book_scan import scan_book
from app.services.planning_agent import propose_plan

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/scan-book")
async def get_scan_book(
    limit: int = 25,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict[str, object]]:
    return await scan_book(db, ctx.workspace_id, limit)


@router.post("/clients/{client_tax_year_id}/propose-plan")
async def post_propose_plan(
    client_tax_year_id: UUID,
    illustrative_amount_cents: int | None = None,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Propose-only: returns a prioritized plan (engine-computed savings + an
    LLM-authored narrative). Never writes a strategy — the advisor applies via
    the existing approval path."""
    try:
        return await propose_plan(
            db,
            workspace_id=ctx.workspace_id,
            client_tax_year_id=client_tax_year_id,
            settings=settings,
            illustrative_amount_cents=illustrative_amount_cents,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
