"""Golden tests for Form 2210 underpayment penalty (TY2025, regular method).

Three adversarially-verified vectors: de minimis stop, prior_100 safe harbor
(372), prior_110 high-income safe harbor (1304). Dollars ×100 = cents.
"""

from __future__ import annotations

from app.engines.form2210 import Form2210Input, calculate_form2210, ty2025_form2210_config

CFG = ty2025_form2210_config()


def test_v1_de_minimis_no_penalty() -> None:
    # tax 8,000, withholding 7,200 → balance 800 < 1,000 → no penalty.
    out = calculate_form2210(
        Form2210Input(filing_status="single", current_year_total_tax_cents=800_000,
                      prior_year_total_tax_cents=600_000, prior_year_agi_cents=7_000_000,
                      annual_withholding_cents=720_000),
        CFG,
    )
    assert out.de_minimis_applied is True
    assert out.penalty_owed is False
    assert out.total_penalty_cents == 0


def test_v2_prior_100_safe_harbor() -> None:
    # tax 30,000 wh 12,000; cy 27,000; AGI 120k≤150k → 100% prior 20,000 binds.
    # installments 5,000; wh/4 3,000; underpayment 2,000 each.
    # penalty = 2,000×7%×[365,304,212,90]/365 → 372.
    out = calculate_form2210(
        Form2210Input(filing_status="single", current_year_total_tax_cents=3_000_000,
                      prior_year_total_tax_cents=2_000_000, prior_year_agi_cents=12_000_000,
                      annual_withholding_cents=1_200_000),
        CFG,
    )
    assert out.required_annual_payment_cents == 2_000_000
    assert out.safe_harbor_basis == "prior_100"
    assert [i.underpayment_cents for i in out.installments] == [200_000] * 4
    assert out.total_penalty_cents == 37_200  # $372


def test_v3_prior_110_high_income() -> None:
    # MFJ tax 100,000 wh 60,000; cy 90,000; AGI 300k>150k → 110%×80,000=88,000 binds.
    # installments 22,000; wh/4 15,000; underpayment 7,000 each → penalty 1,304.
    out = calculate_form2210(
        Form2210Input(filing_status="mfj", current_year_total_tax_cents=10_000_000,
                      prior_year_total_tax_cents=8_000_000, prior_year_agi_cents=30_000_000,
                      annual_withholding_cents=6_000_000),
        CFG,
    )
    assert out.required_annual_payment_cents == 8_800_000
    assert out.safe_harbor_basis == "prior_110"
    assert [i.underpayment_cents for i in out.installments] == [700_000] * 4
    assert out.total_penalty_cents == 130_400  # $1,304


def test_config_constants_guard() -> None:
    assert CFG.underpayment_rate == __import__("decimal").Decimal("0.07")
    assert CFG.de_minimis_cents == 100_000
    assert CFG.high_agi_threshold_cents == 15_000_000
    assert CFG.days_to_deadline == [365, 304, 212, 90]
