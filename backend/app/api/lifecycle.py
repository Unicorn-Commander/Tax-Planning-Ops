from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.services.lifecycle import finalize_plan, verify_workspace_audit_chain

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


@router.post("/plans/{plan_tax_year_id}/finalize")
async def post_finalize_plan(
    plan_tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, str]:
    try:
        plan = await finalize_plan(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            plan_tax_year_id=plan_tax_year_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"client_tax_year_id": str(plan.id), "finalized_at": str(plan.finalized_at)}


@router.get("/audit/verify")
async def get_audit_verify(
    ctx: AuthContext = Depends(require_scopes(("taxplan:admin",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, bool]:
    return {"valid": await verify_workspace_audit_chain(db, ctx.workspace_id)}
