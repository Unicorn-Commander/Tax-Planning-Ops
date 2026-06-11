from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.entity import BusinessEntity
from app.schemas.auth import AuthContext
from app.schemas.entity import BusinessEntityIn, BusinessEntityOut
from app.services.entities import create_entity, delete_entity, list_entities

router = APIRouter(prefix="/clients/tax-years", tags=["business-entities"])


@router.get("/{tax_year_id}/business-entities", response_model=list[BusinessEntityOut])
async def get_entities(
    tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[BusinessEntity]:
    return await list_entities(db, client_tax_year_id=tax_year_id)


@router.post(
    "/{tax_year_id}/business-entities", response_model=BusinessEntityOut, status_code=201
)
async def post_entity(
    tax_year_id: UUID,
    payload: BusinessEntityIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> BusinessEntity:
    return await create_entity(
        db,
        workspace_id=ctx.workspace_id,
        actor_uc_uid=ctx.uc_uid,
        client_tax_year_id=tax_year_id,
        payload=payload,
    )


@router.delete("/{tax_year_id}/business-entities/{entity_id}", status_code=204)
async def remove_entity(
    tax_year_id: UUID,
    entity_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    try:
        await delete_entity(
            db, workspace_id=ctx.workspace_id, actor_uc_uid=ctx.uc_uid, entity_id=entity_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
