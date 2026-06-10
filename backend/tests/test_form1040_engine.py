from __future__ import annotations

from decimal import Decimal

import pytest

from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    RateBracket,
    TaxConfig,
    calculate_form1040,
    validate_brackets,
)


def _config(*, top_rate: str = "0.3000") -> TaxConfig:
    return TaxConfig(
        tax_year=2099,
        filing_status="single",
        standard_deduction_cents=1_500_000,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.1000")),
            RateBracket(
                lower_bound_cents=1_000_000,
                upper_bound_cents=5_000_000,
                rate=Decimal("0.2000"),
            ),
            RateBracket(
                lower_bound_cents=5_000_000,
                upper_bound_cents=None,
                rate=Decimal(top_rate),
            ),
        ],
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=[
                RateBracket(
                    lower_bound_cents=0,
                    upper_bound_cents=4_000_000,
                    rate=Decimal("0.0000"),
                ),
                RateBracket(
                    lower_bound_cents=4_000_000,
                    upper_bound_cents=None,
                    rate=Decimal("0.1500"),
                ),
            ],
            niit_threshold_cents=10_000_000,
            niit_rate=Decimal("0.0380"),
            additional_medicare_threshold_cents=10_000_000,
            additional_medicare_rate=Decimal("0.0090"),
            capital_loss_limit_cents=300_000,
        ),
    )


@pytest.mark.parametrize(
    ("name", "inputs", "expected"),
    [
        (
            "plain wages",
            Form1040Inputs(filing_status="single", wages_cents=5_000_000),
            {
                "total_income_cents": 5_000_000,
                "agi_cents": 5_000_000,
                "taxable_income_cents": 3_500_000,
                "ordinary_tax_cents": 600_000,
                "total_tax_cents": 600_000,
                "marginal_rate": Decimal("0.2000"),
            },
        ),
        (
            "bracket boundary",
            Form1040Inputs(filing_status="single", wages_cents=2_500_000),
            {
                "taxable_income_cents": 1_000_000,
                "ordinary_tax_cents": 100_000,
                "total_tax_cents": 100_000,
                "marginal_rate": Decimal("0.1000"),
            },
        ),
        (
            "itemized crossover",
            Form1040Inputs(
                filing_status="single",
                wages_cents=8_000_000,
                itemized_deduction_cents=2_000_000,
            ),
            {
                "deduction_cents": 2_000_000,
                "taxable_income_cents": 6_000_000,
                "ordinary_tax_cents": 1_200_000,
                "total_tax_cents": 1_200_000,
                "marginal_rate": Decimal("0.3000"),
            },
        ),
        (
            "capital loss limited",
            Form1040Inputs(
                filing_status="single",
                wages_cents=2_000_000,
                capital_gain_loss_cents=-1_000_000,
            ),
            {
                "total_income_cents": 1_700_000,
                "taxable_income_cents": 200_000,
                "ordinary_tax_cents": 20_000,
                "total_tax_cents": 20_000,
            },
        ),
        (
            "qualified dividends in zero band",
            Form1040Inputs(
                filing_status="single",
                wages_cents=3_000_000,
                ordinary_dividends_cents=2_000_000,
                qualified_dividends_cents=2_000_000,
            ),
            {
                "taxable_income_cents": 3_500_000,
                "ordinary_tax_cents": 200_000,
                "preferential_tax_cents": 0,
                "total_tax_cents": 200_000,
            },
        ),
        (
            "preferential income stacked into paid band",
            Form1040Inputs(
                filing_status="single",
                wages_cents=7_000_000,
                ordinary_dividends_cents=3_000_000,
                qualified_dividends_cents=3_000_000,
            ),
            {
                "taxable_income_cents": 8_500_000,
                "ordinary_tax_cents": 1_050_000,
                "preferential_tax_cents": 450_000,
                "total_tax_cents": 1_500_000,
            },
        ),
        (
            "niit",
            Form1040Inputs(
                filing_status="single",
                wages_cents=10_000_000,
                taxable_interest_cents=2_000_000,
                capital_gain_loss_cents=3_000_000,
            ),
            {
                "taxable_income_cents": 13_500_000,
                "ordinary_tax_cents": 2_550_000,
                "preferential_tax_cents": 450_000,
                "niit_cents": 190_000,
                "total_tax_cents": 3_190_000,
            },
        ),
        (
            "additional medicare",
            Form1040Inputs(filing_status="single", wages_cents=15_000_000),
            {
                "taxable_income_cents": 13_500_000,
                "ordinary_tax_cents": 3_450_000,
                "additional_medicare_cents": 45_000,
                "total_tax_cents": 3_495_000,
            },
        ),
        (
            "qbi deduction",
            Form1040Inputs(
                filing_status="single",
                wages_cents=10_000_000,
                qbi_deduction_cents=1_000_000,
            ),
            {
                "qbi_deduction_cents": 1_000_000,
                "taxable_income_cents": 7_500_000,
                "ordinary_tax_cents": 1_650_000,
                "total_tax_cents": 1_650_000,
            },
        ),
    ],
)
def test_form1040_golden_cases(name: str, inputs: Form1040Inputs, expected: dict) -> None:
    result = calculate_form1040(inputs, _config())
    for key, value in expected.items():
        assert getattr(result, key) == value, name
    assert result.effective_rate == (
        Decimal(result.total_tax_cents) / Decimal(result.total_income_cents)
    )


def test_reconciliation_flags_out_of_tolerance() -> None:
    result = calculate_form1040(
        Form1040Inputs(
            filing_status="single",
            wages_cents=5_000_000,
            reported_agi_cents=5_000_000,
            reported_taxable_income_cents=3_000_000,
            reported_total_tax_cents=600_000,
        ),
        _config(),
    )
    flags = {item.field: item.within_tolerance for item in result.reconciliation}
    assert flags == {"agi": True, "taxable_income": False, "total_tax": True}


def test_engine_reads_rates_from_injected_config() -> None:
    inputs = Form1040Inputs(filing_status="single", wages_cents=10_000_000)
    base = calculate_form1040(inputs, _config(top_rate="0.3000"))
    changed = calculate_form1040(inputs, _config(top_rate="0.4000"))
    assert changed.total_tax_cents - base.total_tax_cents == 350_000


def test_tax_is_monotonic_and_effective_rate_is_bounded() -> None:
    cfg = _config()
    previous = 0
    top_rate = cfg.ordinary_brackets[-1].rate
    for wages in range(0, 20_000_000, 250_000):
        result = calculate_form1040(Form1040Inputs(filing_status="single", wages_cents=wages), cfg)
        assert result.total_tax_cents >= previous
        assert Decimal("0") <= result.effective_rate <= top_rate
        previous = result.total_tax_cents


def test_rounding_stability_to_cent() -> None:
    cfg = _config(top_rate="0.3333")
    result = calculate_form1040(Form1040Inputs(filing_status="single", wages_cents=5_000_001), cfg)
    assert isinstance(result.total_tax_cents, int)
    assert result.total_tax_cents == 600_000


def test_bracket_validation_rejects_bad_sets() -> None:
    invalid = validate_brackets(
        [
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000, rate=Decimal("0.2000")),
            RateBracket(lower_bound_cents=2_000, upper_bound_cents=None, rate=Decimal("0.1000")),
        ]
    )
    assert not invalid.valid
    assert "brackets must be contiguous and non-overlapping" in invalid.errors
    assert "rates must be monotonic" in invalid.errors
