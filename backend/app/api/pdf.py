from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.models.tax_year import PlanDocument
from app.schemas.auth import AuthContext
from app.schemas.pdf import BrandingIn, PlanDocumentOut
from app.services.pdf import generate_plan_pdf, upsert_branding

router = APIRouter(tags=["pdf"])


@router.put("/admin/branding")
async def put_branding(
    payload: BrandingIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:admin",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, str]:
    branding = await upsert_branding(db, workspace_id=ctx.workspace_id, payload=payload)
    return {"id": str(branding.id)}


@router.post("/plans/{plan_tax_year_id}/pdf", response_model=PlanDocumentOut)
async def post_plan_pdf(
    plan_tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> PlanDocument:
    try:
        return await generate_plan_pdf(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            plan_tax_year_id=plan_tax_year_id,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
