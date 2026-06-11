"""Live planning analysis for a client tax year.

Computes the rich planning picture ON READ from the existing snapshot inputs +
the resolved bracket config — no new stored columns required. Surfaces the
Phase-2 engines that don't need extra input capture:

  * AMT exposure (Form 6251) off the recomputed regular return;
  * IRMAA tier + cliff planning from MAGI (approximated by AGI);
  * a multi-year baseline projection (inflation-indexed brackets);
  * the deterministic opportunity scan.

Each section degrades independently — a section that can't be computed reports
`available: false` with a reason rather than failing the whole call. Engines
needing inputs not yet captured (gross SS, dependents, multi-entity QBI/SE) are
intentionally not run here; they activate once intake captures those fields.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.amt import ty2025_amt_config
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.form1040 import Form1040Inputs
from app.engines.irmaa import IRMAAInput, calculate_irmaa, ty2025_irmaa_config
from app.engines.multiyear import MultiYearInput, project_multi_year
from app.engines.opportunity import find_opportunities
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.entities import aggregate_business, list_entities
from app.services.tax_config import resolve_bracket_set, to_engine_config


def _irmaa_status(filing_status: str) -> str:
    # IRMAA supports single / mfj / mfs_lived_with_spouse. MFS-living-apart and
    # the single-style statuses all use the single thresholds.
    return "mfj" if filing_status == "mfj" else "single"


async def _latest_snapshot(db: AsyncSession, tax_year_id: UUID) -> TaxSituationSnapshot | None:
    snapshot: TaxSituationSnapshot | None = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    return snapshot


async def get_client_analysis(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    tax_year_id: UUID,
    horizon_years: int = 5,
) -> dict[str, Any]:
    tax_year = await db.get(ClientTaxYear, tax_year_id)
    if tax_year is None:
        raise LookupError("client tax year not found")
    snapshot = await _latest_snapshot(db, tax_year_id)
    if snapshot is None:
        raise LookupError("no tax situation snapshot for this year")
    client = await db.get(Client, tax_year.client_id)

    bracket_set = await resolve_bracket_set(
        db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("no bracket set for this tax year/filing status")
    config = to_engine_config(bracket_set)
    inputs = Form1040Inputs(**{**snapshot.inputs, "filing_status": tax_year.filing_status})

    analysis: dict[str, Any] = {
        "client_tax_year_id": str(tax_year_id),
        "client_name": client.display_name if client else None,
        "tax_year": tax_year.tax_year,
        "filing_status": tax_year.filing_status,
    }

    # --- AMT exposure (via the comprehensive orchestrator) ------------------
    try:
        comp = calculate_comprehensive(
            ComprehensiveInput(form1040=inputs), config, amt_config=ty2025_amt_config()
        )
        analysis["amt"] = {
            "available": True,
            "amt_applies": comp.amt.amt_applies if comp.amt else False,
            "amt_cents": comp.amt_cents,
            "tentative_minimum_tax_cents": comp.amt.tentative_minimum_tax_cents if comp.amt else 0,
            "regular_total_tax_cents": comp.regular_total_tax_cents,
            "total_tax_cents": comp.total_tax_cents,
            "assumptions": comp.assumptions,
        }
    except (ValueError, KeyError, TypeError) as exc:
        analysis["amt"] = {"available": False, "reason": str(exc)}

    # --- IRMAA tier + cliff planning ---------------------------------------
    try:
        irmaa = calculate_irmaa(
            IRMAAInput(
                filing_status=_irmaa_status(tax_year.filing_status),
                magi_cents=snapshot.agi_cents,
            ),
            ty2025_irmaa_config(),
        )
        analysis["irmaa"] = {
            "available": True,
            "magi_basis": "agi_proxy",
            "tier": irmaa.irmaa_tier,
            "total_irmaa_annual_cents": irmaa.total_irmaa_annual_cents,
            "next_cliff_threshold_cents": irmaa.next_cliff_threshold_cents,
            "distance_to_next_cliff_cents": irmaa.distance_to_next_cliff_cents,
            "cliff_cost_annual_cents": irmaa.cliff_cost_annual_cents,
            "room_to_drop_one_tier_cents": irmaa.room_to_drop_one_tier_cents,
            "note": "MAGI approximated by AGI (add tax-exempt interest for exactness).",
        }
    except (ValueError, KeyError, TypeError) as exc:
        analysis["irmaa"] = {"available": False, "reason": str(exc)}

    # --- Multi-year baseline projection ------------------------------------
    try:
        my = project_multi_year(
            MultiYearInput(
                base_year=tax_year.tax_year,
                base_inputs=inputs,
                base_config=config,
                horizon_years=horizon_years,
            )
        )
        analysis["multi_year"] = {
            "available": True,
            "assumptions": my.assumptions,
            "years": [
                {
                    "tax_year": y.tax_year,
                    "total_income_cents": y.total_income_cents,
                    "taxable_income_cents": y.taxable_income_cents,
                    "total_tax_cents": y.total_tax_cents,
                    "marginal_rate": str(y.marginal_rate),
                    "config_source": y.config_source,
                }
                for y in my.baseline.years
            ],
            "cumulative_tax_cents": my.baseline.cumulative_tax_cents,
        }
    except (ValueError, KeyError, TypeError) as exc:
        analysis["multi_year"] = {"available": False, "reason": str(exc)}

    # --- Multi-entity business aggregation (SE tax + §199A QBI) -------------
    try:
        entities = await list_entities(db, client_tax_year_id=tax_year_id)
        analysis["business"] = aggregate_business(
            entities,
            filing_status=tax_year.filing_status,
            taxable_income_before_qbi_cents=snapshot.taxable_income_cents,
            net_capital_gain_cents=max(inputs.qualified_dividends_cents, 0)
            + max(inputs.capital_gain_loss_cents, 0),
        )
    except (ValueError, KeyError, TypeError) as exc:
        analysis["business"] = {"available": False, "reason": str(exc)}

    # --- Opportunity scan ---------------------------------------------------
    try:
        opps = find_opportunities(inputs, config)
        analysis["opportunities"] = {
            "available": True,
            "total_illustrative_savings_cents": sum(
                o.estimated_tax_savings_cents for o in opps
            ),
            "items": [o.model_dump(mode="json") for o in opps],
        }
    except (ValueError, KeyError, TypeError) as exc:
        analysis["opportunities"] = {"available": False, "reason": str(exc)}

    return analysis
