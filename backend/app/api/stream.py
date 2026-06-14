"""Streaming strategist run (SSE) — the Console's live "plan → engine-call feed
→ memo" view (spec §9.6 / Console door 2).

A Server-Sent-Events endpoint that runs the AI strategist and streams its
progress as it happens: the plan card, each engine call as it runs, each finding
as it lands, then the authored memo, then a terminal `done` with the totals. It
is a VIEW — it persists nothing (the existing
``POST /agents/clients/tax-years/{id}/strategist/run`` is the persisting path).

Every dollar in every event is engine-computed; the stream only narrates
progress around the real engine output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_scopes
from app.core.config import Settings, get_settings
from app.db.session import get_tenant_db
from app.schemas.auth import AuthContext
from app.services.strategist_stream import sse_format, stream_strategist_run

router = APIRouter(prefix="/agents", tags=["stream"])


@router.post("/clients/tax-years/{tax_year_id}/strategist/stream")
async def post_strategist_stream(
    tax_year_id: UUID,
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
    db: AsyncSession = Depends(get_tenant_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Stream the strategist run as Server-Sent Events.

    The generator raises ``LookupError`` (missing tax year / snapshot / bracket
    set) BEFORE it yields anything, so we pull the first event eagerly here and
    map that pre-stream failure to a 404 — once the SSE body is open we can no
    longer change the status code.
    """
    agen = stream_strategist_run(
        db, workspace_id=ctx.workspace_id, tax_year_id=tax_year_id, settings=settings
    )
    try:
        first = await agen.__anext__()
    except LookupError as exc:
        await agen.aclose()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def body() -> AsyncIterator[str]:
        yield sse_format(first)
        async for event in agen:
            yield sse_format(event)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
