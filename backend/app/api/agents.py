from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.services.book_scan import scan_book

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/scan-book")
async def get_scan_book(
    limit: int = 25,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict[str, object]]:
    return await scan_book(db, ctx.workspace_id, limit)
