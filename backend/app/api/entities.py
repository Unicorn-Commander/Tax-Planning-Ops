from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.models.entity import BusinessEntity
from app.schemas.auth import AuthContext
from app.schemas.entity import BookToTaxAdjustmentIn, BusinessEntityIn, BusinessEntityOut
from app.services.entities import (
    create_entity,
    delete_entity,
    list_entities,
    set_book_to_tax_adjustment,
    sync_entity_from_accounting_ops,
)

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


@router.post("/{tax_year_id}/business-entities/{entity_id}/sync-accounting-ops")
async def sync_entity_accounting_ops(
    tax_year_id: UUID,
    entity_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Pull the linked Accounting-Ops workspace's P&L net income into this
    entity. Gated: 503 if the integration is off, 502 if AO is unreachable or
    hasn't yet authorized the Tax-Planning-Ops federation actor."""
    try:
        return await sync_entity_from_accounting_ops(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            entity_id=entity_id,
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


@router.post("/{tax_year_id}/business-entities/{entity_id}/book-to-tax-adjustment")
async def set_entity_book_to_tax(
    tax_year_id: UUID,
    entity_id: UUID,
    payload: BookToTaxAdjustmentIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    """Set the net Schedule M-1 book-to-tax adjustment (book net income →
    corporate taxable income) on a C-corp entity — reconciles a synced book
    figure to taxable income."""
    try:
        return await set_book_to_tax_adjustment(
            db,
            workspace_id=ctx.workspace_id,
            actor_uc_uid=ctx.uc_uid,
            entity_id=entity_id,
            adjustment_cents=payload.book_to_tax_adjustment_cents,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
