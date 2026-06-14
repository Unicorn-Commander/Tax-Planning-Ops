from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.realized import RealizedOutcomeOut, RealizedRollupOut, RealizeIn
from app.services.realized import list_realized, reconcile, workspace_rollup

router = APIRouter(tags=["realized"])


@router.get("/plans/{client_tax_year_id}/realized", response_model=list[RealizedOutcomeOut])
async def get_realized(
    client_tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[RealizedOutcomeOut]:
    """Reconciled outcomes for a plan year, newest first. Each carries the
    computed ``variance_cents`` (realized − planned). RLS scopes to the
    workspace; soft-deleted rows are excluded."""
    outcomes = await list_realized(db, client_tax_year_id=client_tax_year_id)
    return [RealizedOutcomeOut.model_validate(o) for o in outcomes]


@router.post(
    "/plans/{client_tax_year_id}/realized", response_model=RealizedOutcomeOut, status_code=201
)
async def post_realized(
    client_tax_year_id: UUID,
    payload: RealizeIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> RealizedOutcomeOut:
    """Reconcile an outcome for a plan year. The planned figure is locked from
    the linked strategy's estimate (or an explicit input); the realized figure
    is operator-supplied. Appends an ``outcome.reconciled`` audit event."""
    try:
        outcome = await reconcile(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            client_tax_year_id=client_tax_year_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RealizedOutcomeOut.model_validate(outcome)


@router.get("/agents/realized-rollup", response_model=RealizedRollupOut)
async def get_realized_rollup(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> RealizedRollupOut:
    """The Book's realized counter: planned vs. realized across every reconciled
    outcome in the workspace, with a per-client breakdown."""
    rollup = await workspace_rollup(db, workspace_id=_ctx.workspace_id)
    return RealizedRollupOut.model_validate(rollup)
