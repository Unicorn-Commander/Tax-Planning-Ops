"""Workspace member management and single-use workspace invitations.

Since migration 0023 the app role holds SELECT-only on
``workspace_membership``: every write path here runs through the
SECURITY DEFINER functions created by that migration (actor checked against
``current_uc_uid()`` in the database, owner checks in the function).  The
service layer keeps the same public API and error types: ``PermissionError``
from the database's 42501, ``InvalidInvitationError``/``LastOwnerError`` from
its P0001.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import ProgrammingError as SAProgrammingError

from app.db.session import bind_session_context
from app.models.membership import WorkspaceMembership
from app.services.audit import append_audit_event
from app.services.member_tokens import (
    generate_invitation_token,
    hash_invitation_token,
)

INVITATION_TTL_DAYS = 7
MEMBER_ROLE = "member"


class InvalidInvitationError(ValueError):
    """The supplied invitation is unknown, expired, consumed, or misplaced."""


class LastOwnerError(ValueError):
    """Removing the requested membership would orphan the workspace."""


def _utc(value: datetime) -> datetime:
    """Normalize a database/test datetime for an aware UTC comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_error(exc: SAProgrammingError) -> Exception:
    """Translate the definer functions' RAISE codes into the service's errors."""
    pgerr = getattr(exc, "orig", None)
    if isinstance(pgerr, asyncpg.PostgresError):
        if pgerr.sqlstate() == "42501":
            return PermissionError(pgerr.get_message())
        message = pgerr.get_message()
        if "last owner" in message:
            return LastOwnerError(message)
        if "invalid or expired" in message:
            return InvalidInvitationError(message)
        return PermissionError(message)
    return exc


async def _enable_roster_read(db: AsyncSession) -> None:
    """Allow the RLS roster read for this transaction only (legacy flag; the
    0023 select policy is user-scoped and the roster read goes through the
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
    except SAProgrammingError as exc:
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
    db: AsyncSession, *, workspace_id: UUID, actor_uc_uid: str
) -> dict[str, Any]:
    """Persist only a hash and return the raw token exactly once.

    Owner-gated in the service; the workspace_invitation table keeps its own
    (0022) grants and is not part of the 0023 lock."""
    await _require_owner(db, workspace_id=workspace_id, uc_uid=actor_uc_uid)
    raw_token = generate_invitation_token()
    invitation_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS)
    await db.execute(
        text(
            """
            INSERT INTO workspace_invitation
                (id, workspace_id, token_hash, role, expires_at, created_by_uc_uid)
            VALUES (:id, :workspace_id, :token_hash, :role, :expires_at, :created_by)
            """
        ),
        {
            "id": invitation_id,
            "workspace_id": workspace_id,
            "token_hash": hash_invitation_token(raw_token),
            "role": MEMBER_ROLE,
            "expires_at": expires_at,
            "created_by": actor_uc_uid,
        },
    )
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.invitation.created",
        aggregate_type="workspace_invitation",
        aggregate_id=invitation_id,
        payload={"expires_at": expires_at.isoformat(), "role": MEMBER_ROLE},
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

    The definer function re-checks actor == current_uc_uid(), the token's
    hash, its expiry/consumption state, and that the token's workspace matches
    the target; the invitee must accept for themselves (p_invitee is bound to
    the GUC, not to an argument)."""
    # Rebind the actor so the definer function's current_uc_uid() is the
    # invitee even if the request's active workspace was someone else's.
    await bind_session_context(db, str(workspace_id), actor_uc_uid)
    try:
        await db.execute(
            text(
                "SELECT workspace_membership_accept_invitation(:ws, :token)"
            ),
            {"ws": workspace_id, "token": raw_token},
        )
    except SAProgrammingError as exc:
        raise _db_error(exc) from exc
    db.expire_all()
    member = await _active_membership(
        db, workspace_id=workspace_id, uc_uid=actor_uc_uid
    )
    if member is None:
        raise InvalidInvitationError("invitation is invalid or expired")
    consumed = await db.scalar(
        text(
            "SELECT id FROM workspace_invitation "
            "WHERE token_hash = :token_hash AND consumed_at IS NOT NULL"
        ),
        {"token_hash": hash_invitation_token(raw_token)},
    )
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.invitation.accepted",
        aggregate_type="workspace_membership",
        aggregate_id=member.id,
        payload={"invitation_id": str(consumed), "role": member.role},
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
    except SAProgrammingError as exc:
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
