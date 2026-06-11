"""Golden tests for the multi-year projection + scenario recompute engine.

A deliberately round config makes every expected value hand-computable:
  ordinary: 0-10,000@10% | 10,000-50,000@20% | 50,000+@30%
  std deduction 15,000; LTCG 0-40,000@0% then 15%; NIIT/AddlMed @100,000.
(All amounts in dollars here ×100 = cents.)
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import AuxiliaryConfig, Form1040Inputs, RateBracket, TaxConfig
from app.engines.multiyear import (
    InputMutation,
    MultiYearInput,
    Scenario,
    index_config,
    project_multi_year,
    recompute_scenario,
)


def _config() -> TaxConfig:
    return TaxConfig(
        tax_year=2025,
        filing_status="single",
        standard_deduction_cents=1_500_000,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.1000")),
            RateBracket(
                lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.2000")
            ),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.3000")),
        ],
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=[
                RateBracket(lower_bound_cents=0, upper_bound_cents=4_000_000, rate=Decimal("0")),
                RateBracket(lower_bound_cents=4_000_000, upper_bound_cents=None, rate=Decimal("0.15")),
            ],
            niit_threshold_cents=10_000_000,
            niit_rate=Decimal("0.0380"),
            additional_medicare_threshold_cents=10_000_000,
            additional_medicare_rate=Decimal("0.0090"),
            capital_loss_limit_cents=300_000,
        ),
    )


def test_recompute_scenario_real_delta() -> None:
    # Base: $50,000 wages, std ded $15,000 → taxable $35,000.
    #   ordinary tax = 10%*10,000 + 20%*25,000 = 1,000 + 5,000 = 6,000.
    base_inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    # Strategy: a $10,000 deductible contribution (adjustments +10,000).
    #   AGI 40,000 → taxable 25,000 → tax = 1,000 + 20%*15,000 = 1,000 + 3,000 = 4,000.
    #   Real savings = 4,000 - 6,000 = -2,000 (the $10k deduction at the 20% margin).
    out = recompute_scenario(
        base_inputs,
        _config(),
        InputMutation(delta_fields={"adjustments_cents": 1_000_000}),
    )
    assert out.base.total_tax_cents == 600_000
    assert out.scenario.total_tax_cents == 400_000
    assert out.tax_delta_cents == -200_000
    assert out.agi_delta_cents == -1_000_000
    assert out.marginal_rate_scenario == Decimal("0.2000")


def test_recompute_rejects_unknown_field() -> None:
    try:
        InputMutation(delta_fields={"not_a_field": 1}).apply(
            Form1040Inputs(filing_status="single")
        )
    except KeyError as exc:
        assert "not_a_field" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError on unknown field")


def test_index_config_indexes_only_what_the_law_indexes() -> None:
    # 2% one year: std ded 15,000→15,300; bracket bound 10,000→10,200,
    # 50,000→51,000. NIIT/AddlMedicare thresholds are statutorily fixed.
    indexed = index_config(_config(), years_forward=1, annual_rate=Decimal("0.02"))
    assert indexed.tax_year == 2026
    assert indexed.standard_deduction_cents == 1_530_000
    assert indexed.ordinary_brackets[0].upper_bound_cents == 1_020_000
    assert indexed.ordinary_brackets[1].upper_bound_cents == 5_100_000
    # fixed thresholds unchanged
    assert indexed.auxiliary.niit_threshold_cents == 10_000_000
    assert indexed.auxiliary.additional_medicare_threshold_cents == 10_000_000
    # LTCG breakpoint IS indexed: 40,000 → 40,800
    assert indexed.auxiliary.ltcg_brackets[0].upper_bound_cents == 4_080_000


def test_project_multi_year_flat_baseline() -> None:
    payload = MultiYearInput(
        base_year=2025,
        base_inputs=Form1040Inputs(filing_status="single", wages_cents=5_000_000),
        base_config=_config(),
        horizon_years=2,
        inflation_rate=Decimal("0"),
        income_growth_rate=Decimal("0"),
    )
    out = project_multi_year(payload)
    assert [y.total_tax_cents for y in out.baseline.years] == [600_000, 600_000]
    assert out.baseline.cumulative_tax_cents == 1_200_000
    assert out.baseline.years[0].config_source == "seeded"
    assert out.baseline.years[1].config_source == "indexed"


def test_project_multi_year_scenario_savings() -> None:
    payload = MultiYearInput(
        base_year=2025,
        base_inputs=Form1040Inputs(filing_status="single", wages_cents=5_000_000),
        base_config=_config(),
        horizon_years=2,
        inflation_rate=Decimal("0"),
        income_growth_rate=Decimal("0"),
        scenarios=[
            Scenario(
                name="annual $10k deductible contribution",
                mutations_by_offset={0: InputMutation(delta_fields={"adjustments_cents": 1_000_000})},
            )
        ],
    )
    out = project_multi_year(payload)
    sc = out.scenarios[0]
    # Mutation persists both years: 400,000 each → cumulative 800,000.
    assert [y.total_tax_cents for y in sc.years] == [400_000, 400_000]
    assert sc.cumulative_tax_cents == 800_000
    assert sc.cumulative_tax_delta_vs_baseline_cents == -400_000
