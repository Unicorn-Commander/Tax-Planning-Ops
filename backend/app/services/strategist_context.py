"""Deeper context for the AI strategist.

Two things the strategist needs to reason like an advisor rather than a
calculator:

  * **Prior-year trajectory** — where the client's income has been heading
    across the years on file, so advice can lean into (or against) the trend
    (accelerate income into low years, defer into high years, watch an IRMAA
    crossing).

  * **Goal-aware findings** — the client's stated objectives (a coming
    liquidity event, charitable intent, a planned move, a retirement date) turned
    into concrete, engine-computed levers. Every dollar still comes from an
    engine (charitable bunching/QCD, §1202 QSBS, the state engine); the goals
    only decide WHICH levers are relevant and how to prioritize them.

These compose with the existing optimizer-driven findings in `strategist.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.charitable import (
    BunchingInput,
    CharitableConfig,
    QCDInput,
    bunching_benefit,
    qcd_benefit,
)
from app.engines.corporate import CorporateConfig, QSBSInput, calculate_qsbs
from app.engines.irmaa import IRMAAConfig, IRMAAInput, calculate_irmaa
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.models.profile import ClientPlanningProfile
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.state_configs import get_state_config

# Long-term capital-gain + NIIT planning proxy for a high earner (20% + 3.8%).
# Used only to size the *relative* benefit of a QSBS exclusion vs an ordinary
# taxable sale; the actual return engine still computes the filed figures.
_LTCG_NIIT_PROXY = Decimal("0.238")


def _d(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def _finding(
    *, title: str, category: str, action: str, impact_cents: int, kind: str,
    citation: str, caveat: str, details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": title, "category": category, "recommended_action": action,
        "estimated_impact_cents": impact_cents, "impact_kind": kind,
        "citation": citation, "caveat": caveat, "details": details,
    }


# ---------------------------------------------------------------------------
# Prior-year trajectory
# ---------------------------------------------------------------------------


async def build_trajectory(
    db: AsyncSession,
    *,
    client_id: UUID,
    irmaa_config: IRMAAConfig,
    irmaa_status: str,
) -> dict[str, Any]:
    tax_years = list(
        (
            await db.execute(
                select(ClientTaxYear)
                .where(ClientTaxYear.client_id == client_id)
                .order_by(ClientTaxYear.tax_year)
            )
        )
        .scalars()
        .all()
    )
    points: list[dict[str, Any]] = []
    for ty in tax_years:
        snap = await db.scalar(
            select(TaxSituationSnapshot)
            .where(TaxSituationSnapshot.client_tax_year_id == ty.id)
            .order_by(TaxSituationSnapshot.created_at.desc())
        )
        if snap is None:
            continue
        points.append(
            {
                "tax_year": ty.tax_year,
                "role": ty.role,
                "total_income_cents": snap.total_income_cents,
                "agi_cents": snap.agi_cents,
                "taxable_income_cents": snap.taxable_income_cents,
                "total_tax_cents": snap.total_tax_cents,
                "marginal_rate": str(snap.marginal_rate),
            }
        )

    if len(points) < 2:
        return {
            "available": False,
            "points": points,
            "reason": "Need at least two years on file to show a trajectory.",
        }

    first, last = points[0], points[-1]
    change = last["total_income_cents"] - first["total_income_cents"]
    span = max(1, abs(first["total_income_cents"]))
    pct = Decimal(change) / Decimal(span)
    if pct > Decimal("0.07"):
        direction = "rising"
    elif pct < Decimal("-0.07"):
        direction = "declining"
    else:
        direction = "flat"

    tier_first = calculate_irmaa(
        IRMAAInput(filing_status=irmaa_status, magi_cents=first["agi_cents"]), irmaa_config
    ).irmaa_tier
    tier_last = calculate_irmaa(
        IRMAAInput(filing_status=irmaa_status, magi_cents=last["agi_cents"]), irmaa_config
    ).irmaa_tier
    irmaa_crossing = tier_last > tier_first

    summary = (
        f"Income has been {direction} across {len(points)} years on file "
        f"({first['tax_year']}: {_d(first['total_income_cents'])} → "
        f"{last['tax_year']}: {_d(last['total_income_cents'])}, "
        f"{_d(change)} change)."
    )
    if irmaa_crossing:
        summary += (
            f" Crossing an IRMAA tier over that span (tier {tier_first} → {tier_last})."
        )

    return {
        "available": True,
        "points": points,
        "income_direction": direction,
        "income_change_cents": change,
        "irmaa_tier_first": tier_first,
        "irmaa_tier_last": tier_last,
        "irmaa_crossing": irmaa_crossing,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Goal-aware findings
# ---------------------------------------------------------------------------


def goal_aware_findings(
    *,
    profile: ClientPlanningProfile | None,
    tax_year: int,
    marginal_rate: Decimal,
    agi_cents: int,
    itemized_deduction_cents: int,
    standard_deduction_cents: int,
    ira_taxable_cents: int,
    primary_state: str | None,
    charitable_config: CharitableConfig,
    corporate_config: CorporateConfig,
) -> list[dict[str, Any]]:
    """Turn the client's stated goals into concrete, engine-computed findings.

    Returns canonical finding dicts (same shape as the optimizer findings).
    A null profile yields an empty list — the strategist still runs."""
    if profile is None:
        return []

    findings: list[dict[str, Any]] = []
    takes_standard = itemized_deduction_cents < standard_deduction_cents

    # --- Charitable bunching (DAF) ----------------------------------------
    if (
        profile.charitable_intent in {"moderate", "high", "legacy"}
        and profile.annual_giving_cents > 0
    ):
        years_bunched = 5 if profile.charitable_intent == "legacy" else (
            2 if profile.cash_flow_sensitivity == "high" else 3
        )
        other_itemized = max(0, itemized_deduction_cents - profile.annual_giving_cents)
        bunch = bunching_benefit(
            BunchingInput(
                annual_giving_cents=profile.annual_giving_cents,
                years_bunched=years_bunched,
                standard_deduction_cents=standard_deduction_cents,
                other_itemized_cents=other_itemized,
                marginal_rate=marginal_rate,
                agi_cents=agi_cents,
            ),
            charitable_config,
        )
        if bunch.tax_savings_cents > 0:
            findings.append(_finding(
                title="Bunch charitable gifts into one year (donor-advised fund)",
                category="charitable",
                action=(
                    f"Pre-fund {years_bunched} years of giving "
                    f"({_d(bunch.bunched_giving_cents)}) into a DAF this year to clear the "
                    f"standard deduction, then grant it out over time. The bunch buys "
                    f"{_d(bunch.extra_deduction_cents)} of deduction the annual gifts wouldn't."
                ),
                impact_cents=bunch.tax_savings_cents, kind="savings", citation="IRC §170",
                caveat=(
                    "Assumes recurring itemized deductions stay roughly constant; the "
                    "2026 0.5%-of-AGI charitable floor is applied."
                ),
                details={
                    "years_bunched": years_bunched,
                    "extra_deduction_cents": bunch.extra_deduction_cents,
                },
            ))

    # --- QCD (retiree direct IRA gift) ------------------------------------
    retired_proxy = (
        profile.retirement_target_year is not None
        and profile.retirement_target_year <= tax_year
    )
    if (
        profile.charitable_intent != "none"
        and profile.annual_giving_cents > 0
        and (retired_proxy or ira_taxable_cents > 0)
    ):
        qcd = qcd_benefit(
            QCDInput(
                intended_giving_cents=profile.annual_giving_cents,
                ira_distribution_available_cents=max(
                    ira_taxable_cents, profile.annual_giving_cents
                ),
                marginal_rate=marginal_rate,
                takes_standard_deduction=takes_standard,
            ),
            charitable_config,
        )
        if qcd.qcd_amount_cents > 0:
            findings.append(_finding(
                title="Give from the IRA as a Qualified Charitable Distribution",
                category="charitable",
                action=(
                    f"Route {_d(qcd.qcd_amount_cents)} of giving directly from the IRA. It "
                    f"is excluded from AGI"
                    + (
                        f", saving {_d(qcd.tax_savings_cents)} versus a gift you couldn't "
                        f"itemize, and counts toward any RMD."
                        if takes_standard else
                        " — its edge here is the lower AGI (IRMAA, SS taxability, NIIT)."
                    )
                ),
                impact_cents=qcd.tax_savings_cents,
                kind="savings" if qcd.tax_savings_cents > 0 else "info",
                citation="IRC §408(d)(8)", caveat=qcd.note,
                details={"qcd_amount_cents": qcd.qcd_amount_cents, "capped": qcd.capped_by_limit},
            ))

    # --- QSBS on a business-sale liquidity event ---------------------------
    if (
        profile.liquidity_event in {"business_sale", "equity_compensation"}
        and profile.liquidity_event_amount_cents > 0
    ):
        gain = profile.liquidity_event_amount_cents
        qsbs = calculate_qsbs(
            QSBSInput(
                eligible_gain_cents=gain, basis_cents=0, holding_years=5,
                acquired_after_obbba=True,
            ),
            corporate_config,
        )
        # Benefit vs an ordinary taxable sale at the LTCG+NIIT proxy.
        ordinary_tax = int((Decimal(gain) * _LTCG_NIIT_PROXY).to_integral_value())
        savings = max(0, ordinary_tax - qsbs.tax_on_taxable_gain_cents)
        if qsbs.qualified and savings > 0:
            findings.append(_finding(
                title="Qualify the sale for the §1202 QSBS exclusion",
                category="liquidity",
                action=(
                    f"Structuring the {_d(gain)} sale to meet §1202 (C-corp original-issue "
                    f"stock, 5-year hold) could exclude {_d(qsbs.excluded_gain_cents)} of gain "
                    f"— up to the ${qsbs.per_issuer_cap_cents // 100_000_000}M per-issuer cap."
                ),
                impact_cents=savings, kind="savings", citation="IRC §1202",
                caveat=(
                    "Requires QSBS eligibility (C-corp, ≤$75M gross assets, qualified trade) "
                    "and the holding period; OBBBA tiers 50/75/100% at 3/4/5 years."
                ),
                details={"excluded_gain_cents": qsbs.excluded_gain_cents,
                         "holding_years_assumed": 5},
            ))

    # --- Relocation timing (realize income after the move) -----------------
    if (
        profile.planned_relocation_state
        and primary_state
        and profile.planned_relocation_state.upper() != primary_state.upper()
        and profile.liquidity_event_amount_cents > 0
    ):
        amount = profile.liquidity_event_amount_cents
        from_cfg = get_state_config(primary_state.upper(), tax_year)
        to_cfg = get_state_config(profile.planned_relocation_state.upper(), tax_year)
        if from_cfg is not None and to_cfg is not None:
            from_tax = calculate_state_tax(
                StateTaxInput(
                    filing_status="single", federal_agi_cents=amount,
                    federal_taxable_income_cents=amount,
                ),
                from_cfg,
            ).total_state_tax_cents
            to_tax = calculate_state_tax(
                StateTaxInput(
                    filing_status="single", federal_agi_cents=amount,
                    federal_taxable_income_cents=amount,
                ),
                to_cfg,
            ).total_state_tax_cents
            delta = from_tax - to_tax
            if delta > 0:
                findings.append(_finding(
                    title=(
                        f"Recognize the gain after establishing {profile.planned_relocation_state} "
                        f"residency"
                    ),
                    category="state",
                    action=(
                        f"Realizing the {_d(amount)} event after the move shifts state tax from "
                        f"{primary_state.upper()} to {profile.planned_relocation_state.upper()}, "
                        f"a {_d(delta)} difference."
                    ),
                    impact_cents=delta, kind="savings", citation="State residency sourcing",
                    caveat=(
                        "Bona-fide residency change required; some states claw back "
                        "source income (deferred comp, installment gains)."
                    ),
                    details={"from_state_tax_cents": from_tax, "to_state_tax_cents": to_tax},
                ))

    # --- Retirement Roth-conversion window (framing) -----------------------
    if (
        profile.retirement_target_year is not None
        and tax_year < profile.retirement_target_year <= tax_year + 12
    ):
        findings.append(_finding(
            title="Plan the low-bracket Roth-conversion window",
            category="retirement",
            action=(
                f"The gap years between retiring in {profile.retirement_target_year} and the "
                f"start of RMDs/Social Security are typically the lowest-bracket years — the "
                f"prime window to convert traditional balances to Roth at low rates."
            ),
            impact_cents=0, kind="info", citation="IRC §408A",
            caveat="Size conversions to fill — not overflow — the target bracket each year.",
            details={"retirement_target_year": profile.retirement_target_year},
        ))

    # --- Education funding (529 superfunding) ------------------------------
    if profile.education_funding:
        findings.append(_finding(
            title="Superfund a 529 with 5-year gift averaging",
            category="education",
            action=(
                "Front-load up to five years of the annual gift exclusion into a 529 in one "
                "year for tax-free education growth; coordinate with the new 529-to-Roth rollover."
            ),
            impact_cents=0, kind="info", citation="IRC §529 / §2503(e)",
            caveat="Gift-tax election on Form 709; state deduction rules vary.",
            details={},
        ))

    return findings
