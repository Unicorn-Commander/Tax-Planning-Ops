"""Audit-journal read API (spec §9.5).

A scoped, paginated READ tail of the append-only, hash-chained audit journal
(which is otherwise write-only). Powers the Desk ticker and the Staff traffic
feed. The journal write/verify logic lives in ``app.services.audit``; this
router only reads.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.schemas.journal import JournalEventOut, JournalStatusOut, JournalTailOut
from app.services.audit import journal_status, read_journal_tail

router = APIRouter(prefix="/lifecycle", tags=["journal"])


@router.get("/journal", response_model=JournalTailOut)
async def get_journal_tail(
    tail: int = Query(20, ge=1, le=200, description="How many newest events to return."),
    before: datetime | None = Query(
        None, description="Page backwards: only events strictly older than this timestamp."
    ),
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
) -> JournalTailOut:
    """The newest-first tail of the workspace's audit journal plus the live chain
    status. RLS scopes the read to the caller's workspace; ``tail`` is clamped to
    [1, 200] and ``before`` pages backwards through older events."""
    events = await read_journal_tail(db, ctx.workspace_id, limit=tail, before=before)
    status = await journal_status(db, ctx.workspace_id)
    return JournalTailOut(
        events=[JournalEventOut.model_validate(event) for event in events],
        status=JournalStatusOut.model_validate(status),
    )
