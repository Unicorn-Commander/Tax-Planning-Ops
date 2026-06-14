"""Tests for the live planning sweep/recompute/optimizer-trace logic.

The engines are PURE, so these exercise the math the scenarios service is built
on WITHOUT a DB: construct `Form1040Inputs` + a round `TaxConfig` directly (as
test_optimizers.py / test_multiyear_engine.py do) and assert that

  * the EMR marginal at a step equals (Δtax / Δincome) from real recomputes,
    including across a cliff/phase-in where it diverges from the bracket rate;
  * a deductible-contribution delta lowers tax (recompute, not amount × rate);
  * the Roth crossover trace is monotonic non-decreasing in tax cost.

The forward-difference formula here is identical to the one in
`services.scenarios.emr_sweep` / `.optimize_roth`, so it pins that logic.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    RateBracket,
    TaxConfig,
    calculate_form1040,
)
from app.engines.multiyear import InputMutation, recompute_scenario


def _config() -> TaxConfig:
    # Round, hand-computable config (mirrors the golden engine tests):
    #   ordinary 0-10k@10% | 10k-50k@20% | 50k+@30%; std ded 15k;
    #   LTCG 0-40k@0% then 15%; NIIT/AddlMedicare @100k.
    return TaxConfig(
        tax_year=2025,
        filing_status="single",
        standard_deduction_cents=1_500_000,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.10")),
            RateBracket(
                lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.20")
            ),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.30")),
        ],
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=[
                RateBracket(lower_bound_cents=0, upper_bound_cents=4_000_000, rate=Decimal("0")),
                RateBracket(
                    lower_bound_cents=4_000_000, upper_bound_cents=None, rate=Decimal("0.15")
                ),
            ],
            niit_threshold_cents=10_000_000,
            niit_rate=Decimal("0.0380"),
            additional_medicare_threshold_cents=10_000_000,
            additional_medicare_rate=Decimal("0.0090"),
            capital_loss_limit_cents=300_000,
        ),
    )


def _marginal_at(field: str, value: int, step: int, config: TaxConfig) -> Decimal:
    """Replicates services.scenarios.emr_sweep's effective marginal at a sweep
    point: Δ(total tax) between this point and the next, over the step."""
    inputs = Form1040Inputs(filing_status="single")
    base_result = calculate_form1040(inputs, config)
    here = recompute_scenario(
        inputs, config, InputMutation(set_fields={field: value}), base_result=base_result
    ).scenario.total_tax_cents
    nxt = recompute_scenario(
        inputs, config, InputMutation(set_fields={field: value + step}), base_result=base_result
    ).scenario.total_tax_cents
    return Decimal(nxt - here) / Decimal(step)


def test_emr_marginal_equals_delta_tax_over_delta_income() -> None:
    config = _config()
    step = 500_000  # $5,000
    # A point squarely inside the 20% ordinary bracket. Wages 40k → taxable 25k
    # (after 15k std ded), well within 10k-50k. No preferential income, AGI far
    # below the 100k NIIT threshold, so the effective marginal IS the 20% rate.
    field, value = "wages_cents", 4_000_000
    inputs = Form1040Inputs(filing_status="single")
    base_result = calculate_form1040(inputs, config)
    here = recompute_scenario(
        inputs, config, InputMutation(set_fields={field: value}), base_result=base_result
    ).scenario.total_tax_cents
    nxt = recompute_scenario(
        inputs, config, InputMutation(set_fields={field: value + step}), base_result=base_result
    ).scenario.total_tax_cents
    expected = Decimal(nxt - here) / Decimal(step)
    assert _marginal_at(field, value, step, config) == expected
    assert expected == Decimal("0.20")  # pure 20% bracket, no phase-out here


def test_emr_marginal_exceeds_bracket_rate_across_niit_cliff() -> None:
    # The point of the EFFECTIVE marginal: above the $100k NIIT threshold, an
    # extra dollar of interest income is taxed at the ordinary rate PLUS 3.8%
    # NIIT, so the measured marginal exceeds the bare bracket rate. We sweep
    # taxable interest (investment income) so NIIT actually engages.
    config = _config()
    step = 500_000
    field, value = "taxable_interest_cents", 15_000_000  # AGI well above 100k
    eff = _marginal_at(field, value, step, config)
    # 30% top bracket + 3.8% NIIT on the marginal investment dollars = 0.338.
    assert eff > Decimal("0.30")
    assert eff == Decimal("0.338")


def test_deductible_contribution_delta_lowers_tax() -> None:
    # A $10k deductible contribution (adjustments +10k) at a 20% margin: real
    # recompute, not amount × rate. Base wages 50k → taxable 35k → tax 6,000;
    # after the deduction taxable 25k → tax 4,000 → −2,000.
    config = _config()
    base_inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    rec = recompute_scenario(
        base_inputs, config, InputMutation(delta_fields={"adjustments_cents": 1_000_000})
    )
    assert rec.tax_delta_cents < 0
    assert rec.tax_delta_cents == -200_000
    assert rec.agi_delta_cents == -1_000_000


def test_roth_trace_monotonic_in_tax_cost() -> None:
    # Replicates services.scenarios.optimize_roth's trace: sweep the conversion
    # from $0 upward, recompute the incremental tax cost at each step, and assert
    # cost is monotonic non-decreasing (more conversion never costs less tax) and
    # each step's marginal is non-negative.
    config = _config()
    inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    base_result = calculate_form1040(inputs, config)
    target = 4_000_000  # convert up to $40k of IRA into the picture
    step = target // 10
    amounts = list(range(0, target + 1, step))
    if amounts[-1] != target:
        amounts.append(target)

    prev_cost = 0
    prev_amount = 0
    costs: list[int] = []
    for amount in amounts:
        if amount == 0:
            cost = 0
        else:
            cost = recompute_scenario(
                inputs,
                config,
                InputMutation(delta_fields={"ira_taxable_cents": amount}),
                base_result=base_result,
            ).tax_delta_cents
        increment = amount - prev_amount
        if increment > 0:
            marginal = Decimal(cost - prev_cost) / Decimal(increment)
            assert marginal >= 0  # each incremental dollar of conversion costs ≥ 0 tax
        costs.append(cost)
        prev_cost, prev_amount = cost, amount

    assert costs == sorted(costs)  # monotonic non-decreasing
    assert costs[-1] > costs[0]  # converting $40k does cost real tax
