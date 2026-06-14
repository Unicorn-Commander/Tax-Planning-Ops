from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.models.workspace import Workspace
from app.schemas.auth import AuthContext, MeResponse, WorkspaceMembership
from app.services.workspaces import ensure_home_membership, list_my_memberships

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeResponse)
async def me(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MeResponse:
    # Make sure the active/home workspace shows up in the switcher, named from
    # the workspaces row (visible under RLS for the active workspace).
    active_name = await db.scalar(
        select(Workspace.name).where(Workspace.id == ctx.workspace_id)
    )
    await ensure_home_membership(
        db,
        uc_uid=ctx.uc_uid,
        workspace_id=ctx.workspace_id,
        name=active_name or f"Workspace {str(ctx.workspace_id)[:8]}",
    )
    memberships = await list_my_memberships(db, uc_uid=ctx.uc_uid)
    workspaces = [
        WorkspaceMembership(
            workspaceId=m.workspace_id,
            displayName=m.workspace_name,
            role=m.role,
            isDefault=m.workspace_id == ctx.workspace_id,
        )
        for m in memberships
    ]
    # Union the membership ids with the claim-authorized ids so a freshly created
    # workspace is selectable immediately.
    authorized: list[UUID] = sorted(
        set(ctx.authorized_workspace_ids) | {m.workspace_id for m in memberships}
    )
    return MeResponse(
        sub=ctx.uc_uid,
        workspace_id=ctx.workspace_id,
        authorized_workspace_ids=authorized,
        workspaces=workspaces,
        scopes=sorted(ctx.scopes),
        claims=ctx.claims,
    )
