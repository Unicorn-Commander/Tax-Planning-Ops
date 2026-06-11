"""Book-wide opportunity scan.

Ranks a firm's clients by REAL planning opportunity, not by raw tax. For each
client's latest snapshot we rebuild the federal inputs + the resolved bracket
config and run the deterministic opportunity engine (which scores every
candidate strategy by re-running the engine). The opportunity score is the sum
of the modeled savings — a genuine "who should I call first" signal.

Falls back to total tax as the score only when a snapshot can't be re-evaluated
(e.g. a missing bracket set), so the scan never silently drops a client.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.form1040 import Form1040Inputs, TaxConfig
from app.engines.opportunity import find_opportunities
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.tax_config import resolve_bracket_set, to_engine_config


async def scan_book(db: AsyncSession, workspace_id: UUID, limit: int = 25) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Client, ClientTaxYear, TaxSituationSnapshot)
        .join(ClientTaxYear, ClientTaxYear.client_id == Client.id)
        .join(TaxSituationSnapshot, TaxSituationSnapshot.client_tax_year_id == ClientTaxYear.id)
        .where(Client.workspace_id == workspace_id)
        .order_by(TaxSituationSnapshot.total_tax_cents.desc())
    )

    config_cache: dict[tuple[int, str], TaxConfig | None] = {}
    rows: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    for client, tax_year, snapshot in result.all():
        # One row per client (their highest-tax year, already ordered desc).
        if client.id in seen:
            continue
        seen.add(client.id)

        opportunities: list[dict[str, Any]] = []
        opportunity_score = snapshot.total_tax_cents  # fallback
        scored = False
        key = (tax_year.tax_year, tax_year.filing_status)
        if key not in config_cache:
            bracket_set = await resolve_bracket_set(
                db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
            )
            config_cache[key] = to_engine_config(bracket_set) if bracket_set else None
        config = config_cache[key]
        if config is not None:
            try:
                inputs = Form1040Inputs(
                    **{**snapshot.inputs, "filing_status": tax_year.filing_status}
                )
                found = find_opportunities(inputs, config)
                opportunity_score = sum(o.estimated_tax_savings_cents for o in found)
                opportunities = [
                    {
                        "code": o.code,
                        "name": o.name,
                        "category": o.category,
                        "estimated_tax_savings_cents": o.estimated_tax_savings_cents,
                        "illustrative_amount_cents": o.illustrative_amount_cents,
                    }
                    for o in found[:5]
                ]
                scored = True
            except (TypeError, ValueError, KeyError):
                scored = False

        rows.append(
            {
                "client_id": str(client.id),
                "client_name": client.display_name,
                "client_tax_year_id": str(tax_year.id),
                "tax_year": tax_year.tax_year,
                "total_tax_cents": snapshot.total_tax_cents,
                "effective_rate": str(snapshot.effective_rate),
                "opportunity_score_cents": opportunity_score,
                "opportunity_scored": scored,
                "top_opportunities": opportunities,
            }
        )

    rows.sort(key=lambda r: r["opportunity_score_cents"], reverse=True)
    return rows[:limit]
