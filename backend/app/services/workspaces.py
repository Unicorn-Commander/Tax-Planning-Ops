"""Multi-workspace tenancy — a user's owned/joined workspaces.

The suite SSO hands a user one *home* workspace (the token's ``workspace_id``
claim, or the self-serve ``uuid5(sub)`` derivation). This module lets a user own
SEVERAL named workspaces (e.g. a personal file + a company file) and switch
between them. ``workspace_membership`` is the source of truth for "which
workspaces may this user select", and selection is authorized against it in the
auth middleware. RLS scopes the table to the caller's uc_uid, so a user can only
ever see/manage their own memberships; ``WITH CHECK`` means they can only create
a membership for themselves.

The two write paths that touch the RLS-protected ``workspaces`` table
(create/rename) bind a session to the *target* workspace id so the workspaces
``WITH CHECK (id = current_workspace_id())`` is satisfied.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker, bind_session_context, ensure_workspace
from app.models.membership import WorkspaceMembership
from app.models.workspace import Workspace


async def _set_uc_uid(session: AsyncSession, uc_uid: str) -> None:
    """Bind only the uc_uid GUC so the membership RLS (``user_uc_uid =
    current_uc_uid()``) applies — used for user-scoped queries that don't target
    a particular workspace."""
    await session.execute(
        text("SELECT set_config('app.uc_uid', :v, true)"), {"v": uc_uid}
    )


async def is_workspace_member(uc_uid: str, workspace_id: uuid.UUID) -> bool:
    """Is this user a member of this workspace? Authoritative for authorizing a
    workspace selection that the token's claims don't already cover. Runs in its
    own uc_uid-scoped session (the auth middleware has no tenant session yet)."""
    if not uc_uid:
        return False
    async with async_session_maker() as session:
        await _set_uc_uid(session, uc_uid)
        found = await session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.deleted_at.is_(None),
            )
        )
        return found is not None


async def list_my_memberships(db: AsyncSession, *, uc_uid: str) -> list[WorkspaceMembership]:
    """The caller's workspaces (RLS already scopes to their uc_uid). Newest first;
    the home workspace, if seeded, sorts naturally by creation."""
    rows = await db.scalars(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.deleted_at.is_(None))
        .order_by(WorkspaceMembership.created_at.asc())
    )
    return list(rows.all())


async def ensure_home_membership(
    db: AsyncSession, *, uc_uid: str, workspace_id: uuid.UUID, name: str
) -> None:
    """Make sure the user's active/home workspace shows up in their switcher.

    Idempotent: inserts a membership for (uc_uid, workspace_id) if absent. Safe
    under the membership RLS — ``WITH CHECK`` requires user_uc_uid == the session
    uc_uid, which the tenant session has set."""
    if not uc_uid:
        return
    existing = await db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        WorkspaceMembership(
            user_uc_uid=uc_uid,
            workspace_id=workspace_id,
            workspace_name=name,
            role="owner",
        )
    )
    await db.flush()


async def create_workspace(*, uc_uid: str, name: str) -> dict[str, Any]:
    """Create a brand-new named workspace owned by this user.

    Binds a fresh session to the NEW workspace id (so the workspaces
    ``WITH CHECK`` passes) AND the caller's uc_uid (so the membership
    ``WITH CHECK`` passes), provisions the workspace row, and records ownership.
    """
    clean = name.strip() or "Untitled workspace"
    new_id = uuid.uuid4()
    async with async_session_maker() as session:
        # Bind to the new workspace + the caller so both RLS WITH CHECKs pass.
        await bind_session_context(session, str(new_id), uc_uid)
        await ensure_workspace(session, str(new_id), clean)
        membership = WorkspaceMembership(
            user_uc_uid=uc_uid,
            workspace_id=new_id,
            workspace_name=clean,
            role="owner",
        )
        session.add(membership)
        await session.flush()
        await session.commit()
    return {"workspace_id": new_id, "name": clean, "role": "owner"}


async def rename_workspace(*, uc_uid: str, workspace_id: uuid.UUID, name: str) -> dict[str, Any]:
    """Rename a workspace the caller owns. Verifies membership (raising
    ``PermissionError`` otherwise), updates the workspaces row (bound to that id)
    and the denormalised membership name."""
    clean = name.strip()
    if not clean:
        raise ValueError("workspace name cannot be empty")
    if not await is_workspace_member(uc_uid, workspace_id):
        raise PermissionError("not a member of this workspace")
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), uc_uid)
        await session.execute(
            update(Workspace).where(Workspace.id == workspace_id).values(name=clean)
        )
        await session.execute(
            update(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .values(workspace_name=clean)
        )
        await session.commit()
    return {"workspace_id": workspace_id, "name": clean}
