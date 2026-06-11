"""Golden tests for the deterministic opportunity scan.

Same round config as the multi-year tests. A $50,000 wage earner: a $10,000
pre-tax deferral / deductible contribution saves the real 20% marginal = $2,000;
charitable bunching below the standard deduction saves $0 (dropped); tax-loss
harvesting is inapplicable with no gains.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import AuxiliaryConfig, Form1040Inputs, RateBracket, TaxConfig
from app.engines.opportunity import find_opportunities


def _config() -> TaxConfig:
    return TaxConfig(
        tax_year=2025,
        filing_status="single",
        standard_deduction_cents=1_500_000,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.10")),
            RateBracket(lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.20")),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.30")),
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


def test_wage_earner_opportunities_real_savings() -> None:
    inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    opps = find_opportunities(inputs, _config(), illustrative_amount_cents=1_000_000)
    by_code = {o.code: o for o in opps}

    # Pre-tax deferral, traditional IRA, and HSA each save the real 20% margin.
    for code in ("retirement_deferral_401k", "traditional_ira", "hsa_contribution"):
        assert by_code[code].estimated_tax_savings_cents == 200_000, code
        assert by_code[code].marginal_rate_used == Decimal("0.2000")

    # Charitable bunching $10k stays under the $15k standard deduction → no
    # benefit → dropped from the list.
    assert "charitable_bunching" not in by_code
    # No realized gains → tax-loss harvesting not applicable.
    assert "tax_loss_harvesting" not in by_code

    # Sorted by savings descending.
    savings = [o.estimated_tax_savings_cents for o in opps]
    assert savings == sorted(savings, reverse=True)


def test_charitable_bunching_above_standard_saves() -> None:
    # A $20,000 bunch exceeds the $15,000 standard by $5,000 at the 20% margin
    # → $1,000 real savings.
    inputs = Form1040Inputs(filing_status="single", wages_cents=5_000_000)
    opps = find_opportunities(inputs, _config(), illustrative_amount_cents=2_000_000)
    by_code = {o.code: o for o in opps}
    assert by_code["charitable_bunching"].estimated_tax_savings_cents == 100_000


def test_tax_loss_harvesting_offsets_gains() -> None:
    # $30,000 LTCG taxed at 15% preferential; harvesting $10,000 of losses saves
    # 15% × 10,000 = $1,500.
    inputs = Form1040Inputs(
        filing_status="single", wages_cents=5_000_000, capital_gain_loss_cents=3_000_000
    )
    opps = find_opportunities(inputs, _config(), illustrative_amount_cents=1_000_000)
    by_code = {o.code: o for o in opps}
    assert by_code["tax_loss_harvesting"].estimated_tax_savings_cents == 150_000
