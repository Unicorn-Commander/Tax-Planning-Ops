"""Propose-only tax-planning agent.

Given a client tax year, score the real planning opportunities with the
deterministic engine and ask the LLM (qwen3.6, reasoning on) to author a
prioritized, client-facing narrative. The agent is PROPOSE-ONLY: it never writes
a ClientStrategy or mutates the plan — an advisor reviews the proposal and
applies strategies through the existing approval path.

Hard rule: every dollar figure in the proposal comes from the engine. The LLM is
given the computed numbers and explicitly instructed never to invent or alter a
figure; if the LLM is unavailable the structured opportunities still return (the
narrative is simply omitted). This keeps a language model out of the math.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.engines.form1040 import Form1040Inputs
from app.engines.opportunity import Opportunity, find_opportunities
from app.integrations.llm import chat, llm_enabled, strip_think
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.tax_config import resolve_bracket_set, to_engine_config

_DISCLAIMER = (
    "Illustrative planning estimates only — not tax advice. Figures assume the "
    "stated illustrative contribution amounts and current-year brackets; the "
    "advisor must confirm eligibility, contribution limits, and the client's "
    "facts before acting."
)


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


async def _latest_snapshot(db: AsyncSession, tax_year_id: UUID) -> TaxSituationSnapshot | None:
    snapshot: TaxSituationSnapshot | None = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    return snapshot


async def _narrative(
    client_name: str,
    opportunities: list[Opportunity],
    settings: Settings,
) -> str | None:
    if not llm_enabled(settings) or not opportunities:
        return None
    lines = "\n".join(
        f"- {o.name} ({o.category}, {o.citation}): contributing "
        f"{_dollars(o.illustrative_amount_cents)} saves about "
        f"{_dollars(o.estimated_tax_savings_cents)} this year at a "
        f"{o.marginal_rate_used:.0%} marginal rate. Eligibility: {o.eligibility_note}"
        for o in opportunities
    )
    prompt = (
        "You are a tax-planning advisor drafting a brief, prioritized proposal for a "
        f"client named {client_name}. Use ONLY the figures below — never invent, round "
        "differently, or alter any dollar amount or savings number. Write 2-4 short "
        "paragraphs: lead with the highest-impact moves, explain the why plainly, and "
        "note that eligibility must be confirmed. Do not promise outcomes.\n\n"
        f"COMPUTED OPPORTUNITIES (authoritative):\n{lines}\n\n"
        "Write the proposal now."
    )
    reply = await chat(
        settings,
        [{"role": "user", "content": prompt}],
        model=settings.LLM_TEXT_MODEL,
        max_tokens=1200,
    )
    return strip_think(reply)


async def propose_plan(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    client_tax_year_id: UUID,
    settings: Settings,
    illustrative_amount_cents: int | None = None,
) -> dict[str, Any]:
    tax_year = await db.get(ClientTaxYear, client_tax_year_id)
    if tax_year is None:
        raise LookupError("client tax year not found")
    snapshot = await _latest_snapshot(db, client_tax_year_id)
    if snapshot is None:
        raise LookupError("no tax situation snapshot for this year")
    client = await db.get(Client, tax_year.client_id)
    client_name = client.display_name if client else "the client"

    bracket_set = await resolve_bracket_set(
        db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("no bracket set for this tax year/filing status")
    config = to_engine_config(bracket_set)

    inputs = Form1040Inputs(**{**snapshot.inputs, "filing_status": tax_year.filing_status})
    kwargs: dict[str, Any] = {}
    if illustrative_amount_cents is not None:
        kwargs["illustrative_amount_cents"] = illustrative_amount_cents
    opportunities = find_opportunities(inputs, config, **kwargs)

    narrative = await _narrative(client_name, opportunities, settings)
    total_savings = sum(o.estimated_tax_savings_cents for o in opportunities)

    return {
        "status": "proposed",
        "client_tax_year_id": str(client_tax_year_id),
        "client_name": client_name,
        "tax_year": tax_year.tax_year,
        "current_total_tax_cents": snapshot.total_tax_cents,
        "total_illustrative_savings_cents": total_savings,
        "opportunities": [o.model_dump(mode="json") for o in opportunities],
        "narrative": narrative,
        "narrative_available": narrative is not None,
        "disclaimer": _DISCLAIMER,
    }
