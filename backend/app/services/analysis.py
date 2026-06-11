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

from app.engine_configs import ty2025_qbi_config, ty2025_se_tax_config
from app.engines.amt import ty2025_amt_config
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.form1040 import Form1040Inputs
from app.engines.irmaa import IRMAAInput, calculate_irmaa, ty2025_irmaa_config
from app.engines.multiyear import MultiYearInput, project_multi_year
from app.engines.opportunity import find_opportunities
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.entities import aggregate_business, aggregate_for_comprehensive, list_entities
from app.services.tax_config import resolve_bracket_set, to_engine_config
from app.state_configs import get_state_config


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

    # Business entities fold into the comprehensive return: their income joins
    # Schedule 1, SE tax + the ½-SE deduction apply, and §199A QBI is computed.
    entities = await list_entities(db, client_tax_year_id=tax_year_id)
    agg = aggregate_for_comprehensive(entities)
    # C-corp salaries → 1040 wages; C-corp dividends → qualified (and ordinary)
    # dividends. The corporate tax is added separately as the integrated total.
    comp_form1040 = inputs.model_copy(
        update={
            "schedule_1_income_cents": inputs.schedule_1_income_cents + agg.schedule_1_cents,
            "wages_cents": inputs.wages_cents + agg.owner_wages_add_cents,
            "qualified_dividends_cents": (
                inputs.qualified_dividends_cents + agg.owner_qualified_dividends_cents
            ),
            "ordinary_dividends_cents": (
                inputs.ordinary_dividends_cents + agg.owner_qualified_dividends_cents
            ),
        }
    )
    net_capital_gain = max(comp_form1040.qualified_dividends_cents, 0) + max(
        comp_form1040.capital_gain_loss_cents, 0
    )

    # --- Comprehensive return (federal + SS + CTC + AMT + SE/QBI when present) -
    try:
        comp = calculate_comprehensive(
            ComprehensiveInput(
                form1040=comp_form1040,
                self_employment_base_cents=agg.se_base_cents,
                qbi_businesses=agg.qbi_businesses,
                net_capital_gain_for_qbi_cents=net_capital_gain,
            ),
            config,
            amt_config=ty2025_amt_config(),
            se_config=ty2025_se_tax_config(),
            qbi_config=ty2025_qbi_config(),
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
        analysis["comprehensive_return"] = {
            "available": True,
            "base_snapshot_total_tax_cents": snapshot.total_tax_cents,
            "total_tax_cents": comp.total_tax_cents,
            "regular_total_tax_cents": comp.regular_total_tax_cents,
            "se_tax_cents": comp.se_tax_cents,
            "amt_cents": comp.amt_cents,
            "qbi_deduction_cents": (
                comp.qbi.allowed_qbi_deduction_cents if comp.qbi else 0
            ),
            "refundable_credits_cents": comp.refundable_credits_cents,
            "balance_due_cents": comp.balance_due_cents,
            "includes_business": bool(entities),
            # C-corp double tax: the corporation's own 21% tax sits on top of the
            # owner's personal tax on salary + dividends.
            "corporate_tax_cents": agg.corporate_tax_cents,
            "integrated_total_tax_cents": comp.total_tax_cents + agg.corporate_tax_cents,
            "has_c_corp": agg.has_c_corp,
            "assumptions": comp.assumptions,
        }

        # State income tax (from the client's primary state).
        state_code = (client.primary_state if client else None) or ""
        state_cfg = get_state_config(state_code, tax_year.tax_year)
        if state_cfg is not None:
            st = calculate_state_tax(
                StateTaxInput(
                    filing_status=tax_year.filing_status,
                    federal_agi_cents=comp.federal.agi_cents,
                    federal_taxable_income_cents=comp.federal.taxable_income_cents,
                    social_security_taxable_cents=comp_form1040.social_security_taxable_cents,
                    retirement_income_cents=(
                        comp_form1040.ira_taxable_cents + comp_form1040.pensions_taxable_cents
                    ),
                ),
                state_cfg,
            )
            analysis["state_tax"] = {
                "available": True,
                "state": st.state,
                "has_income_tax": st.has_income_tax,
                "state_tax_cents": st.total_state_tax_cents,
                "state_marginal_rate": str(st.marginal_rate),
                "federal_plus_state_total_cents": (
                    comp.total_tax_cents + agg.corporate_tax_cents + st.total_state_tax_cents
                ),
                "assumptions": st.assumptions,
            }
        else:
            analysis["state_tax"] = {
                "available": False,
                "reason": f"State '{state_code}' not yet modeled (federal-only).",
            }
    except (ValueError, KeyError, TypeError) as exc:
        analysis["amt"] = {"available": False, "reason": str(exc)}
        analysis["comprehensive_return"] = {"available": False, "reason": str(exc)}

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
    # Reuses the entities loaded above; QBI here is keyed off the base taxable
    # income for the standalone view (the folded number lives in
    # comprehensive_return).
    try:
        analysis["business"] = aggregate_business(
            entities,
            filing_status=tax_year.filing_status,
            taxable_income_before_qbi_cents=snapshot.taxable_income_cents,
            net_capital_gain_cents=net_capital_gain,
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
