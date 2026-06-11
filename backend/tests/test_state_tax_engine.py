"""Tests for the config-driven state tax engine (synthetic states → the engine
logic is verified independent of any year's real constants, which arrive from
the state-config registry)."""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import RateBracket
from app.engines.state_tax import (
    StateSurtax,
    StateTaxConfig,
    StateTaxInput,
    calculate_state_tax,
)


def test_no_income_tax_state() -> None:
    cfg = StateTaxConfig(state="TX", has_income_tax=False)
    out = calculate_state_tax(
        StateTaxInput(filing_status="single", federal_agi_cents=20_000_000), cfg
    )
    assert out.total_state_tax_cents == 0
    assert out.has_income_tax is False


def test_flat_rate_state() -> None:
    # IL-style 4.95% flat, no standard deduction → $100k AGI = $4,950.
    cfg = StateTaxConfig(state="IL", flat_rate=Decimal("0.0495"))
    out = calculate_state_tax(
        StateTaxInput(filing_status="single", federal_agi_cents=10_000_000), cfg
    )
    assert out.state_taxable_income_cents == 10_000_000
    assert out.total_state_tax_cents == 495_000
    assert out.marginal_rate == Decimal("0.0495")


def test_bracketed_state_with_std_deduction() -> None:
    # Brackets 0-10k@1%, 10k-50k@5%, 50k+@9.3%; std ded $5k.
    # AGI $100k → taxable $95k → 1%·10k + 5%·40k + 9.3%·45k = 100+2000+4185 = 6,285.
    cfg = StateTaxConfig(
        state="CA",
        brackets_by_status={"single": [
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.01")),
            RateBracket(lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.05")),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.093")),
        ]},
        standard_deduction_by_status={"single": 500_000},
    )
    out = calculate_state_tax(
        StateTaxInput(filing_status="single", federal_agi_cents=10_000_000), cfg
    )
    assert out.state_taxable_income_cents == 9_500_000
    assert out.base_tax_cents == 628_500
    assert out.marginal_rate == Decimal("0.093")


def test_millionaire_surtax() -> None:
    # 1% surtax over $1M of state taxable income, on top of a 9.3% top bracket.
    cfg = StateTaxConfig(
        state="CA",
        brackets_by_status={"single": [
            RateBracket(lower_bound_cents=0, upper_bound_cents=None, rate=Decimal("0.093")),
        ]},
        standard_deduction_by_status={"single": 0},
        surtaxes=[StateSurtax(name="mental health", threshold_cents=100_000_000,
                              rate=Decimal("0.01"), applies_to="state_taxable_income")],
    )
    out = calculate_state_tax(
        StateTaxInput(filing_status="single", federal_agi_cents=120_000_000), cfg
    )
    # base 9.3%·$1.2M = 111,600; surtax 1%·($1.2M−$1M)=$2,000.
    assert out.base_tax_cents == 11_160_000
    assert out.surtax_cents == 200_000
    assert out.total_state_tax_cents == 11_360_000
    assert out.marginal_rate == Decimal("0.103")  # 9.3% + 1%


def test_social_security_exclusion() -> None:
    # State that doesn't tax SS: $20k taxable SS is subtracted from the base.
    cfg = StateTaxConfig(
        state="PA", flat_rate=Decimal("0.0307"), taxes_social_security=False,
        taxes_retirement_income=False,
    )
    out = calculate_state_tax(
        StateTaxInput(filing_status="single", federal_agi_cents=8_000_000,
                      social_security_taxable_cents=2_000_000, retirement_income_cents=3_000_000),
        cfg,
    )
    # base $80k − $20k SS − $30k retirement = $30k → 3.07% = $921.
    assert out.state_taxable_income_cents == 3_000_000
    assert out.total_state_tax_cents == 92_100
