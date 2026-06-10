from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.strategy import ClientStrategy, StrategyLibrary
from app.schemas.auth import AuthContext
from app.schemas.strategy import (
    AddClientStrategyRequest,
    ClientStrategyOut,
    StrategyLibraryIn,
    StrategyLibraryOut,
)
from app.services.strategies import (
    add_client_strategy,
    list_strategy_library,
    upsert_strategy_library,
)

router = APIRouter(tags=["strategies"])


@router.get("/strategy-library", response_model=list[StrategyLibraryOut])
async def get_strategy_library(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[StrategyLibrary]:
    return await list_strategy_library(db, ctx.workspace_id)


@router.put("/admin/strategy-library", response_model=StrategyLibraryOut)
async def put_strategy_library(
    payload: StrategyLibraryIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:admin",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> StrategyLibrary:
    return await upsert_strategy_library(
        db,
        workspace_id=ctx.workspace_id,
        actor_uc_uid=ctx.uc_uid,
        payload=payload,
    )


@router.post(
    "/plans/{client_tax_year_id}/strategies",
    response_model=ClientStrategyOut,
    status_code=201,
)
async def post_client_strategy(
    client_tax_year_id: UUID,
    payload: AddClientStrategyRequest,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClientStrategy:
    try:
        return await add_client_strategy(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            client_tax_year_id=client_tax_year_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
