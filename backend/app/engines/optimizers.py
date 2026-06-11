"""Optimization routines — the search layer that turns the engines into advice.

These find the SPECIFIC best move for a client by searching over the
deterministic engines: how much to convert to Roth to fill a bracket without
tripping an IRMAA cliff, and the S-corp salary that minimizes the combined
payroll-tax + lost-QBI cost. The numbers are exact (engine-computed); the
strategist agent narrates them.

Pure functions, integer cents.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.engines.form1040 import Form1040Inputs, RateBracket, TaxConfig, calculate_form1040
from app.engines.irmaa import IRMAAConfig, IRMAAInput, calculate_irmaa
from app.engines.multiyear import InputMutation, recompute_scenario
from app.engines.qbi import QBIConfig, QBIInput, calculate_qbi
from app.engines.scorp import SCorpConfig, SCorpInput, calculate_scorp_split


def _ceiling_for_rate(brackets: list[RateBracket], target_rate: Decimal) -> int | None:
    """Upper bound of the highest ordinary bracket whose rate ≤ target_rate.
    None if that bracket is open-ended (the top bracket)."""
    ceiling: int | None = None
    for b in sorted(brackets, key=lambda x: x.lower_bound_cents):
        if b.rate <= target_rate:
            ceiling = b.upper_bound_cents
    return ceiling


# ---------------------------------------------------------------------------
# Roth conversion optimizer
# ---------------------------------------------------------------------------


class RothConversionResult(BaseModel):
    recommended_conversion_cents: int
    tax_cost_cents: int
    effective_rate_on_conversion: Decimal
    current_taxable_income_cents: int
    fill_to_bracket_rate: Decimal
    bracket_ceiling_cents: int | None
    irmaa_warning: str | None = None


def optimize_roth_conversion(
    inputs: Form1040Inputs,
    config: TaxConfig,
    *,
    fill_to_rate: Decimal,
    irmaa_config: IRMAAConfig | None = None,
    irmaa_filing_status: str = "single",
) -> RothConversionResult:
    """Recommend the Roth conversion that fills ordinary income to the top of
    the `fill_to_rate` bracket, priced through the real engine, with an IRMAA
    cliff warning (the conversion raises MAGI, which governs Medicare premiums
    two years later)."""
    base = calculate_form1040(inputs, config)
    ceiling = _ceiling_for_rate(config.ordinary_brackets, fill_to_rate)
    headroom = max((ceiling - base.taxable_income_cents), 0) if ceiling is not None else 0

    cost = 0
    eff = Decimal("0")
    if headroom > 0:
        rec = recompute_scenario(
            inputs, config, InputMutation(delta_fields={"ira_taxable_cents": headroom}),
            base_result=base,
        )
        cost = rec.tax_delta_cents
        eff = (Decimal(cost) / Decimal(headroom)) if headroom else Decimal("0")

    irmaa_warning: str | None = None
    if irmaa_config is not None and headroom > 0:
        before = calculate_irmaa(
            IRMAAInput(filing_status=irmaa_filing_status, magi_cents=base.agi_cents),
            irmaa_config,
        )
        after = calculate_irmaa(
            IRMAAInput(filing_status=irmaa_filing_status, magi_cents=base.agi_cents + headroom),
            irmaa_config,
        )
        if after.irmaa_tier > before.irmaa_tier:
            delta = after.total_irmaa_annual_cents - before.total_irmaa_annual_cents
            irmaa_warning = (
                f"This conversion pushes MAGI from IRMAA tier {before.irmaa_tier} to "
                f"{after.irmaa_tier}, adding ~{delta}c/yr in Medicare premiums two years out. "
                f"Consider converting only up to the tier threshold."
            )

    return RothConversionResult(
        recommended_conversion_cents=headroom,
        tax_cost_cents=cost,
        effective_rate_on_conversion=eff,
        current_taxable_income_cents=base.taxable_income_cents,
        fill_to_bracket_rate=fill_to_rate,
        bracket_ceiling_cents=ceiling,
        irmaa_warning=irmaa_warning,
    )


# ---------------------------------------------------------------------------
# S-corp salary optimizer (payroll tax vs QBI tradeoff)
# ---------------------------------------------------------------------------


class SalaryOptimizationResult(BaseModel):
    optimal_salary_cents: int
    payroll_tax_at_optimal_cents: int
    qbi_deduction_at_optimal_cents: int
    net_cost_at_optimal_cents: int  # payroll tax − QBI value
    all_salary_net_cost_cents: int
    savings_vs_all_salary_cents: int
    candidates_evaluated: int


def optimize_scorp_salary(
    *,
    net_business_income_cents: int,
    filing_status: str,
    taxable_income_before_qbi_cents: int,
    marginal_rate: Decimal,
    scorp_config: SCorpConfig,
    qbi_config: QBIConfig,
    reasonable_min_salary_cents: int = 0,
    step_cents: int = 500_000,
) -> SalaryOptimizationResult:
    """Search the reasonable salary that minimizes combined cost = payroll tax
    − (QBI deduction × marginal rate). Lower salary cuts payroll tax but, for a
    high earner above the §199A threshold, also cuts the W-2 wage limit (and
    thus QBI); the optimum balances the two. Below the threshold QBI is
    wage-independent, so the optimum is just the reasonable-comp floor."""
    income = max(net_business_income_cents, 0)
    floor = max(min(reasonable_min_salary_cents, income), 0)

    def net_cost(salary: int) -> tuple[int, int, int]:
        salary = min(salary, income)
        payroll = calculate_scorp_split(
            SCorpInput(
                filing_status=filing_status,
                net_business_income_cents=income,
                reasonable_salary_cents=salary,
            ),
            scorp_config,
        ).chosen.total_cents
        qbi = calculate_qbi(
            QBIInput(
                filing_status=filing_status,
                qualified_business_income_cents=income - salary,
                w2_wages_cents=salary,
                taxable_income_before_qbi_cents=taxable_income_before_qbi_cents,
            ),
            qbi_config,
        ).allowed_qbi_deduction_cents
        qbi_value = int(Decimal(qbi) * marginal_rate)
        return payroll - qbi_value, payroll, qbi

    candidates = list(range(floor, income + 1, step_cents))
    if not candidates or candidates[-1] != income:
        candidates.append(income)

    best_salary = floor
    best = net_cost(floor)
    for salary in candidates:
        c = net_cost(salary)
        if c[0] < best[0]:
            best, best_salary = c, salary

    all_salary = net_cost(income)
    return SalaryOptimizationResult(
        optimal_salary_cents=best_salary,
        payroll_tax_at_optimal_cents=best[1],
        qbi_deduction_at_optimal_cents=best[2],
        net_cost_at_optimal_cents=best[0],
        all_salary_net_cost_cents=all_salary[0],
        savings_vs_all_salary_cents=all_salary[0] - best[0],
        candidates_evaluated=len(candidates),
    )
