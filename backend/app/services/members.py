"""Workspace member management and single-use workspace invitations.

Since migration 0024 the app role holds SELECT-only on
``workspace_membership``: every write path here runs through the
SECURITY DEFINER functions created by that migration (actor checked against
``current_uc_uid()`` in the database, owner checks in the function).  The
service layer keeps the same public API and error types: ``PermissionError``
from the database's 42501, ``InvalidInvitationError``/``LastOwnerError`` from
its P0001.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError as SADBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import bind_session_context
from app.models.membership import WorkspaceMembership
from app.services.audit import append_audit_event
from app.services.member_tokens import generate_invitation_token

# Fixed in the workspace_invitation_create definer (0024).
INVITATION_TTL_DAYS = 7
MEMBER_ROLE = "member"


class InvalidInvitationError(ValueError):
    """The supplied invitation is unknown, expired, consumed, or misplaced."""


class LastOwnerError(ValueError):
    """Removing the requested membership would orphan the workspace."""


def _db_error(exc: SADBAPIError) -> Exception:
    """Translate the definer functions' RAISE codes into the service's errors."""
    pgerr = getattr(exc, "orig", None)
    if pgerr is not None:
        sqlstate = getattr(pgerr, "sqlstate", None)
        if callable(sqlstate):
            sqlstate = sqlstate()
        if sqlstate == "42501":
            return PermissionError(str(pgerr))
        message = str(pgerr)
        if "last owner" in message:
            return LastOwnerError(message)
        if "invalid or expired" in message:
            return InvalidInvitationError(message)
        return PermissionError(message)
    return exc


async def _enable_roster_read(db: AsyncSession) -> None:
    """Allow the RLS roster read for this transaction only (legacy flag; the
    0024 select policy is user-scoped and the roster read goes through the
    same flag-gated policy restored for read paths)."""
    await db.execute(text("SELECT set_config('app.membership_read', '1', true)"))


async def _active_membership(
    db: AsyncSession, *, workspace_id: UUID, uc_uid: str
) -> WorkspaceMembership | None:
    return await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_uc_uid == uc_uid,
            WorkspaceMembership.deleted_at.is_(None),
        )
    )


async def _require_member(
    db: AsyncSession, *, workspace_id: UUID, uc_uid: str
) -> WorkspaceMembership:
    membership = await _active_membership(db, workspace_id=workspace_id, uc_uid=uc_uid)
    if membership is None:
        raise PermissionError("not a member of this workspace")
    return membership


async def _require_owner(
    db: AsyncSession, *, workspace_id: UUID, uc_uid: str
) -> WorkspaceMembership:
    membership = await _require_member(db, workspace_id=workspace_id, uc_uid=uc_uid)
    if membership.role != "owner":
        raise PermissionError("workspace owner required")
    return membership


async def list_members(
    db: AsyncSession, *, workspace_id: UUID, uc_uid: str
) -> list[WorkspaceMembership]:
    """List the active roster for a workspace any active member can access."""
    await _require_member(db, workspace_id=workspace_id, uc_uid=uc_uid)
    await _enable_roster_read(db)
    rows = await db.scalars(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.deleted_at.is_(None),
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )
    return list(rows.all())


async def add_member(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    member_uc_uid: str,
) -> WorkspaceMembership:
    """Add a known subject as a normal member, idempotently.

    The actor must be an active OWNER (checked in the service for a clear
    error and re-checked in the definer function against current_uc_uid())."""
    await _require_owner(db, workspace_id=workspace_id, uc_uid=actor_uc_uid)
    await _enable_roster_read(db)
    workspace_name = await db.scalar(
        select(WorkspaceMembership.workspace_name)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.deleted_at.is_(None),
        )
        .limit(1)
    )
    if workspace_name is None:
        raise LookupError("workspace not found")

    try:
        await db.execute(
            text(
                "SELECT workspace_membership_add_member(:ws, :member, :name)"
            ),
            {
                "ws": workspace_id,
                "member": member_uc_uid,
                "name": workspace_name,
            },
        )
    except SADBAPIError as exc:
        raise _db_error(exc) from exc
    db.expire_all()
    membership = await _active_membership(
        db, workspace_id=workspace_id, uc_uid=member_uc_uid
    )
    if membership is None:
        raise LookupError("member not found in this workspace")
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.member.added",
        aggregate_type="workspace_membership",
        aggregate_id=membership.id,
        payload={"member_uc_uid": member_uc_uid, "role": membership.role},
    )
    return membership


async def create_invitation(
    db: AsyncSession, *, workspace_id: UUID, actor_uc_uid: str, invitee_uc_uid: str
) -> dict[str, Any]:
    """Create an invitation and return the raw token exactly once.

    Owner-gated in the service for a clear error and again in the definer
    ``workspace_invitation_create`` (actor = current_uc_uid(), active owner).
    The definer hashes the token, fixes role and expiry, and binds the
    invitation to ``invitee_uc_uid``: only that subject can accept it. The app
    role has no direct access to ``workspace_invitation``."""
    await _require_owner(db, workspace_id=workspace_id, uc_uid=actor_uc_uid)
    raw_token = generate_invitation_token()
    try:
        row = (
            await db.execute(
                text(
                    "SELECT o_id, o_expires_at "
                    "FROM workspace_invitation_create(:ws, :token, :invitee)"
                ),
                {"ws": workspace_id, "token": raw_token, "invitee": invitee_uc_uid},
            )
        ).one()
    except SADBAPIError as exc:
        raise _db_error(exc) from exc
    invitation_id, expires_at = row.o_id, row.o_expires_at
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.invitation.created",
        aggregate_type="workspace_invitation",
        aggregate_id=invitation_id,
        payload={
            "expires_at": expires_at.isoformat(),
            "role": MEMBER_ROLE,
            "invitee_uc_uid": invitee_uc_uid,
        },
    )
    return {"invitation_token": raw_token, "expires_at": expires_at}


async def accept_invitation(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    raw_token: str,
) -> WorkspaceMembership:
    """Atomically consume an invitation and add the accepting subject.

    The definer hashes the raw token itself, checks expiry/consumption, the
    target workspace and that current_uc_uid() is the invitation's bound
    invitee, then adds that subject. The audit row is stamped for the invitation's workspace,
    re-binding the GUC so the row lands there even when the request's active
    workspace differs."""
    await bind_session_context(db, str(workspace_id), actor_uc_uid)
    try:
        invitation_id = await db.scalar(
            text("SELECT workspace_membership_accept_invitation(:ws, :token)"),
            {"ws": workspace_id, "token": raw_token},
        )
    except SADBAPIError as exc:
        raise _db_error(exc) from exc
    db.expire_all()
    member = await _active_membership(
        db, workspace_id=workspace_id, uc_uid=actor_uc_uid
    )
    if member is None:
        raise InvalidInvitationError("invitation is invalid or expired")
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.invitation.accepted",
        aggregate_type="workspace_membership",
        aggregate_id=member.id,
        payload={"invitation_id": str(invitation_id), "role": member.role},
    )
    return member


async def remove_member(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    member_uc_uid: str,
) -> WorkspaceMembership:
    """Remove a member, refusing to orphan the workspace.

    The last-owner guard lives in the definer function (row-locked count);
    the service reads the target's role first to pass the right check in."""
    await _require_owner(db, workspace_id=workspace_id, uc_uid=actor_uc_uid)
    await _enable_roster_read(db)
    target = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_uc_uid == member_uc_uid,
            WorkspaceMembership.deleted_at.is_(None),
        )
    )
    if target is None:
        raise LookupError("member not found in this workspace")
    target_id = target.id
    target_role = target.role
    try:
        await db.execute(
            text(
                "SELECT workspace_membership_remove_member(:ws, :member, :role)"
            ),
            {
                "ws": workspace_id,
                "member": member_uc_uid,
                "role": target_role,
            },
        )
    except SADBAPIError as exc:
        raise _db_error(exc) from exc
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.member.removed",
        aggregate_type="workspace_membership",
        aggregate_id=target_id,
        payload={"member_uc_uid": member_uc_uid, "role": target_role},
    )
    return target
