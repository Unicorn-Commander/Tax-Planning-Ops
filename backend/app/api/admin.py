from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.tax_config import TaxBracketSet
from app.schemas.auth import AuthContext
from app.schemas.tax_config import TaxBracketSetIn, TaxBracketSetOut
from app.services.tax_config import list_bracket_sets, upsert_bracket_set

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tax-bracket-sets", response_model=list[TaxBracketSetOut])
async def get_tax_bracket_sets(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:admin",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TaxBracketSet]:
    return await list_bracket_sets(db)


@router.put("/tax-bracket-sets", response_model=TaxBracketSetOut)
async def put_tax_bracket_set(
    payload: TaxBracketSetIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:admin",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> TaxBracketSet:
    try:
        return await upsert_bracket_set(
            db, payload, workspace_id=ctx.workspace_id, actor_uc_uid=ctx.uc_uid
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
