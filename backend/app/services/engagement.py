"""Read firm branding and read/write the per-client advisory fee.

Two small honesty-gap closers behind the Present plates: the letterhead is read
straight from the workspace's branding row (no hardcoded default leaking into a
client-facing document), and the advisory fee is a per-client, operator-supplied
integer-cents value (never computed) so savings can be framed net of fee.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import WorkspaceBranding
from app.models.client import Client
from app.models.engagement import Engagement
from app.schemas.engagement import FeeIn


async def get_branding(
    db: AsyncSession,
    *,
    workspace_id: UUID,
) -> WorkspaceBranding | None:
    """The workspace's firm-branding row, or None if it has never been set."""
    return await db.scalar(
        select(WorkspaceBranding).where(WorkspaceBranding.workspace_id == workspace_id)
    )


async def get_engagement(
    db: AsyncSession,
    *,
    client_id: UUID,
) -> Engagement | None:
    """The advisory-fee engagement for a client, or None if none is on file.

    RLS already scopes the query to the caller's workspace; the unique
    constraint on ``client_id`` makes this at most one row."""
    return await db.scalar(select(Engagement).where(Engagement.client_id == client_id))


async def upsert_engagement(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    client_id: UUID,
    payload: FeeIn,
) -> Engagement:
    """Create or update the client's advisory-fee engagement.

    The client must exist in the caller's workspace (RLS-scoped) or this raises
    ``LookupError``. ``fee_cents`` is taken verbatim from the operator-supplied
    payload — it is never derived from the plan numbers."""
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise LookupError("client not found")
    engagement = await db.scalar(select(Engagement).where(Engagement.client_id == client_id))
    if engagement is None:
        engagement = Engagement(workspace_id=workspace_id, client_id=client_id)
    engagement.fee_cents = payload.fee_cents
    engagement.fee_basis = payload.fee_basis
    engagement.fee_note = payload.fee_note
    db.add(engagement)
    await db.flush()
    return engagement
