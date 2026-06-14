"""Live planning endpoints — the Lab's what-if instruments over the real engines.

Every figure returned here is an engine recompute (Form 1040 / the optimizers),
never a flat estimate. Recompute, EMR sweep, Roth crossover, and the S-corp
salary curve all run the deterministic engines under the caller's tenant DB.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.scenarios import (
    EMRSweepIn,
    EMRSweepOut,
    RothOptimizeOut,
    ScenarioRecomputeIn,
    ScenarioRecomputeOut,
    ScorpOptimizeOut,
)
from app.services.scenarios import emr_sweep, optimize_roth, optimize_scorp, recompute

router = APIRouter(prefix="/agents", tags=["scenarios"])


@router.post("/clients/tax-years/{tax_year_id}/scenario")
async def post_scenario(
    tax_year_id: UUID,
    body: ScenarioRecomputeIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScenarioRecomputeOut:
    """Apply a structural what-if (absolute sets / signed deltas in cents) to the
    client's current situation and return the REAL before/after tax delta."""
    try:
        rec = await recompute(
            db,
            tax_year_id=tax_year_id,
            set_fields=body.set_fields,
            delta_fields=body.delta_fields,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ScenarioRecomputeOut(
        base_total_tax_cents=rec.base.total_tax_cents,
        scenario_total_tax_cents=rec.scenario.total_tax_cents,
        tax_delta_cents=rec.tax_delta_cents,
        agi_delta_cents=rec.agi_delta_cents,
        taxable_income_delta_cents=rec.taxable_income_delta_cents,
        marginal_rate_base=str(rec.marginal_rate_base),
        marginal_rate_scenario=str(rec.marginal_rate_scenario),
        savings=rec.tax_delta_cents < 0,
    )


@router.post("/clients/tax-years/{tax_year_id}/emr-sweep")
async def post_emr_sweep(
    tax_year_id: UUID,
    body: EMRSweepIn | None = None,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> EMRSweepOut:
    """Sweep one income field upward and return the EFFECTIVE marginal rate at
    each step (Δtax/Δincome — captures phase-outs and cliffs), plus IRMAA/NIIT
    threshold overlays."""
    params = body or EMRSweepIn()
    try:
        result = await emr_sweep(
            db,
            tax_year_id=tax_year_id,
            start_cents=params.start_cents,
            step_cents=params.step_cents,
            steps=params.steps,
            field=params.field,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EMRSweepOut(**result)


@router.post("/clients/tax-years/{tax_year_id}/optimize/roth")
async def post_optimize_roth(
    tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> RothOptimizeOut:
    """Roth-conversion bracket fill (IRMAA-aware) with an engine-recomputed
    crossover trace."""
    try:
        result = await optimize_roth(db, tax_year_id=tax_year_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RothOptimizeOut(**result)


@router.post("/clients/tax-years/{tax_year_id}/optimize/scorp")
async def post_optimize_scorp(
    tax_year_id: UUID,
    entity_id: UUID | None = None,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScorpOptimizeOut:
    """S-corp reasonable-salary optimization (payroll vs §199A QBI) with an
    engine-recomputed salary→tax curve. 404 if there is no S-corp entity."""
    try:
        result = await optimize_scorp(db, tax_year_id=tax_year_id, entity_id=entity_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ScorpOptimizeOut(**result)
