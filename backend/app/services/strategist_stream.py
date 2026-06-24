"""Streaming AI tax-strategist — the Console's live "plan → engine-call feed →
memo" view (spec §9.6 / Console door 2).

This is the STREAMING twin of ``strategist.generate_strategist_memo``. It runs
the SAME deterministic optimizers + scans over the client's actual situation
(comprehensive return, Roth bracket-fill, S-corp salary split per entity, the
opportunity catalog, the IRMAA cliff check, the goal-aware levers) and then asks
the LLM to author the memo — but instead of returning one blob at the end it
``yield``s an event around each step so the Console can render progress live: the
plan card, each engine call as it starts and finishes, each finding as it lands,
then the authored memo.

It is a VIEW: it does NOT persist anything (the existing
``POST /clients/tax-years/{id}/strategist/run`` is the persisting path). Every
dollar in every event is engine-computed — the stream only narrates progress
around the real engine output; the model never produces a figure.

The figures mirror ``strategist.py`` exactly (same engine calls, same inputs),
so a stream and a persisted run over the same snapshot agree to the cent.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.charitable import charitable_config_for
from app.engines.comprehensive import ComprehensiveInput, calculate_comprehensive
from app.engines.form1040 import Form1040Inputs
from app.engines.irmaa import IRMAAInput, calculate_irmaa
from app.engines.opportunity import find_opportunities
from app.engines.optimizers import optimize_roth_conversion, optimize_scorp_salary
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.integrations.llm import llm_enabled
from app.models.client import Client
from app.models.tax_year import ClientTaxYear
from app.services.entities import (
    aggregate_for_comprehensive,
    business_for_comprehensive,
    list_entities,
)
from app.services.profile import get_profile
from app.services.strategist import (
    _author_memo,
    _d,
    _finding,
    _irmaa_status,
    _latest_snapshot,
    _objectives_block,
    _return_block,
    _source_documents_block,
)
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

# Stable step keys for the plan card and the engine_call events. The two S-corp
# variants keep the same `name` ("scorp_salary"); the optimizer step is present
# in the plan only when the client actually has business entities (its narration
# is per-entity, so the plan lists it once as a header).
STEP_COMPREHENSIVE = "comprehensive_return"
STEP_ROTH = "roth_optimizer"
STEP_SCORP = "scorp_optimizer"
STEP_OPPORTUNITY = "opportunity_scan"
STEP_IRMAA = "irmaa_check"
STEP_GOALS = "goal_aware"
STEP_MEMO = "author_memo"

_STEP_LABELS = {
    STEP_COMPREHENSIVE: "Comprehensive return",
    STEP_ROTH: "Roth-conversion optimizer",
    STEP_SCORP: "S-corp salary optimizer",
    STEP_OPPORTUNITY: "Opportunity scan",
    STEP_IRMAA: "IRMAA cliff check",
    STEP_GOALS: "Goal-aware levers",
    STEP_MEMO: "Author memo",
}


def build_plan_steps(*, has_entities: bool) -> list[dict[str, str]]:
    """The ordered plan card: the named steps the strategist is about to run.

    Pure — no DB, no engines — so the ordering can be unit-tested in isolation.
    The S-corp optimizer step appears only when the client has business
    entities (it has nothing to narrate otherwise), matching the per-entity loop
    in ``strategist.generate_strategist_memo``.
    """
    keys = [STEP_COMPREHENSIVE, STEP_ROTH]
    if has_entities:
        keys.append(STEP_SCORP)
    keys += [STEP_OPPORTUNITY, STEP_IRMAA, STEP_GOALS, STEP_MEMO]
    return [{"key": k, "label": _STEP_LABELS[k]} for k in keys]


def sse_format(event: dict[str, Any]) -> str:
    """Serialize one event dict as a single Server-Sent-Events frame."""
    return f"data: {json.dumps(event)}\n\n"


def _engine_running(name: str) -> dict[str, Any]:
    return {"type": "engine_call", "name": name, "status": "running"}


def _engine_done(name: str, summary: str) -> dict[str, Any]:
    return {"type": "engine_call", "name": name, "status": "done", "summary": summary}


async def stream_strategist_run(
    db: AsyncSession, *, workspace_id: UUID, tax_year_id: UUID, settings: Any
) -> AsyncIterator[dict[str, Any]]:
    """Run the strategist and yield event dicts in order (see module docstring).

    Raises ``LookupError`` BEFORE any event is yielded if the tax year, snapshot,
    or bracket set is missing — so the endpoint can map it to a 404 before the
    SSE stream opens. Every figure in every event is real engine output.
    """
    # ---- Resolve context (may raise LookupError before streaming starts) ----
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
    has_entities = bool(entities)

    # ---- 1. Plan card -------------------------------------------------------
    yield {"type": "plan", "steps": build_plan_steps(has_entities=has_entities)}

    # ---- 2. Comprehensive return -------------------------------------------
    yield _engine_running(STEP_COMPREHENSIVE)
    se_base, biz_sched1, qbi_businesses = business_for_comprehensive(entities)
    net_cap_gain = (
        max(inputs.qualified_dividends_cents, 0) + max(inputs.capital_gain_loss_cents, 0)
    )
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
    yield _engine_done(
        STEP_COMPREHENSIVE,
        f"Total tax {_d(comp.total_tax_cents)} at a {marginal:.0%} marginal rate.",
    )

    findings: list[dict[str, Any]] = []

    # ---- 3. Roth conversion -------------------------------------------------
    yield _engine_running(STEP_ROTH)
    roth = optimize_roth_conversion(
        inputs, config, fill_to_rate=marginal,
        irmaa_config=irmaa_config_for(tax_year.tax_year),
        irmaa_filing_status=_irmaa_status(tax_year.filing_status),
    )
    if roth.recommended_conversion_cents > 0:
        finding = _finding(
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
        )
        findings.append(finding)
        yield {"type": "finding", "finding": finding}
        yield _engine_done(
            STEP_ROTH,
            f"Convert {_d(roth.recommended_conversion_cents)} "
            f"(tax cost {_d(roth.tax_cost_cents)}).",
        )
    else:
        yield _engine_done(STEP_ROTH, "No bracket headroom for a conversion this year.")

    # ---- 4. S-corp salary optimization (per S-corp entity) ------------------
    if has_entities:
        yield _engine_running(STEP_SCORP)
        scorp_found = 0
        best_savings = 0
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
                finding = _finding(
                    title=f"Optimize the S-corp salary split ({e.name or 'S-corp'})",
                    category="entity",
                    action=(
                        f"A reasonable salary near {_d(opt.optimal_salary_cents)} balances "
                        f"payroll tax against the §199A QBI wage limit."
                    ),
                    impact_cents=opt.savings_vs_all_salary_cents, kind="savings",
                    citation="IRC §199A / §1361",
                    caveat="Salary must be defensible as reasonable comp.",
                    details={
                        "optimal_salary_cents": opt.optimal_salary_cents,
                        "qbi_deduction_cents": opt.qbi_deduction_at_optimal_cents,
                    },
                )
                findings.append(finding)
                scorp_found += 1
                best_savings = max(best_savings, opt.savings_vs_all_salary_cents)
                yield {"type": "finding", "finding": finding}
        summary = (
            f"{scorp_found} salary split(s); best saves {_d(best_savings)}."
            if scorp_found
            else "No salary-split savings for the S-corp entities."
        )
        yield _engine_done(STEP_SCORP, summary)

    # ---- 5. Opportunity catalog --------------------------------------------
    yield _engine_running(STEP_OPPORTUNITY)
    opp_found = 0
    for o in find_opportunities(inputs, config):
        finding = _finding(
            title=o.name, category=o.category,
            action=(
                f"Contributing {_d(o.illustrative_amount_cents)} saves about "
                f"{_d(o.estimated_tax_savings_cents)} at the {o.marginal_rate_used:.0%} margin."
            ),
            impact_cents=o.estimated_tax_savings_cents, kind="savings",
            citation=o.citation, caveat=o.eligibility_note, details={},
        )
        findings.append(finding)
        opp_found += 1
        yield {"type": "finding", "finding": finding}
    yield _engine_done(STEP_OPPORTUNITY, f"{opp_found} structural lever(s) identified.")

    # ---- 6. IRMAA cliff proximity ------------------------------------------
    yield _engine_running(STEP_IRMAA)
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
        finding = _finding(
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
        )
        findings.append(finding)
        yield {"type": "finding", "finding": finding}
        yield _engine_done(
            STEP_IRMAA,
            f"{_d(irmaa.distance_to_next_cliff_cents)} below the next tier "
            f"(+{_d(irmaa.cliff_cost_annual_cents)}/yr).",
        )
    else:
        yield _engine_done(STEP_IRMAA, "No nearby IRMAA cliff.")

    # ---- 7. Goal-aware levers ----------------------------------------------
    yield _engine_running(STEP_GOALS)
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
    goal_findings = goal_aware_findings(
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
    for finding in goal_findings:
        findings.append(finding)
        yield {"type": "finding", "finding": finding}
    yield _engine_done(STEP_GOALS, f"{len(goal_findings)} goal-aligned lever(s).")

    # ---- Rank (identical to strategist.py): savings desc, then cost, info ----
    _order = {"savings": 0, "cost": 1, "info": 2}
    findings.sort(
        key=lambda f: (_order.get(f["impact_kind"], 1), -f["estimated_impact_cents"])
    )

    # Prior-year income trajectory (used to make the memo situation-aware).
    trajectory = await build_trajectory(
        db,
        client_id=tax_year.client_id,
        irmaa_config=irmaa_config_for(tax_year.tax_year),
        irmaa_status=_irmaa_status(tax_year.filing_status),
    )

    # ---- 8. Author memo -----------------------------------------------------
    #
    # The LLM client (app.integrations.llm.chat) performs a single, NON-streaming
    # chat completion — one httpx POST that returns the whole assistant message.
    # It exposes no token-by-token streaming, so we honestly emit the finished
    # memo as ONE `memo` event rather than faking `memo_delta` chunks. (If the
    # client later grows real SSE/`stream=True` token output, switch this to emit
    # `memo_delta` chunks then `memo_done`.)
    yield _engine_running(STEP_MEMO)
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
        source_documents_block=_source_documents_block(tax_year),
    )
    if memo is not None:
        yield {"type": "memo", "text": memo}
        yield _engine_done(STEP_MEMO, "Memo authored.")
    else:
        # No LLM configured (or no findings) — be explicit; the findings already
        # streamed are the deliverable in that degraded mode.
        reason = (
            "LLM not configured — see the streamed findings."
            if not llm_enabled(settings)
            else "No findings to author a memo from."
        )
        yield _engine_done(STEP_MEMO, reason)

    # ---- 9. Done ------------------------------------------------------------
    yield {
        "type": "done",
        "current_total_tax_cents": comp.total_tax_cents,
        "total_savings_identified_cents": sum(
            f["estimated_impact_cents"] for f in findings if f["impact_kind"] == "savings"
        ),
    }
