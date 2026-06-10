from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.engines.quarterly import QuarterlyConfig, QuarterlyInput, compute_quarterly


def _config() -> QuarterlyConfig:
    return QuarterlyConfig(
        current_year_rate=Decimal("0.9000"),
        prior_year_rate=Decimal("1.0000"),
        high_agi_prior_year_rate=Decimal("1.1000"),
        high_agi_threshold_cents=15_000_000,
        due_dates=[
            date(2099, 4, 15),
            date(2099, 6, 15),
            date(2099, 9, 15),
            date(2100, 1, 15),
        ],
    )


def test_safe_harbor_uses_90_current_when_lowest() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=1_000_000,
            prior_year_tax_cents=2_000_000,
            prior_year_agi_cents=10_000_000,
            config=_config(),
        )
    )
    assert result.safe_harbor_basis == "90_current"
    assert result.required_annual_payment_cents == 900_000
    assert [q.required_payment_cents for q in result.quarters] == [225_000] * 4


def test_safe_harbor_uses_100_prior_when_lowest() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=2_000_000,
            prior_year_tax_cents=1_000_000,
            prior_year_agi_cents=10_000_000,
            config=_config(),
        )
    )
    assert result.safe_harbor_basis == "100_prior"
    assert result.required_annual_payment_cents == 1_000_000


def test_high_agi_110_boundary_qualifies_only_above_threshold() -> None:
    at_threshold = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=2_000_000,
            prior_year_tax_cents=1_000_000,
            prior_year_agi_cents=15_000_000,
            config=_config(),
        )
    )
    above_threshold = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=2_000_000,
            prior_year_tax_cents=1_000_000,
            prior_year_agi_cents=15_000_001,
            config=_config(),
        )
    )
    assert at_threshold.required_annual_payment_cents == 1_000_000
    assert above_threshold.required_annual_payment_cents == 1_000_000
    assert above_threshold.safe_harbor_basis == "100_prior"


def test_roll_forward_partial_payment() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=1_000_000,
            prior_year_tax_cents=2_000_000,
            prior_year_agi_cents=10_000_000,
            payments_made_cents=[100_000, 0, 0, 0],
            config=_config(),
        )
    )
    assert result.quarters[0].remaining_cents == 125_000
    assert result.quarters[1].unpaid_rollforward_cents == 125_000
    assert result.quarters[1].remaining_cents == 350_000


def test_withholding_credited_evenly() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=1_000_000,
            prior_year_tax_cents=2_000_000,
            prior_year_agi_cents=10_000_000,
            annual_withholding_cents=400_000,
            config=_config(),
        )
    )
    assert [q.withholding_credit_cents for q in result.quarters] == [100_000] * 4
    assert result.quarters[0].required_payment_cents == 125_000


def test_annualized_method_is_uneven() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=1_000_000,
            prior_year_tax_cents=2_000_000,
            prior_year_agi_cents=10_000_000,
            method="annualized",
            period_income_cents=[100_000, 100_000, 100_000, 9_700_000],
            config=_config(),
        )
    )
    assert result.quarters[0].required_payment_cents < result.quarters[3].required_payment_cents


def test_total_required_never_exceeds_annual_target() -> None:
    result = compute_quarterly(
        QuarterlyInput(
            projected_current_year_tax_cents=1_000_000,
            prior_year_tax_cents=2_000_000,
            prior_year_agi_cents=10_000_000,
            payments_made_cents=[0, 0, 0, 0],
            config=_config(),
        )
    )
    assert (
        sum(q.required_payment_cents for q in result.quarters)
        <= result.required_annual_payment_cents
    )
