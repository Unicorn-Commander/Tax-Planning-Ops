from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.engagement import BrandingOut, EngagementOut, FeeIn
from app.services.engagement import get_branding, get_engagement, upsert_engagement

router = APIRouter(tags=["engagement"])


@router.get("/admin/branding", response_model=BrandingOut | None)
async def get_admin_branding(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> BrandingOut | None:
    """The firm letterhead (name, logo, color, signature) read straight from the
    workspace's branding row — the real source for the Memo/Present letterhead,
    so it isn't a hardcoded default. Returns 200 with a ``null`` body when no
    branding has been set yet, letting the UI fall back to its own default
    cleanly (rather than treating an absence as a 404 error)."""
    branding = await get_branding(db, workspace_id=_ctx.workspace_id)
    return BrandingOut.model_validate(branding) if branding is not None else None


@router.get("/admin/engagements/{client_id}/fee", response_model=EngagementOut | None)
async def get_engagement_fee(
    client_id: UUID,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> EngagementOut | None:
    """The client's advisory-fee engagement. Returns 200 with a ``null`` body
    when no fee is on file yet (the Present plate then omits the net-of-fee
    framing rather than implying a $0 fee)."""
    engagement = await get_engagement(db, client_id=client_id)
    return EngagementOut.model_validate(engagement) if engagement is not None else None


@router.put("/admin/engagements/{client_id}/fee", response_model=EngagementOut)
async def put_engagement_fee(
    client_id: UUID,
    payload: FeeIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> EngagementOut:
    """Set (create or update) the client's advisory fee. ``fee_cents`` is the
    operator-supplied integer-cents amount — it is recorded verbatim, never
    computed from the plan. 404 if the client doesn't exist in the workspace."""
    try:
        engagement = await upsert_engagement(
            db, workspace_id=ctx.workspace_id, client_id=client_id, payload=payload
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EngagementOut.model_validate(engagement)
