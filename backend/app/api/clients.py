from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.client import Client
from app.schemas.auth import AuthContext
from app.schemas.client import ClientCreate, ClientRead
from app.services.clients import create_client, list_clients

router = APIRouter(prefix="/clients", tags=["clients"])


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
