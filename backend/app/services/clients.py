from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.schemas.client import ClientCreate


async def create_client(db: AsyncSession, workspace_id: UUID, payload: ClientCreate) -> Client:
    client = Client(workspace_id=workspace_id, **payload.model_dump())
    db.add(client)
    await db.flush()
    await db.refresh(client)
    return client


async def list_clients(db: AsyncSession) -> list[Client]:
    result = await db.execute(select(Client).order_by(Client.display_name))
    return list(result.scalars().all())
