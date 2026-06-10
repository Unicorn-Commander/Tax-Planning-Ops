from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import require_scopes
from app.schemas.auth import AuthContext

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> dict[str, bool]:
    return {"ok": True}


@router.get("/livez", include_in_schema=False)
async def livez() -> dict[str, bool]:
    return {"ok": True}
