"""Golden tests for the C-corp engine (1120 + §1202 QSBS + AET, TY2025).

Vectors adversarially verified (the reviewer corrected two AET-credit figures —
those corrected values are used here). Dollars ×100 = cents.
"""

from __future__ import annotations

from decimal import Decimal

from app.engine_configs import ty2025_corporate_config
from app.engines.corporate import (
    AETInput,
    CorporateTaxInput,
    QSBSInput,
    calculate_aet,
    calculate_corporate_tax,
    calculate_qsbs,
)

CFG = ty2025_corporate_config()


# ----------------------------- corporate tax -----------------------------


def test_corp_tax_flat_21() -> None:
    out = calculate_corporate_tax(CorporateTaxInput(pre_nol_taxable_income_cents=30_000_000), CFG)
    assert out.corporate_tax_cents == 6_300_000  # 21% of $300k
    assert out.nol_deduction_cents == 0


def test_corp_tax_nol_80pct_limit() -> None:
    # Pre-NOL $200k, $500k NOL available → deduct 80%·200k = $160k → taxable $40k.
    out = calculate_corporate_tax(
        CorporateTaxInput(pre_nol_taxable_income_cents=20_000_000, nol_available_cents=50_000_000),
        CFG,
    )
    assert out.nol_deduction_cents == 16_000_000
    assert out.corporate_taxable_income_cents == 4_000_000
    assert out.corporate_tax_cents == 840_000  # 21% of $40k
    assert out.nol_carryforward_remaining_cents == 34_000_000


def test_corp_tax_high() -> None:
    out = calculate_corporate_tax(CorporateTaxInput(pre_nol_taxable_income_cents=100_000_000), CFG)
    assert out.corporate_tax_cents == 21_000_000  # 21% of $1M


# ------------------------------- §1202 QSBS ------------------------------


def test_qsbs_new_5yr_100pct() -> None:
    # New stock, 5yr, gain $18M, basis $2M → cap max($15M, 10·$2M=$20M)=$20M;
    # 100% → excluded $18M, taxable 0.
    out = calculate_qsbs(
        QSBSInput(eligible_gain_cents=1_800_000_000, basis_cents=200_000_000,
                  holding_years=5, acquired_after_obbba=True),
        CFG,
    )
    assert out.exclusion_pct == Decimal("1.00")
    assert out.per_issuer_cap_cents == 2_000_000_000  # 10× basis
    assert out.excluded_gain_cents == 1_800_000_000
    assert out.taxable_gain_cents == 0


def test_qsbs_new_4yr_75pct() -> None:
    # New stock, 4yr, gain $8M, basis $1M → cap max($15M, $10M)=$15M; 75% →
    # excluded $6M, taxable $2M, tax 28%·$2M = $560k. AMT preference modeled 0.
    out = calculate_qsbs(
        QSBSInput(eligible_gain_cents=800_000_000, basis_cents=100_000_000,
                  holding_years=4, acquired_after_obbba=True),
        CFG,
    )
    assert out.exclusion_pct == Decimal("0.75")
    assert out.per_issuer_cap_cents == 1_500_000_000
    assert out.excluded_gain_cents == 600_000_000
    assert out.taxable_gain_cents == 200_000_000
    assert out.tax_on_taxable_gain_cents == 56_000_000
    assert out.amt_preference_cents == 0


def test_qsbs_old_5yr_capped_at_10x_basis() -> None:
    # Old stock, 5yr, gain $12.5M, basis $500k → cap max($10M, 10·$500k=$5M)=$10M;
    # 100% but excludable capped at $10M → excluded $10M, taxable $2.5M, tax $700k.
    out = calculate_qsbs(
        QSBSInput(eligible_gain_cents=1_250_000_000, basis_cents=50_000_000,
                  holding_years=5, acquired_after_obbba=False),
        CFG,
    )
    assert out.per_issuer_cap_cents == 1_000_000_000  # $10M dollar cap beats 10×$500k
    assert out.excluded_gain_cents == 1_000_000_000
    assert out.taxable_gain_cents == 250_000_000
    assert out.tax_on_taxable_gain_cents == 70_000_000


# --------------------------------- AET -----------------------------------


def test_aet_psc_credit_reduced_by_prior_ep() -> None:
    # PSC, accumulated taxable income $500k, prior E&P $50k → credit
    # max($150k − $50k, 0) = $100k; base $400k; AET 20% = $80k (reviewer-corrected).
    out = calculate_aet(
        AETInput(accumulated_taxable_income_cents=50_000_000,
                 prior_year_accumulated_ep_cents=5_000_000, is_psc=True),
        CFG,
    )
    assert out.credit_cents == 10_000_000
    assert out.accumulated_taxable_income_over_credit_cents == 40_000_000
    assert out.estimated_aet_cents == 8_000_000
    assert out.exposed is True


def test_config_guard() -> None:
    assert CFG.corporate_rate == Decimal("0.21")
    assert CFG.nol_limit_pct == Decimal("0.80")
    assert CFG.qsbs_cap_new_cents == 1_500_000_000
    assert CFG.aet_credit_cents == 25_000_000
