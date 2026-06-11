"""Golden tests for the §86 Social Security taxability engine.

The three confirmed regimes (independently re-derived against the canonical
IRS Social Security Benefits Worksheet): none, 50% tier, 85% tier (capped).
Amounts in dollars ×100 = cents.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.ss_taxability import SSInput, calculate_taxable_ss, ty2025_ss_config

CFG = ty2025_ss_config()


def test_below_first_base_none_taxable() -> None:
    # single: benefits 20,000, other 12,000 → provisional 12,000 + 10,000 = 22,000
    # 22,000 <= 25,000 first base → none taxable.
    out = calculate_taxable_ss(
        SSInput(filing_status="single", social_security_benefits_cents=2_000_000,
                other_income_cents=1_200_000),
        CFG,
    )
    assert out.provisional_income_cents == 2_200_000
    assert out.taxable_social_security_cents == 0
    assert out.tier == "none"


def test_fifty_percent_tier() -> None:
    # single: benefits 20,000, other 20,000 → provisional 30,000 (between 25k–34k)
    # taxable = min(½·20,000, ½·(30,000−25,000)) = min(10,000, 2,500) = 2,500.
    out = calculate_taxable_ss(
        SSInput(filing_status="single", social_security_benefits_cents=2_000_000,
                other_income_cents=2_000_000),
        CFG,
    )
    assert out.provisional_income_cents == 3_000_000
    assert out.taxable_social_security_cents == 250_000
    assert out.tier == "fifty"


def test_eighty_five_percent_tier_capped_mfj() -> None:
    # mfj: benefits 40,000, other 80,000 → provisional 80,000 + 20,000 = 100,000
    # over base2 = 56,000; 0.85·56,000 = 47,600; gap = min(20,000, ½·12,000=6,000)=6,000
    # → 53,600, capped at 0.85·40,000 = 34,000.
    out = calculate_taxable_ss(
        SSInput(filing_status="mfj", social_security_benefits_cents=4_000_000,
                other_income_cents=8_000_000),
        CFG,
    )
    assert out.provisional_income_cents == 10_000_000
    assert out.taxable_social_security_cents == 3_400_000  # 85% cap
    assert out.tier == "eighty_five"


def test_eighty_five_percent_tier_not_capped() -> None:
    # single: benefits 30,000, other 40,000 → provisional 55,000
    # over base2 = 21,000; 0.85·21,000 = 17,850; gap = min(15,000, 4,500)=4,500
    # → 22,350 < 0.85·30,000=25,500 → taxable 22,350.
    out = calculate_taxable_ss(
        SSInput(filing_status="single", social_security_benefits_cents=3_000_000,
                other_income_cents=4_000_000),
        CFG,
    )
    assert out.provisional_income_cents == 5_500_000
    assert out.taxable_social_security_cents == 2_235_000
    assert out.tier == "eighty_five"


def test_mfs_lived_with_spouse_85_from_first_dollar() -> None:
    # bases are 0/0 → 85% tier immediately. benefits 10,000, other 5,000
    # provisional 5,000 + 5,000 = 10,000; over base2 = 10,000; 0.85·10,000 = 8,500
    # capped at 0.85·10,000 = 8,500.
    out = calculate_taxable_ss(
        SSInput(filing_status="mfs_lived_with_spouse",
                social_security_benefits_cents=1_000_000, other_income_cents=500_000),
        CFG,
    )
    assert out.taxable_social_security_cents == 850_000
    assert out.tier == "eighty_five"


def test_no_benefits() -> None:
    out = calculate_taxable_ss(
        SSInput(filing_status="single", other_income_cents=5_000_000), CFG
    )
    assert out.taxable_social_security_cents == 0
    assert out.taxable_percentage == Decimal("0")


def test_config_constants_guard() -> None:
    # Lock the statutory 2025 base amounts so they cannot silently drift.
    assert CFG.bases["single"].base1_cents == 2_500_000
    assert CFG.bases["single"].base2_cents == 3_400_000
    assert CFG.bases["mfj"].base1_cents == 3_200_000
    assert CFG.bases["mfj"].base2_cents == 4_400_000
    assert CFG.bases["mfs_lived_with_spouse"].base1_cents == 0
