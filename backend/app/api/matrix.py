from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.matrix import MatrixOut
from app.services.matrix import build_matrix

router = APIRouter(prefix="/agents", tags=["matrix"])


@router.get("/matrix", response_model=MatrixOut)
async def get_matrix(
    limit: int = 50,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MatrixOut:
    """The Book matrix (spec §9.8): clients × strategy-categories, each cell the
    sum of that category's engine-computed strategy estimates. Rows inherit the
    opportunity-ranked order of the book scan (never re-sorted by total tax)."""
    return MatrixOut(**await build_matrix(db, workspace_id=ctx.workspace_id, limit=limit))
