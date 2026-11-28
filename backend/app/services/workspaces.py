"""Multi-workspace tenancy — a user's owned/joined workspaces.

The suite SSO hands a user one *home* workspace (the token's ``workspace_id``
claim, or the self-serve ``uuid5(sub)`` derivation). This module lets a user own
SEVERAL named workspaces (e.g. a personal file + a company file) and switch
between them. ``workspace_membership`` is the source of truth for "which
workspaces may this user select", and selection is authorized against it in the
auth middleware.

Since migration 0024 the app role is SELECT-only on
``workspace_membership``: every write goes through the migration's SECURITY
DEFINER functions (``workspace_membership_create_workspace`` for a fresh
named workspace, ``workspace_membership_ensure_home`` for the self-serve
home row; the member functions in ``app.services.members`` for the rest).
The definer checks re-verify the actor against ``current_uc_uid()`` in the
database.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError as SAProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker, bind_session_context
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


async def workspace_org(workspace_id: uuid.UUID) -> uuid.UUID | None:
    """The Ops-Center org a workspace is bound to (None: no row, or not bound).

    Server-side truth for the entitlement door: the org it asks Ops-Center
    about is read here, never taken from the request. Runs in its own session
    bound to that workspace (the workspaces RLS only shows the bound row)."""
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), None)
        return await session.scalar(
            select(Workspace.org_id).where(Workspace.id == workspace_id)
        )


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
    db: AsyncSession,
    *,
    uc_uid: str,
    claims: dict[str, Any],
    workspace_id: uuid.UUID,
    name: str,
    org_id: uuid.UUID | None = None,
) -> bool:
    """Create-and-claim the caller's self-serve workspace.

    Acts ONLY when workspace_id is the caller's own self-serve workspace (uuid5
    of sub, no explicit workspace claim); for any claimed workspace (the
    token's workspace_id, a PAT's workspace_scope, a header selection) it
    writes NOTHING and changes no role.

    The 0024 definer ``workspace_membership_ensure_home`` inserts the
    workspaces row and, only if THIS call inserted it, the caller's owner
    membership. An existing workspace is never claimed, so it has to run
    before anything else provisions the row: ``get_tenant_db`` calls this
    ahead of ``ensure_workspace``. Repeat calls are no-ops. Returns True when
    it claimed.

    ``claims`` must be the request's VERIFIED claims (``ctx.claims``): the
    self-serve workspace the auth middleware actually resolves is
    ``uuid5(claims["sub"])``, and ``ctx.uc_uid`` is ``claims.uc_uid or sub`` —
    so deriving from ``uc_uid`` alone would never match when the two differ
    (the production shape) and the home row would never be written."""
    if not uc_uid:
        return False
    from app.core.auth import derive_self_serve_workspace

    if derive_self_serve_workspace(claims) != workspace_id:
        return False
    # The definer binds the claim to the active workspace + uc_uid GUCs.
    await bind_session_context(db, str(workspace_id), uc_uid)
    try:
        claimed = await db.scalar(
            text("SELECT workspace_membership_ensure_home(:ws, :name, :org)"),
            {"ws": workspace_id, "name": name, "org": org_id},
        )
    except SAProgrammingError as exc:
        pgerr = getattr(exc, "orig", None)
        if pgerr is not None and getattr(pgerr, "sqlstate", None) == "42501":
            raise PermissionError(str(pgerr)) from exc
        raise
    db.expire_all()
    return bool(claimed)


async def create_workspace(
    *,
    uc_uid: str,
    name: str,
    org_id: uuid.UUID | None = None,
    claims: dict[str, Any],
) -> dict[str, Any]:
    """Create a brand-new named workspace owned by this user.

    Runs entirely through the 0024 SECURITY DEFINER function: it checks the
    actor against current_uc_uid(), provisions the workspace row with a
    server-generated id, and records the caller as owner. The session's GUCs
    are bound to the CALLER's context first (the function never trusts its
    arguments for authorization). ``org_id`` (the org the creating request was
    entitled in) binds the new workspace to that Ops-Center org.

    ``claims`` are the caller's VERIFIED token claims: creating a workspace is
    self-serve tenant provisioning, so a non-user (service/M2M) principal is
    refused here as well as in the middleware (TPO-MACH-1, defense in depth)
    — this writer must hold the line even when reached from another route."""
    # Late import: app.core.auth imports this module at module level.
    from app.core.auth import caller_is_user_principal
    from app.core.config import get_settings

    if not caller_is_user_principal(claims, get_settings()):
        raise PermissionError("workspace creation requires an end-user principal")
    clean = name.strip() or "Untitled workspace"
    async with async_session_maker() as session:
        # Bind the uc_uid GUC (workspace unknown yet); the function derives the
        # actor from it and mints the owner row for the same user.
        await _set_uc_uid(session, uc_uid)
        new_id = await session.scalar(
            text(
                "SELECT workspace_membership_create_workspace("
                "current_uc_uid(), :name, :org)"
            ),
            {"name": clean, "org": org_id},
        )
        await session.commit()
    return {
        "workspace_id": str(new_id) if new_id is not None else new_id,
        "name": clean,
        "role": "owner",
    }


async def rename_workspace(*, uc_uid: str, workspace_id: uuid.UUID, name: str) -> dict[str, Any]:
    """Rename a workspace the caller owns.

    Runs through the 0024 definer ``workspace_membership_rename_workspace``:
    it requires an active owner (``PermissionError`` otherwise) and renames
    both the workspaces row and the denormalised ``workspace_name`` on every
    membership row of that workspace (what /me and the switcher show)."""
    clean = name.strip()
    if not clean:
        raise ValueError("workspace name cannot be empty")
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), uc_uid)
        try:
            await session.execute(
                text("SELECT workspace_membership_rename_workspace(:ws, :name)"),
                {"ws": workspace_id, "name": clean},
            )
        except SAProgrammingError as exc:
            pgerr = getattr(exc, "orig", None)
            if pgerr is not None and getattr(pgerr, "sqlstate", None) == "42501":
                raise PermissionError("workspace owner required") from exc
            raise
        await session.commit()
    return {"workspace_id": workspace_id, "name": clean}
