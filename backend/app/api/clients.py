from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.client import Client
from app.schemas.auth import AuthContext
from app.schemas.client import ClientCreate, ClientRead
from app.services.analysis import get_client_analysis
from app.services.clients import create_client, list_clients
from app.services.overview import get_client_overview

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/{client_id}/overview")
async def get_overview(
    client_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    try:
        return await get_client_overview(db, client_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/tax-years/{tax_year_id}/analysis")
async def get_analysis(
    tax_year_id: UUID,
    horizon_years: int = 5,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """Live planning analysis (AMT, IRMAA, multi-year, opportunities) computed
    from the latest snapshot — no stored columns required."""
    try:
        return await get_client_analysis(
            db, workspace_id=ctx.workspace_id, tax_year_id=tax_year_id, horizon_years=horizon_years
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[ClientRead])
async def get_clients(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[Client]:
    return await list_clients(db)


@router.post("", response_model=ClientRead, status_code=201)
async def post_client(
    payload: ClientCreate,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> Client:
    return await create_client(db, ctx.workspace_id, payload)
