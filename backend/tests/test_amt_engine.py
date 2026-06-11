"""Golden tests for the AMT engine (Form 6251, TY2025).

Three adversarially-verified vectors: 28% ordinary tier (ISO), MFJ exemption
phaseout (SALT add-back), and MFJ with preferential cap gains retained.
Amounts in dollars ×100 = cents.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.amt import AMTInput, calculate_amt, ty2025_amt_config
from app.engines.form1040 import RateBracket

CFG = ty2025_amt_config()

# 2025 MFJ LTCG brackets: 0% to $96,700, 15% to $600,050, then 20%.
MFJ_LTCG = [
    RateBracket(lower_bound_cents=0, upper_bound_cents=9_670_000, rate=Decimal("0")),
    RateBracket(lower_bound_cents=9_670_000, upper_bound_cents=60_005_000, rate=Decimal("0.15")),
    RateBracket(lower_bound_cents=60_005_000, upper_bound_cents=None, rate=Decimal("0.20")),
]


def test_a_single_iso_28pct_tier() -> None:
    # AMTI = 250,000 + 15,000 std add-back + 135,000 ISO = 400,000.
    # exemption 88,100 (below phaseout); excess 311,900 > 239,100 →
    # 0.28·311,900 − 4,782 = 82,550 TMT; AMT = 82,550 − 60,000 = 22,550.
    out = calculate_amt(
        AMTInput(filing_status="single", regular_taxable_income_cents=25_000_000,
                 regular_tax_for_amt_cents=6_000_000, used_standard_deduction=True,
                 standard_deduction_cents=1_500_000, other_preferences_cents=13_500_000),
        CFG,
    )
    assert out.amti_cents == 40_000_000
    assert out.exemption_cents == 8_810_000
    assert out.taxable_excess_cents == 31_190_000
    assert out.tentative_minimum_tax_cents == 8_255_000
    assert out.amt_cents == 2_255_000


def test_b_mfj_exemption_phaseout_salt() -> None:
    # AMTI = 1,360,000 + 40,000 SALT = 1,400,000. excess over 1,252,700 = 147,300;
    # 25% → 36,825; exemption 137,000 − 36,825 = 100,175. excess 1,299,825 →
    # 0.28·1,299,825 − 4,782 = 359,169 TMT; AMT = 359,169 − 330,000 = 29,169.
    out = calculate_amt(
        AMTInput(filing_status="mfj", regular_taxable_income_cents=136_000_000,
                 regular_tax_for_amt_cents=33_000_000, salt_addback_cents=4_000_000),
        CFG,
    )
    assert out.amti_cents == 140_000_000
    assert out.exemption_cents == 10_017_500
    assert out.taxable_excess_cents == 129_982_500
    assert out.tentative_minimum_tax_cents == 35_916_900
    assert out.amt_cents == 2_916_900


def test_c_mfj_preferential_cap_gains_retained() -> None:
    # AMTI 500,000 (no add-backs); exemption 137,000; excess 363,000.
    # ordinary 363,000 − 200,000 = 163,000 ≤ 239,100 → 0.26·163,000 = 42,380.
    # preferential 200,000 stacks at 15% (regular TI in the 15% band) = 30,000.
    # TMT 72,380; AMT = 72,380 − 70,000 = 2,380.
    out = calculate_amt(
        AMTInput(filing_status="mfj", regular_taxable_income_cents=50_000_000,
                 regular_tax_for_amt_cents=7_000_000,
                 amt_preferential_income_cents=20_000_000, ltcg_brackets=MFJ_LTCG),
        CFG,
    )
    assert out.amti_cents == 50_000_000
    assert out.exemption_cents == 13_700_000
    assert out.taxable_excess_cents == 36_300_000
    assert out.tentative_minimum_tax_cents == 7_238_000
    assert out.amt_cents == 238_000


def test_no_amt_when_regular_tax_high() -> None:
    out = calculate_amt(
        AMTInput(filing_status="single", regular_taxable_income_cents=10_000_000,
                 regular_tax_for_amt_cents=9_000_000),
        CFG,
    )
    assert out.amt_cents == 0
    assert out.amt_applies is False


def test_config_constants_guard() -> None:
    assert CFG.params["single"].exemption_cents == 8_810_000
    assert CFG.params["mfj"].exemption_cents == 13_700_000
    assert CFG.params["mfs"].exemption_cents == 6_850_000
    assert CFG.params["mfj"].phaseout_threshold_cents == 125_270_000
    assert CFG.params["single"].rate_breakpoint_cents == 23_910_000
    assert CFG.params["single"].breakpoint_subtraction_cents == 478_200
