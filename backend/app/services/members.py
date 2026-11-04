"""Workspace member management and single-use workspace invitations.

Membership rows are RLS-protected.  The migration keeps the normal user-scoped
switcher query intact, while this service enables the roster-read flag only for
the target-workspace list operation.  Owner checks remain explicit in the
service and are also represented by the database policy functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import bind_session_context
from app.models.membership import WorkspaceMembership
from app.models.workspace import Workspace
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


async def _enable_roster_read(db: AsyncSession) -> None:
    """Allow the RLS roster policy for this transaction only."""
    await db.execute(
        text("SELECT set_config('app.membership_read', '1', true)")
    )


async def _active_membership(
    db: AsyncSession, *, workspace_id: UUID, uc_uid: str
) -> WorkspaceMembership | None:
    return cast(
        WorkspaceMembership | None,
        await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_uc_uid == uc_uid,
                WorkspaceMembership.deleted_at.is_(None),
            )
        ),
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
    """Add a known subject as a normal member, idempotently."""
    await _require_owner(db, workspace_id=workspace_id, uc_uid=actor_uc_uid)
    await _enable_roster_read(db)
    workspace_name = await db.scalar(
        select(Workspace.name).where(Workspace.id == workspace_id)
    )
    if workspace_name is None:
        raise LookupError("workspace not found")

    # The owner-only INSERT/UPDATE policy lets this query see a previously
    # removed row so re-adding a subject does not collide with the unique key.
    existing = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_uc_uid == member_uc_uid,
        )
    )
    if existing is None:
        existing = WorkspaceMembership(
            user_uc_uid=member_uc_uid,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            role=MEMBER_ROLE,
        )
        db.add(existing)
    elif existing.deleted_at is not None:
        existing.deleted_at = None
        existing.workspace_name = workspace_name
        existing.role = MEMBER_ROLE

    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.member.added",
        aggregate_type="workspace_membership",
        aggregate_id=existing.id,
        payload={"member_uc_uid": member_uc_uid, "role": existing.role},
    )
    return existing


async def create_invitation(
    db: AsyncSession, *, workspace_id: UUID, actor_uc_uid: str
) -> dict[str, Any]:
    """Persist only a hash and return the raw token exactly once."""
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
    """Atomically consume an invitation and add the accepting subject."""
    result = await db.execute(
        text(
            """
            SELECT id, workspace_id, role, expires_at, consumed_at
            FROM workspace_invitation
            WHERE token_hash = :token_hash
            FOR UPDATE
            """
        ),
        {"token_hash": hash_invitation_token(raw_token)},
    )
    row = result.mappings().first()
    if row is None:
        raise InvalidInvitationError("invitation is invalid or expired")

    invitation_workspace_id = UUID(str(row["workspace_id"]))
    expires_at = _utc(row["expires_at"])
    if (
        row["consumed_at"] is not None
        or expires_at <= datetime.now(UTC)
        or invitation_workspace_id != workspace_id
    ):
        raise InvalidInvitationError("invitation is invalid or expired")

    # The invitee is not a member yet, so the request's active workspace may be
    # their private self-serve workspace. Rebind this transaction only after the
    # token proves the target workspace, then the normal INSERT RLS check applies.
    await bind_session_context(db, str(workspace_id), actor_uc_uid)
    workspace_name = await db.scalar(
        select(Workspace.name).where(Workspace.id == workspace_id)
    )
    if workspace_name is None:
        raise InvalidInvitationError("invitation is invalid or expired")

    member = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_uc_uid == actor_uc_uid,
        )
    )
    if member is None:
        member = WorkspaceMembership(
            user_uc_uid=actor_uc_uid,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            role=str(row["role"] or MEMBER_ROLE),
        )
        db.add(member)
    elif member.deleted_at is not None:
        member.deleted_at = None
        member.workspace_name = workspace_name
        member.role = str(row["role"] or MEMBER_ROLE)

    await db.flush()
    await db.execute(
        text(
            "UPDATE workspace_invitation SET consumed_at = now() "
            "WHERE id = :invitation_id AND consumed_at IS NULL"
        ),
        {"invitation_id": row["id"]},
    )
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="workspace.invitation.accepted",
        aggregate_type="workspace_membership",
        aggregate_id=member.id,
        payload={"invitation_id": str(row["id"]), "role": member.role},
    )
    return member


async def remove_member(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    member_uc_uid: str,
) -> WorkspaceMembership:
    """Remove a member, refusing to orphan the workspace."""
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

    if target.role == "owner":
        # Lock the owner set before counting so two concurrent removals cannot
        # both observe two owners and leave the workspace orphaned.
        owners = await db.scalars(
            select(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == "owner",
                WorkspaceMembership.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if len(list(owners.all())) <= 1:
            raise LastOwnerError("cannot remove the last owner")

    target_id = target.id
    target_role = target.role
    await db.delete(target)
    await db.flush()
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
