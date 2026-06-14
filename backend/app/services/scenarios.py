"""Live planning recompute + optimizer + EMR sweep over the pure engines.

This is the search layer behind the Lab surface. It loads the client's current
situation (latest snapshot + resolved brackets), then drives the EXISTING engines
to answer what-ifs with REAL numbers and the traces that make the instruments
honest:

  * `recompute` — apply a structural mutation, re-run Form 1040, return the real
    before/after delta (a deferral lowers AGI, which can cross brackets / change
    QBI headroom / NIIT exposure — never a flat amount × rate).
  * `emr_sweep` — sweep one income field upward and read the EFFECTIVE marginal
    rate at each step as Δ(total tax) / Δincome between consecutive recomputes,
    so phase-outs and cliffs show up as the bumps they actually are. IRMAA tier
    and NIIT thresholds are overlaid as labeled income lines (threshold only —
    their dollar cost is not faked here).
  * `optimize_roth` / `optimize_scorp` — call the existing optimizers exactly as
    the strategist does, plus a step-by-step engine-recomputed trace/curve so the
    crossover chart and salary curve are real, not interpolated.

No new tables, no new model. Pure-compute under a tenant DB session that only
loads the situation. All money is integer cents; rates are the engines' Decimals.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.form1040 import (
    Form1040Inputs,
    TaxConfig,
    calculate_form1040,
)
from app.engines.multiyear import (
    InputMutation,
    ScenarioRecompute,
    recompute_scenario,
)
from app.engines.optimizers import optimize_roth_conversion, optimize_scorp_salary
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.entities import list_entities
from app.services.tax_config import resolve_bracket_set, to_engine_config
from app.year_configs import irmaa_config_for, qbi_config_for, scorp_config_for

# Number of recompute steps used to draw the Roth crossover trace and the S-corp
# salary curve. Enough to show the shape without hammering the engine.
_ROTH_TRACE_STEPS = 10
_SCORP_CURVE_STEPS = 10
# A "next dollar" probe: +$100 is large enough to land inside a bracket yet small
# enough to read the local slope as the true marginal rate.
_NEXT_DOLLAR_PROBE_CENTS = 10_000


def _irmaa_status(filing_status: str) -> str:
    # IRMAA models single / mfj / mfs_lived_with_spouse; everything that isn't a
    # joint return uses the single thresholds (matches analysis.py / strategist.py).
    return "mfj" if filing_status == "mfj" else "single"


async def _latest_snapshot(db: AsyncSession, tax_year_id: UUID) -> TaxSituationSnapshot | None:
    snapshot: TaxSituationSnapshot | None = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    return snapshot


async def _assemble(
    db: AsyncSession, tax_year_id: UUID
) -> tuple[Form1040Inputs, TaxConfig, TaxSituationSnapshot, ClientTaxYear]:
    """Canonical situation load (mirrors services/analysis.py): the tax year, its
    latest snapshot, and the resolved engine config + base inputs."""
    tax_year = await db.get(ClientTaxYear, tax_year_id)
    if tax_year is None:
        raise LookupError("client tax year not found")
    snapshot = await _latest_snapshot(db, tax_year_id)
    if snapshot is None:
        raise LookupError("no tax situation snapshot for this year")
    bracket_set = await resolve_bracket_set(
        db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("no bracket set for this tax year/filing status")
    config = to_engine_config(bracket_set)
    inputs = Form1040Inputs(**{**snapshot.inputs, "filing_status": tax_year.filing_status})
    return inputs, config, snapshot, tax_year


async def recompute(
    db: AsyncSession,
    *,
    tax_year_id: UUID,
    set_fields: dict[str, int],
    delta_fields: dict[str, int],
) -> ScenarioRecompute:
    """Re-run the federal engine with the mutation applied; return the real delta."""
    inputs, config, _snapshot, _tax_year = await _assemble(db, tax_year_id)
    mutation = InputMutation(set_fields=set_fields, delta_fields=delta_fields)
    try:
        return recompute_scenario(inputs, config, mutation)
    except KeyError as exc:
        # The engine rejects unknown field names so a typo can't silently no-op a
        # strategy; surface it as a 422 rather than a 500.
        raise ValueError(f"unknown input field: {exc}") from exc


def _cliff_overlays(
    *, filing_status: str, tax_year: int, config: TaxConfig
) -> list[dict[str, Any]]:
    """Labeled income-threshold lines for the EMR terrain. We overlay only the
    threshold income (real, from config) — NOT a fabricated dollar cost."""
    overlays: list[dict[str, Any]] = []
    irmaa_cfg = irmaa_config_for(tax_year)
    status = _irmaa_status(filing_status)
    for threshold_cents, target_tier in irmaa_cfg.cliffs.get(status, []):
        overlays.append(
            {
                "label": f"IRMAA tier {target_tier}",
                "threshold_cents": threshold_cents,
                "kind": "irmaa",
            }
        )
    if config.auxiliary.niit_threshold_cents is not None:
        overlays.append(
            {
                "label": "NIIT 3.8% threshold",
                "threshold_cents": config.auxiliary.niit_threshold_cents,
                "kind": "niit",
            }
        )
    overlays.sort(key=lambda o: o["threshold_cents"])
    return overlays


async def emr_sweep(
    db: AsyncSession,
    *,
    tax_year_id: UUID,
    start_cents: int | None,
    step_cents: int,
    steps: int,
    field: str,
) -> dict[str, Any]:
    """Sweep `field` upward and report the EFFECTIVE marginal rate at each step.

    The marginal at point i = Δ(total tax) between point i and point i+1, divided
    by `step_cents`. That is the whole point: it captures phase-outs and cliffs
    (an IRMAA jump, NIIT switching on) as the real next-dollar cost, not the
    statutory bracket rate. `true_next_dollar_rate` is the local slope at the base
    income (+$100), and `nominal_marginal_rate` is the engine's bracket rate at
    base for contrast."""
    if step_cents <= 0:
        raise ValueError("step_cents must be positive")
    if steps <= 0:
        raise ValueError("steps must be positive")
    inputs, config, _snapshot, tax_year = await _assemble(db, tax_year_id)

    data = inputs.model_dump()
    if field not in data:
        raise ValueError(f"unknown input field: {field}")
    if not isinstance(data[field], int):
        raise ValueError(f"field is not a sweepable integer amount: {field}")
    current = data[field]
    base_value = current if start_cents is None else start_cents

    base_result = calculate_form1040(inputs, config)

    # Recompute total tax at each sweep point by SETTING `field` absolutely (so a
    # point's value is exactly base_value + i·step regardless of the field's
    # current value), then read effective marginal as the forward difference.
    def tax_at(value: int) -> int:
        rec = recompute_scenario(
            inputs, config, InputMutation(set_fields={field: value}), base_result=base_result
        )
        return rec.scenario.total_tax_cents

    point_count = steps + 1  # inclusive of the start point
    incomes = [base_value + i * step_cents for i in range(point_count + 1)]
    taxes = [tax_at(v) for v in incomes]

    points: list[dict[str, Any]] = []
    for i in range(point_count):
        marginal = Decimal(taxes[i + 1] - taxes[i]) / Decimal(step_cents)
        points.append(
            {
                "income_cents": incomes[i],
                "total_tax_cents": taxes[i],
                "marginal_rate": str(marginal),
            }
        )

    # True next-dollar rate at the BASE income (the current situation's value):
    # Δtax for a small +probe, normalized to a per-dollar rate.
    near = recompute_scenario(
        inputs,
        config,
        InputMutation(delta_fields={field: _NEXT_DOLLAR_PROBE_CENTS}),
        base_result=base_result,
    )
    true_next_dollar = Decimal(near.tax_delta_cents) / Decimal(_NEXT_DOLLAR_PROBE_CENTS)

    return {
        "field": field,
        "base_income_cents": base_value,
        "points": points,
        "true_next_dollar_rate": str(true_next_dollar),
        "nominal_marginal_rate": str(base_result.marginal_rate),
        "cliff_overlays": _cliff_overlays(
            filing_status=tax_year.filing_status, tax_year=tax_year.tax_year, config=config
        ),
    }


async def optimize_roth(db: AsyncSession, *, tax_year_id: UUID) -> dict[str, Any]:
    """Roth-conversion bracket fill (IRMAA-aware) + an engine-recomputed trace so
    the crossover chart is real. Fill target = the base return's marginal bracket
    rate, the same fill semantics the strategist uses."""
    inputs, config, _snapshot, tax_year = await _assemble(db, tax_year_id)
    base_result = calculate_form1040(inputs, config)
    fill_to_rate = base_result.marginal_rate

    roth = optimize_roth_conversion(
        inputs,
        config,
        fill_to_rate=fill_to_rate,
        irmaa_config=irmaa_config_for(tax_year.tax_year),
        irmaa_filing_status=_irmaa_status(tax_year.filing_status),
    )

    # Trace: sweep the conversion from $0 up to the recommended headroom (the
    # bracket fill), recomputing the incremental tax cost at each step through the
    # engine. Each step's marginal = Δtax(prev→this) / step amount.
    trace: list[dict[str, Any]] = []
    target = roth.recommended_conversion_cents
    if target > 0:
        step = max(target // _ROTH_TRACE_STEPS, 1)
        amounts = list(range(0, target + 1, step))
        if amounts[-1] != target:
            amounts.append(target)
        prev_cost = 0
        prev_amount = 0
        for amount in amounts:
            if amount == 0:
                rec = None
                cost = 0
            else:
                rec = recompute_scenario(
                    inputs,
                    config,
                    InputMutation(delta_fields={"ira_taxable_cents": amount}),
                    base_result=base_result,
                )
                cost = rec.tax_delta_cents
            increment = amount - prev_amount
            marginal = (
                Decimal(cost - prev_cost) / Decimal(increment) if increment > 0 else Decimal("0")
            )
            trace.append(
                {
                    "conversion_cents": amount,
                    "tax_cost_cents": cost,
                    "marginal_at_step": str(marginal),
                }
            )
            prev_cost, prev_amount = cost, amount

    return {
        "recommended_conversion_cents": roth.recommended_conversion_cents,
        "tax_cost_cents": roth.tax_cost_cents,
        "effective_rate_on_conversion": str(roth.effective_rate_on_conversion),
        "bracket_ceiling_cents": roth.bracket_ceiling_cents,
        "irmaa_warning": roth.irmaa_warning,
        "trace": trace,
    }


async def optimize_scorp(
    db: AsyncSession, *, tax_year_id: UUID, entity_id: UUID | None = None
) -> dict[str, Any]:
    """S-corp salary optimization (payroll vs §199A QBI) for one S-corp entity +
    an engine-recomputed salary→tax curve. Calls the optimizer exactly as the
    strategist does. Raises LookupError if there is no matching S-corp entity."""
    inputs, config, snapshot, tax_year = await _assemble(db, tax_year_id)
    base_result = calculate_form1040(inputs, config)
    marginal = base_result.marginal_rate

    entities = await list_entities(db, client_tax_year_id=tax_year_id)
    target = None
    for e in entities:
        if e.kind != "s_corp_k1" or e.amount_cents <= 0:
            continue
        if entity_id is not None and e.id != entity_id:
            continue
        target = e
        break
    if target is None:
        raise LookupError("no S-corp entity found for this tax year")

    # Net business income and reasonable-comp floor exactly as strategist.py.
    net_income = target.amount_cents + target.shareholder_w2_wages_cents
    reasonable_min = max(target.shareholder_w2_wages_cents // 2, 0)
    opt = optimize_scorp_salary(
        net_business_income_cents=net_income,
        filing_status=tax_year.filing_status,
        taxable_income_before_qbi_cents=snapshot.taxable_income_cents,
        marginal_rate=marginal,
        scorp_config=scorp_config_for(tax_year.tax_year),
        qbi_config=qbi_config_for(tax_year.tax_year),
        reasonable_min_salary_cents=reasonable_min,
    )

    # Curve: sweep salary from the reasonable-comp floor to the full net income,
    # recomputing the owner's TOTAL federal tax at each point through the 1040
    # engine. The S-corp split moves dollars between W-2 wages (in total income)
    # and the QBI deduction; both flow through calculate_form1040, so the curve is
    # a real recompute, not the optimizer's internal net-cost metric.
    floor = max(min(reasonable_min, net_income), 0)
    span = net_income - floor
    curve: list[dict[str, Any]] = []
    if net_income > 0:
        step = max(span // _SCORP_CURVE_STEPS, 1) if span > 0 else 1
        salaries = list(range(floor, net_income + 1, step))
        if not salaries or salaries[-1] != net_income:
            salaries.append(net_income)
        for salary in salaries:
            salary = min(max(salary, 0), net_income)
            # Salary → owner W-2 wages; the remaining profit → QBI. Recompute the
            # full federal return for this split.
            qbi_income = net_income - salary
            rec = recompute_scenario(
                inputs,
                config,
                InputMutation(
                    delta_fields={
                        "wages_cents": salary,
                        "schedule_1_income_cents": qbi_income,
                    }
                ),
                base_result=base_result,
            )
            curve.append(
                {
                    "salary_cents": salary,
                    "total_tax_cents": rec.scenario.total_tax_cents,
                }
            )

    return {
        "optimal_salary_cents": opt.optimal_salary_cents,
        "savings_vs_all_salary_cents": opt.savings_vs_all_salary_cents,
        "qbi_deduction_at_optimal_cents": opt.qbi_deduction_at_optimal_cents,
        "curve": curve,
    }
