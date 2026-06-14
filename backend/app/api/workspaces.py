from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext, WorkspaceMembership
from app.services.workspaces import create_workspace, list_my_memberships, rename_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def _out(workspace_id: UUID, name: str, role: str, active: UUID) -> WorkspaceMembership:
    return WorkspaceMembership(
        workspaceId=workspace_id,
        displayName=name,
        role=role,
        isDefault=workspace_id == active,
    )


@router.get("", response_model=list[WorkspaceMembership])
async def get_workspaces(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[WorkspaceMembership]:
    """The caller's named workspaces (RLS-scoped to their uc_uid)."""
    memberships = await list_my_memberships(db, uc_uid=ctx.uc_uid)
    return [_out(m.workspace_id, m.workspace_name, m.role, ctx.workspace_id) for m in memberships]


@router.post("", response_model=WorkspaceMembership, status_code=status.HTTP_201_CREATED)
async def post_workspace(
    payload: WorkspaceCreateIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> WorkspaceMembership:
    """Create a new named workspace owned by the caller; they can switch to it
    immediately (membership authorizes the selection)."""
    created = await create_workspace(uc_uid=ctx.uc_uid, name=payload.name)
    return _out(created["workspace_id"], created["name"], created["role"], ctx.workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceMembership)
async def patch_workspace(
    workspace_id: UUID,
    payload: WorkspaceRenameIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> WorkspaceMembership:
    """Rename a workspace the caller owns."""
    try:
        renamed = await rename_workspace(
            uc_uid=ctx.uc_uid, workspace_id=workspace_id, name=payload.name
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _out(renamed["workspace_id"], renamed["name"], "owner", ctx.workspace_id)
