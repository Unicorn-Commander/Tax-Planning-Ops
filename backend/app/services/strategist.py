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

from app.engine_configs import ty2025_qbi_config, ty2025_scorp_config, ty2025_se_tax_config
from app.engines.amt import ty2025_amt_config
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.ctc import ty2025_ctc_config
from app.engines.form1040 import Form1040Inputs
from app.engines.irmaa import IRMAAInput, calculate_irmaa, ty2025_irmaa_config
from app.engines.opportunity import find_opportunities
from app.engines.optimizers import optimize_roth_conversion, optimize_scorp_salary
from app.engines.ss_taxability import ty2025_ss_config
from app.integrations.llm import chat, llm_enabled, strip_think
from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.entities import business_for_comprehensive, list_entities
from app.services.tax_config import resolve_bracket_set, to_engine_config

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
    client_name: str, situation: str, findings: list[dict[str, Any]], settings: Any
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
    prompt = (
        f"You are a tax-planning advisor writing a concise working memo for {client_name}.\n"
        f"Client situation: {situation}\n\n"
        "Below are findings already computed by the firm's tax engine. Use ONLY these "
        "dollar figures — never invent, round differently, or alter a number. Write a "
        "prioritized memo (3-6 short sections): lead with the highest-impact moves, "
        "explain the WHY in plain language specific to this client, state the caveat for "
        "each, and end with a short 'Next steps' list. Do not promise outcomes.\n\n"
        "COMPUTED FINDINGS (authoritative):\n" + "\n".join(lines) + "\n\nWrite the memo now."
    )
    reply = await chat(
        settings, [{"role": "user", "content": prompt}],
        model=settings.LLM_TEXT_MODEL, max_tokens=1100, no_think=True,
    )
    return strip_think(reply)


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
        config, ss_config=ty2025_ss_config(), ctc_config=ty2025_ctc_config(),
        amt_config=ty2025_amt_config(), se_config=ty2025_se_tax_config(),
        qbi_config=ty2025_qbi_config(),
    )
    marginal = comp.federal.marginal_rate
    findings: list[dict[str, Any]] = []

    # Roth conversion — fill the current bracket cheaply, IRMAA-aware.
    roth = optimize_roth_conversion(
        inputs, config, fill_to_rate=marginal, irmaa_config=ty2025_irmaa_config(),
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
            marginal_rate=marginal, scorp_config=ty2025_scorp_config(),
            qbi_config=ty2025_qbi_config(),
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
        ty2025_irmaa_config(),
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

    # Rank: savings first (by size desc), then costs/warnings.
    findings.sort(
        key=lambda f: (0 if f["impact_kind"] == "savings" else 1, -f["estimated_impact_cents"])
    )

    situation = (
        f"{tax_year.filing_status.upper()}, tax year {tax_year.tax_year}; current total tax "
        f"{_d(comp.total_tax_cents)} at a {marginal:.0%} marginal rate; "
        f"{'has business entities' if entities else 'wage/investment income'}."
    )
    memo = await _author_memo(client_name, situation, findings, settings)

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
        "disclaimer": _DISCLAIMER,
    }
