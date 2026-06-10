from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.quarterly import ComputeQuarterlyRequest, QuarterlyRecordOut, QuarterlyResultOut
from app.services.quarterly import compute_quarterly_for_plan

router = APIRouter(prefix="/quarterly", tags=["quarterly"])


@router.post("/{plan_tax_year_id}/compute", response_model=QuarterlyResultOut)
async def post_compute_quarterly(
    plan_tax_year_id: UUID,
    payload: ComputeQuarterlyRequest,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> QuarterlyResultOut:
    try:
        basis, annual, records = await compute_quarterly_for_plan(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            plan_tax_year_id=plan_tax_year_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return QuarterlyResultOut(
        safe_harbor_basis=basis,
        required_annual_payment_cents=annual,
        quarters=[
            QuarterlyRecordOut(
                id=record.id,
                quarter=record.quarter,
                due_date=record.due_date.date(),
                required_payment_cents=record.required_payment_cents,
                payment_made_cents=record.payment_made_cents,
                unpaid_rollforward_cents=record.unpaid_rollforward_cents,
                status=record.status,
                annualized_income_cents=record.annualized_income_cents,
            )
            for record in records
        ],
    )
