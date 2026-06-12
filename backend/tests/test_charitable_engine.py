"""Charitable engine golden checks — bunching (DAF) and QCD."""

from __future__ import annotations

from decimal import Decimal

from app.engines.charitable import (
    BunchingInput,
    QCDInput,
    bunching_benefit,
    qcd_benefit,
    ty2025_charitable_config,
    ty2026_charitable_config,
)


def test_bunching_clears_standard_deduction() -> None:
    # $15k/yr giving + $10k recurring SALT, MFJ std $32,200, 24% marginal, 3yr.
    # Annual giving never clears the std deduction → $0 benefit. Bunching 3 years
    # ($45k gifts + $10k SALT = $55k) clears it: $22,800 extra deduction.
    out = bunching_benefit(
        BunchingInput(
            annual_giving_cents=1_500_000,
            years_bunched=3,
            standard_deduction_cents=3_220_000,
            other_itemized_cents=1_000_000,
            marginal_rate=Decimal("0.24"),
        ),
        ty2025_charitable_config(),
    )
    assert out.extra_deduction_cents == 2_280_000
    assert out.tax_savings_cents == 547_200  # 22,800 × 24%
    assert out.bunch_year_itemizes is True
    assert out.annual_itemizes is False


def test_bunching_applies_2026_agi_floor() -> None:
    # 2026 adds a 0.5%-of-AGI charitable floor. AGI $400k → $2,000 floor shaves
    # the deductible gift each window.
    out = bunching_benefit(
        BunchingInput(
            annual_giving_cents=1_500_000,
            years_bunched=3,
            standard_deduction_cents=3_220_000,
            other_itemized_cents=1_000_000,
            marginal_rate=Decimal("0.24"),
            agi_cents=40_000_000,
        ),
        ty2026_charitable_config(),
    )
    assert out.charitable_floor_cents == 200_000  # 0.5% × $400k
    # bunch itemized = $10k SALT + ($45k − $2k floor) = $53k; over $32.2k std = $20,800.
    assert out.extra_deduction_cents == 2_080_000
    assert out.tax_savings_cents == 499_200


def test_qcd_benefit_for_standard_deduction_donor() -> None:
    out = qcd_benefit(
        QCDInput(
            intended_giving_cents=2_000_000,
            ira_distribution_available_cents=5_000_000,
            marginal_rate=Decimal("0.22"),
            takes_standard_deduction=True,
        ),
        ty2026_charitable_config(),
    )
    assert out.qcd_amount_cents == 2_000_000
    assert out.agi_reduction_cents == 2_000_000
    assert out.tax_savings_cents == 440_000  # $20k × 22%
    assert out.capped_by_limit is False


def test_qcd_capped_at_annual_limit_and_zero_for_itemizer() -> None:
    capped = qcd_benefit(
        QCDInput(
            intended_giving_cents=15_000_000,  # $150k intended
            ira_distribution_available_cents=20_000_000,
            marginal_rate=Decimal("0.22"),
            takes_standard_deduction=True,
        ),
        ty2026_charitable_config(),
    )
    assert capped.qcd_amount_cents == 11_100_000  # $111k 2026 limit
    assert capped.capped_by_limit is True

    itemizer = qcd_benefit(
        QCDInput(
            intended_giving_cents=2_000_000,
            ira_distribution_available_cents=5_000_000,
            marginal_rate=Decimal("0.22"),
            takes_standard_deduction=False,
        ),
        ty2026_charitable_config(),
    )
    assert itemizer.tax_savings_cents == 0  # itemizer already deducts the gift
    assert "AGI reduction" in itemizer.note
