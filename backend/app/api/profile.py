from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.profile import ClientPlanningProfile
from app.schemas.auth import AuthContext
from app.schemas.profile import PlanningProfileIn, PlanningProfileOut
from app.services.profile import get_profile, upsert_profile

router = APIRouter(prefix="/clients", tags=["planning-profile"])


@router.get("/{client_id}/planning-profile", response_model=PlanningProfileOut | None)
async def read_planning_profile(
    client_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClientPlanningProfile | None:
    """The client's planning objectives, or null if none captured yet."""
    return await get_profile(db, client_id=client_id)


@router.put("/{client_id}/planning-profile", response_model=PlanningProfileOut)
async def put_planning_profile(
    client_id: UUID,
    payload: PlanningProfileIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClientPlanningProfile:
    try:
        return await upsert_profile(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            client_id=client_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
