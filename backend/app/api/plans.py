from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.tax_year import TaxSituationSnapshot
from app.schemas.auth import AuthContext
from app.schemas.plans import CreatePlanRequest, UpdateAssumptionsRequest
from app.services.plans import create_plan_from_base, update_plan_assumptions

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("", status_code=201)
async def post_plan(
    payload: CreatePlanRequest,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, UUID]:
    try:
        plan_year, snapshot = await create_plan_from_base(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            base_tax_year_id=payload.base_tax_year_id,
            target_tax_year=payload.target_tax_year,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"client_tax_year_id": plan_year.id, "snapshot_id": snapshot.id}


@router.patch("/{plan_tax_year_id}/assumptions")
async def patch_plan_assumptions(
    plan_tax_year_id: UUID,
    payload: UpdateAssumptionsRequest,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, int | str | UUID]:
    try:
        snapshot: TaxSituationSnapshot = await update_plan_assumptions(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            plan_tax_year_id=plan_tax_year_id,
            assumptions=payload.assumptions,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "snapshot_id": snapshot.id,
        "total_tax_cents": snapshot.total_tax_cents,
        "marginal_rate": str(snapshot.marginal_rate),
        "effective_rate": str(snapshot.effective_rate),
    }
