from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import require_scopes
from app.schemas.auth import AuthContext, MeResponse

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeResponse)
async def me(ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",)))) -> MeResponse:
    return MeResponse(
        sub=ctx.uc_uid,
        workspace_id=ctx.workspace_id,
        authorized_workspace_ids=sorted(ctx.authorized_workspace_ids),
        scopes=sorted(ctx.scopes),
        claims=ctx.claims,
    )
