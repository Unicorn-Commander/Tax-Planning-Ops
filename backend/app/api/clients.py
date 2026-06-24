from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.integrations.accounting_ops import (
    AccountingOpsAuthError,
    AccountingOpsDisabledError,
    AccountingOpsUnavailableError,
    AccountingOpsWorkspaceNotFoundError,
)
from app.models.client import Client
from app.schemas.auth import AuthContext
from app.schemas.client import ClientCreate, ClientRead
from app.services.analysis import get_client_analysis
from app.services.clients import create_client, list_clients
from app.services.overview import get_client_overview
from app.services.source_documents import (
    get_tax_documents,
    set_accounting_ops_link,
    sync_tax_documents_from_accounting_ops,
)

router = APIRouter(prefix="/clients", tags=["clients"])


class AccountingOpsLinkIn(BaseModel):
    """Link a client to its Accounting-Ops document vault. Empty values unlink."""

    accounting_ops_workspace_id: str | None = None
    accounting_ops_entity_id: str | None = None


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


# --- Accounting-Ops source-document federation (AO owns OCR; TPO consumes) -----


@router.post("/{client_id}/accounting-ops-link")
async def link_accounting_ops(
    client_id: UUID,
    payload: AccountingOpsLinkIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """Link a client to its Accounting-Ops document vault (the AO workspace +
    personal entity) so source tax documents can be pulled over federation."""
    try:
        return await set_accounting_ops_link(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            client_id=client_id,
            accounting_ops_workspace_id=payload.accounting_ops_workspace_id,
            accounting_ops_entity_id=payload.accounting_ops_entity_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/tax-years/{tax_year_id}/tax-documents")
async def list_tax_documents(
    tax_year_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """The stored per-year manifest of Accounting-Ops source documents (no AO
    call). Empty until first synced."""
    try:
        return await get_tax_documents(db, tax_year_id=tax_year_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/tax-years/{tax_year_id}/sync-tax-documents")
async def sync_tax_documents(
    tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Pull the linked client's Accounting-Ops source documents for this tax year
    into the per-year manifest. 503 if the integration is off, 502 if AO is
    unreachable or hasn't authorized the federation actor, 400 if not linked."""
    try:
        return await sync_tax_documents_from_accounting_ops(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            tax_year_id=tax_year_id,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AccountingOpsWorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountingOpsDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (AccountingOpsAuthError, AccountingOpsUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
