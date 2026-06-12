"""AI tax-strategist — the "real analysis" layer.

Runs the deterministic optimizers + scans over the client's actual situation
(Roth-conversion bracket-fill, S-corp salary optimization, the opportunity
catalog, IRMAA cliff proximity), assembles structured findings with EXACT
engine-computed numbers, and asks the LLM to author a prioritized, situation-
aware advisor memo. The model reasons and narrates; it never computes a figure —
every dollar in the memo comes from a finding. Degrades to the structured
findings if the LLM is unavailable.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.charitable import charitable_config_for
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.form1040 import Form1040Inputs
from app.engines.irmaa import IRMAAInput, calculate_irmaa
from app.engines.opportunity import find_opportunities
from app.engines.optimizers import optimize_roth_conversion, optimize_scorp_salary
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.integrations.llm import chat, llm_enabled, strip_think
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.entities import (
    aggregate_for_comprehensive,
    business_for_comprehensive,
    list_entities,
)
from app.services.profile import get_profile
from app.services.strategist_context import build_trajectory, goal_aware_findings
from app.services.tax_config import resolve_bracket_set, to_engine_config
from app.state_configs import get_state_config
from app.year_configs import (
    amt_config_for,
    corporate_config_for,
    ctc_config_for,
    irmaa_config_for,
    qbi_config_for,
    scorp_config_for,
    se_config_for,
    ss_config_for,
)

_DISCLAIMER = (
    "Advisor working memo — illustrative planning estimates, not tax advice or a "
    "filed return. Figures assume current-year brackets and the stated amounts; "
    "confirm eligibility, limits, reasonable compensation, and the client's full "
    "facts before acting."
)


def _irmaa_status(filing_status: str) -> str:
    return "mfj" if filing_status == "mfj" else "single"


def _d(cents: int) -> str:
    return f"${cents / 100:,.0f}"


async def _latest_snapshot(db: AsyncSession, tax_year_id: UUID) -> TaxSituationSnapshot | None:
    snap: TaxSituationSnapshot | None = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    return snap


def _finding(
    title: str, category: str, action: str, impact_cents: int, kind: str,
    citation: str, caveat: str, details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": title, "category": category, "recommended_action": action,
        "estimated_impact_cents": impact_cents, "impact_kind": kind,
        "citation": citation, "caveat": caveat, "details": details,
    }


async def _author_memo(
    client_name: str,
    situation: str,
    findings: list[dict[str, Any]],
    settings: Any,
    *,
    objectives_block: str,
    trajectory_summary: str | None,
    return_block: str,
) -> str | None:
    if not llm_enabled(settings) or not findings:
        return None
    lines = []
    for f in findings:
        lines.append(
            f"- [{f['category']}] {f['title']} — {f['recommended_action']} "
            f"Impact: {_d(f['estimated_impact_cents'])} ({f['impact_kind']}). "
            f"Cite: {f['citation']}. Caveat: {f['caveat']}"
        )
    context_sections = [
        f"Client situation: {situation}", "", "CURRENT-YEAR RETURN:", return_block,
    ]
    if objectives_block:
        context_sections += [
            "", "CLIENT OBJECTIVES (what they're trying to accomplish):", objectives_block,
        ]
    if trajectory_summary:
        context_sections += ["", "INCOME TRAJECTORY:", trajectory_summary]
    prompt = (
        f"You are a tax-planning advisor writing a concise working memo for {client_name}.\n"
        + "\n".join(context_sections)
        + "\n\n"
        "Below are findings already computed by the firm's tax engine. Use ONLY these "
        "dollar figures — never invent, round differently, or alter a number. Write a "
        "prioritized memo (3-6 short sections) that is SPECIFIC to this client: explicitly "
        "tie each recommendation to the client's stated objectives and to where their income "
        "is heading (the trajectory). Lead with the highest-impact moves, explain the WHY in "
        "plain language for THIS client, state the caveat for each, and end with a short "
        "'Next steps' list. If an objective has no matching finding, say what's needed to act "
        "on it. Do not promise outcomes.\n\n"
        "COMPUTED FINDINGS (authoritative):\n" + "\n".join(lines) + "\n\nWrite the memo now."
    )
    reply = await chat(
        settings, [{"role": "user", "content": prompt}],
        model=settings.LLM_TEXT_MODEL, max_tokens=1400, no_think=True,
    )
    return strip_think(reply)


_OBJECTIVE_LABELS = {
    "minimize_current_tax": "minimize current-year tax",
    "minimize_lifetime_tax": "minimize lifetime tax",
    "maximize_retirement": "maximize retirement readiness",
    "wealth_transfer": "transfer wealth to heirs",
    "charitable_legacy": "build a charitable legacy",
}


def _objectives_block(profile: Any) -> str:
    if profile is None:
        return ""
    parts: list[str] = []
    if profile.primary_objective in _OBJECTIVE_LABELS:
        parts.append(f"Primary objective: {_OBJECTIVE_LABELS[profile.primary_objective]}.")
    if profile.retirement_target_year:
        parts.append(f"Targets retirement in {profile.retirement_target_year}.")
    if profile.liquidity_event != "none":
        ev = profile.liquidity_event.replace("_", " ")
        yr = f" in {profile.liquidity_event_year}" if profile.liquidity_event_year else ""
        amt = (
            f" (~{_d(profile.liquidity_event_amount_cents)})"
            if profile.liquidity_event_amount_cents
            else ""
        )
        parts.append(f"Expects a {ev} liquidity event{yr}{amt}.")
    if profile.charitable_intent != "none":
        giving = f" (~{_d(profile.annual_giving_cents)}/yr)" if profile.annual_giving_cents else ""
        parts.append(f"Charitable intent: {profile.charitable_intent}{giving}.")
    if profile.estate_priority != "none":
        parts.append(f"Estate/wealth-transfer priority: {profile.estate_priority}.")
    if profile.planned_relocation_state:
        yr = f" in {profile.relocation_year}" if profile.relocation_year else ""
        parts.append(f"Planning to relocate to {profile.planned_relocation_state}{yr}.")
    if profile.roth_preference not in {"no_preference", "advisor_optimize"}:
        parts.append(f"Roth preference: {profile.roth_preference.replace('_', ' ')}.")
    parts.append(
        f"Risk tolerance: {profile.risk_tolerance}; cash-flow sensitivity: "
        f"{profile.cash_flow_sensitivity}."
    )
    if profile.education_funding:
        parts.append("Funding education for dependents.")
    if profile.business_succession != "none":
        parts.append(f"Business succession: {profile.business_succession.replace('_', ' ')}.")
    if profile.notes:
        parts.append(f"Advisor notes: {profile.notes}")
    return " ".join(parts)


def _return_block(comp: Any, agg_corporate_tax_cents: int, state_tax_cents: int | None) -> str:
    parts = [
        f"AGI {_d(comp.federal.agi_cents)}, "
        f"taxable income {_d(comp.federal.taxable_income_cents)}.",
        f"Federal total tax {_d(comp.total_tax_cents)} at a "
        f"{comp.federal.marginal_rate:.0%} marginal rate.",
    ]
    if comp.se_tax_cents:
        parts.append(f"Self-employment tax {_d(comp.se_tax_cents)}.")
    if comp.qbi and comp.qbi.allowed_qbi_deduction_cents:
        parts.append(f"§199A QBI deduction {_d(comp.qbi.allowed_qbi_deduction_cents)}.")
    if comp.amt and comp.amt.amt_applies:
        parts.append(f"AMT applies (+{_d(comp.amt_cents)}).")
    if agg_corporate_tax_cents:
        parts.append(f"C-corp tax {_d(agg_corporate_tax_cents)} on top (double tax).")
    if state_tax_cents:
        parts.append(f"State income tax {_d(state_tax_cents)}.")
    return " ".join(parts)


async def generate_strategist_memo(
    db: AsyncSession, *, workspace_id: UUID, tax_year_id: UUID, settings: Any
) -> dict[str, Any]:
    tax_year = await db.get(ClientTaxYear, tax_year_id)
    if tax_year is None:
        raise LookupError("client tax year not found")
    snapshot = await _latest_snapshot(db, tax_year_id)
    if snapshot is None:
        raise LookupError("no tax situation snapshot for this year")
    client = await db.get(Client, tax_year.client_id)
    client_name = client.display_name if client else "the client"
    profile = await get_profile(db, client_id=tax_year.client_id) if client else None

    bracket_set = await resolve_bracket_set(
        db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("no bracket set for this tax year/filing status")
    config = to_engine_config(bracket_set)
    inputs = Form1040Inputs(**{**snapshot.inputs, "filing_status": tax_year.filing_status})

    entities = await list_entities(db, client_tax_year_id=tax_year_id)
    se_base, biz_sched1, qbi_businesses = business_for_comprehensive(entities)
    net_cap_gain = max(inputs.qualified_dividends_cents, 0) + max(inputs.capital_gain_loss_cents, 0)

    comp = calculate_comprehensive(
        ComprehensiveInput(
            form1040=inputs.model_copy(
                update={"schedule_1_income_cents": inputs.schedule_1_income_cents + biz_sched1}
            ),
            self_employment_base_cents=se_base,
            qbi_businesses=qbi_businesses,
            net_capital_gain_for_qbi_cents=net_cap_gain,
        ),
        config,
        ss_config=ss_config_for(tax_year.tax_year),
        ctc_config=ctc_config_for(tax_year.tax_year),
        amt_config=amt_config_for(tax_year.tax_year),
        se_config=se_config_for(tax_year.tax_year),
        qbi_config=qbi_config_for(tax_year.tax_year),
    )
    marginal = comp.federal.marginal_rate
    findings: list[dict[str, Any]] = []

    # Roth conversion — fill the current bracket cheaply, IRMAA-aware.
    roth = optimize_roth_conversion(
        inputs, config, fill_to_rate=marginal, irmaa_config=irmaa_config_for(tax_year.tax_year),
        irmaa_filing_status=_irmaa_status(tax_year.filing_status),
    )
    if roth.recommended_conversion_cents > 0:
        findings.append(_finding(
            title="Fill the current bracket with a Roth conversion",
            category="retirement",
            action=(
                f"Convert {_d(roth.recommended_conversion_cents)} to Roth this year — it "
                f"taxes at {roth.effective_rate_on_conversion:.0%} now (the top of the current "
                f"bracket) and grows tax-free."
            ),
            impact_cents=roth.tax_cost_cents, kind="cost", citation="IRC §408A",
            caveat=roth.irmaa_warning or "Pay the conversion tax from outside the IRA.",
            details={
                "conversion_cents": roth.recommended_conversion_cents,
                "tax_cost_cents": roth.tax_cost_cents,
                "bracket_ceiling_cents": roth.bracket_ceiling_cents,
            },
        ))

    # S-corp salary optimization per S-corp entity.
    for e in entities:
        if e.kind != "s_corp_k1" or e.amount_cents <= 0:
            continue
        opt = optimize_scorp_salary(
            net_business_income_cents=e.amount_cents + e.shareholder_w2_wages_cents,
            filing_status=tax_year.filing_status,
            taxable_income_before_qbi_cents=snapshot.taxable_income_cents,
            marginal_rate=marginal, scorp_config=scorp_config_for(tax_year.tax_year),
            qbi_config=qbi_config_for(tax_year.tax_year),
            reasonable_min_salary_cents=max(e.shareholder_w2_wages_cents // 2, 0),
        )
        if opt.savings_vs_all_salary_cents > 0:
            findings.append(_finding(
                title=f"Optimize the S-corp salary split ({e.name or 'S-corp'})",
                category="entity",
                action=(
                    f"A reasonable salary near {_d(opt.optimal_salary_cents)} balances payroll "
                    f"tax against the §199A QBI wage limit."
                ),
                impact_cents=opt.savings_vs_all_salary_cents, kind="savings",
                citation="IRC §199A / §1361",
                caveat="Salary must be defensible as reasonable comp.",
                details={
                    "optimal_salary_cents": opt.optimal_salary_cents,
                    "qbi_deduction_cents": opt.qbi_deduction_at_optimal_cents,
                },
            ))

    # Opportunity catalog (the generic structural levers).
    for o in find_opportunities(inputs, config):
        findings.append(_finding(
            title=o.name, category=o.category, action=(
                f"Contributing {_d(o.illustrative_amount_cents)} saves about "
                f"{_d(o.estimated_tax_savings_cents)} at the {o.marginal_rate_used:.0%} margin."
            ),
            impact_cents=o.estimated_tax_savings_cents, kind="savings",
            citation=o.citation, caveat=o.eligibility_note, details={},
        ))

    # IRMAA cliff proximity (planning warning).
    irmaa = calculate_irmaa(
        IRMAAInput(
            filing_status=_irmaa_status(tax_year.filing_status), magi_cents=snapshot.agi_cents
        ),
        irmaa_config_for(tax_year.tax_year),
    )
    if (
        irmaa.distance_to_next_cliff_cents is not None
        and irmaa.cliff_cost_annual_cents
        and irmaa.distance_to_next_cliff_cents < 2_000_000  # within $20k of a cliff
    ):
        findings.append(_finding(
            title="Watch the Medicare IRMAA cliff",
            category="medicare",
            action=(
                f"MAGI is only {_d(irmaa.distance_to_next_cliff_cents)} below the next IRMAA "
                f"tier; crossing it adds {_d(irmaa.cliff_cost_annual_cents)}/yr in premiums "
                f"two years out. Keep income under the threshold."
            ),
            impact_cents=irmaa.cliff_cost_annual_cents, kind="cost",
            citation="42 USC §1395r(i)", caveat="IRMAA uses MAGI from two years prior.",
            details={"distance_cents": irmaa.distance_to_next_cliff_cents},
        ))

    # Goal-aware findings — the client's stated objectives turned into concrete,
    # engine-computed levers (charitable bunching/QCD, §1202 QSBS on a liquidity
    # event, relocation timing, the retirement Roth window, 529 superfunding).
    state_for_block: int | None = None
    if client and client.primary_state:
        st_cfg = get_state_config(client.primary_state.upper(), tax_year.tax_year)
        if st_cfg is not None:
            state_for_block = calculate_state_tax(
                StateTaxInput(
                    filing_status=tax_year.filing_status,
                    federal_agi_cents=comp.federal.agi_cents,
                    federal_taxable_income_cents=comp.federal.taxable_income_cents,
                ),
                st_cfg,
            ).total_state_tax_cents

    corp_tax = aggregate_for_comprehensive(entities).corporate_tax_cents if entities else 0
    findings.extend(
        goal_aware_findings(
            profile=profile,
            tax_year=tax_year.tax_year,
            marginal_rate=marginal,
            agi_cents=comp.federal.agi_cents,
            itemized_deduction_cents=inputs.itemized_deduction_cents,
            standard_deduction_cents=config.standard_deduction_cents,
            ira_taxable_cents=inputs.ira_taxable_cents,
            primary_state=client.primary_state if client else None,
            charitable_config=charitable_config_for(tax_year.tax_year),
            corporate_config=corporate_config_for(tax_year.tax_year),
        )
    )

    # Rank: savings first (by size desc), then costs/warnings, then info.
    _order = {"savings": 0, "cost": 1, "info": 2}
    findings.sort(
        key=lambda f: (_order.get(f["impact_kind"], 1), -f["estimated_impact_cents"])
    )

    # Prior-year income trajectory for situation-aware advice.
    trajectory = await build_trajectory(
        db,
        client_id=tax_year.client_id,
        irmaa_config=irmaa_config_for(tax_year.tax_year),
        irmaa_status=_irmaa_status(tax_year.filing_status),
    )

    situation = (
        f"{tax_year.filing_status.upper()}, tax year {tax_year.tax_year}; current total tax "
        f"{_d(comp.total_tax_cents)} at a {marginal:.0%} marginal rate; "
        f"{'has business entities' if entities else 'wage/investment income'}."
    )
    objectives_block = _objectives_block(profile)
    return_block = _return_block(comp, corp_tax, state_for_block)
    memo = await _author_memo(
        client_name, situation, findings, settings,
        objectives_block=objectives_block,
        trajectory_summary=trajectory.get("summary") if trajectory.get("available") else None,
        return_block=return_block,
    )

    return {
        "client_tax_year_id": str(tax_year_id),
        "client_name": client_name,
        "tax_year": tax_year.tax_year,
        "current_total_tax_cents": comp.total_tax_cents,
        "marginal_rate": str(marginal),
        "findings": findings,
        "total_savings_identified_cents": sum(
            f["estimated_impact_cents"] for f in findings if f["impact_kind"] == "savings"
        ),
        "memo": memo,
        "memo_available": memo is not None,
        "has_profile": profile is not None,
        "objectives_summary": objectives_block or None,
        "trajectory": trajectory,
        "disclaimer": _DISCLAIMER,
    }
