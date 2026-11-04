from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext, WorkspaceMembership
from app.schemas.members import MemberAddIn
from app.services.members import (
    InvalidInvitationError,
    LastOwnerError,
    accept_invitation,
    add_member,
    create_invitation,
    list_members,
    remove_member,
)
from app.services.workspaces import create_workspace, list_my_memberships, rename_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class WorkspaceMemberOut(BaseModel):
    uc_uid: str
    role: str


class InvitationCreatedOut(BaseModel):
    invitation_token: str
    expires_at: datetime


class MemberRemovedOut(BaseModel):
    removed: bool
    uc_uid: str


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


def _require_selected_workspace(workspace_id: UUID, ctx: AuthContext) -> None:
    """Keep path addressing aligned with the middleware-selected workspace."""
    if workspace_id != ctx.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workspace selector is not authorized for this token",
        )


def _member_out(member: Any) -> WorkspaceMemberOut:
    return WorkspaceMemberOut(uc_uid=member.user_uc_uid, role=member.role)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
async def get_workspace_members(
    workspace_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[WorkspaceMemberOut]:
    """List the active roster; any active workspace member may read it."""
    _require_selected_workspace(workspace_id, ctx)
    try:
        members = await list_members(db, workspace_id=workspace_id, uc_uid=ctx.uc_uid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return [_member_out(member) for member in members]


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_workspace_member(
    workspace_id: UUID,
    payload: MemberAddIn,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> WorkspaceMemberOut:
    """Add a known subject as a member or accept a one-time invitation."""
    try:
        if payload.invitation_token is not None:
            member = await accept_invitation(
                db,
                workspace_id=workspace_id,
                actor_uc_uid=ctx.uc_uid,
                raw_token=payload.invitation_token,
            )
        else:
            _require_selected_workspace(workspace_id, ctx)
            if payload.uc_uid is None:  # guarded by MemberAddIn's model validator
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="provide exactly one of uc_uid or invitation_token",
                )
            member = await add_member(
                db,
                workspace_id=workspace_id,
                actor_uc_uid=ctx.uc_uid,
                member_uc_uid=payload.uc_uid,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidInvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _member_out(member)


@router.post(
    "/{workspace_id}/invitations",
    response_model=InvitationCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_workspace_invitation(
    workspace_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> InvitationCreatedOut:
    """Create an owner-controlled invitation; the raw token is returned once."""
    _require_selected_workspace(workspace_id, ctx)
    try:
        created = await create_invitation(
            db, workspace_id=workspace_id, actor_uc_uid=ctx.uc_uid
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return InvitationCreatedOut(**created)


@router.delete(
    "/{workspace_id}/members/{uc_uid}",
    response_model=MemberRemovedOut,
)
async def delete_workspace_member(
    workspace_id: UUID,
    uc_uid: str,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> MemberRemovedOut:
    """Remove a member as an owner, protecting the last owner."""
    _require_selected_workspace(workspace_id, ctx)
    try:
        await remove_member(
            db,
            workspace_id=workspace_id,
            actor_uc_uid=ctx.uc_uid,
            member_uc_uid=uc_uid,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LastOwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MemberRemovedOut(removed=True, uc_uid=uc_uid)
