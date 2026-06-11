"""Tests for the optimization routines."""

from __future__ import annotations

from decimal import Decimal

from app.engine_configs import ty2025_qbi_config, ty2025_scorp_config
from app.engines.form1040 import AuxiliaryConfig, Form1040Inputs, RateBracket, TaxConfig
from app.engines.irmaa import ty2025_irmaa_config
from app.engines.optimizers import optimize_roth_conversion, optimize_scorp_salary


def _aux() -> AuxiliaryConfig:
    return AuxiliaryConfig(
        ltcg_brackets=[RateBracket(lower_bound_cents=0, upper_bound_cents=None, rate=Decimal("0"))],
        niit_threshold_cents=None, niit_rate=Decimal("0"),
        additional_medicare_threshold_cents=None, additional_medicare_rate=Decimal("0"),
        capital_loss_limit_cents=300_000,
    )


def _config(std: int = 1_500_000) -> TaxConfig:
    return TaxConfig(
        tax_year=2025, filing_status="single", standard_deduction_cents=std,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_000_000, rate=Decimal("0.10")),
            RateBracket(lower_bound_cents=1_000_000, upper_bound_cents=5_000_000, rate=Decimal("0.20")),
            RateBracket(lower_bound_cents=5_000_000, upper_bound_cents=None, rate=Decimal("0.30")),
        ],
        auxiliary=_aux(),
    )


def test_roth_fills_to_bracket_top() -> None:
    # wages $30,000 → taxable $15,000 (std $15k? no: std 1.5M=$15k → taxable 1.5M).
    # Actually wages 3,000,000 − std 1,500,000 = taxable 1,500,000.
    # Fill to top of the 20% bracket (ceiling 5,000,000): headroom 3,500,000.
    # base tax on 1,500,000 = 100,000 + 20%·500,000 = 200,000;
    # tax on 5,000,000 = 100,000 + 20%·4,000,000 = 900,000 → cost 700,000 @ 20%.
    out = optimize_roth_conversion(
        Form1040Inputs(filing_status="single", wages_cents=3_000_000), _config(),
        fill_to_rate=Decimal("0.20"),
    )
    assert out.bracket_ceiling_cents == 5_000_000
    assert out.recommended_conversion_cents == 3_500_000
    assert out.tax_cost_cents == 700_000
    assert out.effective_rate_on_conversion == Decimal("0.20")
    assert out.irmaa_warning is None


def test_roth_irmaa_cliff_warning() -> None:
    # Config with a high 20% ceiling so the conversion crosses an IRMAA tier.
    cfg = TaxConfig(
        tax_year=2025, filing_status="single", standard_deduction_cents=0,
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=10_000_000, rate=Decimal("0.10")),
            RateBracket(lower_bound_cents=10_000_000, upper_bound_cents=20_000_000, rate=Decimal("0.20")),
            RateBracket(lower_bound_cents=20_000_000, upper_bound_cents=None, rate=Decimal("0.30")),
        ],
        auxiliary=_aux(),
    )
    # AGI $100k → tier 0; fill to 20% ceiling $200k → tier 3. Warning fires.
    out = optimize_roth_conversion(
        Form1040Inputs(filing_status="single", wages_cents=10_000_000), cfg,
        fill_to_rate=Decimal("0.20"), irmaa_config=ty2025_irmaa_config(), irmaa_filing_status="single",
    )
    assert out.recommended_conversion_cents == 10_000_000
    assert out.irmaa_warning is not None
    assert "IRMAA" in out.irmaa_warning


def test_scorp_salary_below_threshold_picks_floor() -> None:
    # $100k S-corp, single, TI below the $197,300 QBI threshold → QBI is
    # wage-independent, so the lowest reasonable salary wins.
    # floor $40k: payroll 6,120; QBI 20%·60k=12,000 capped under 20,000 → 12,000;
    # net = 6,120 − 0.24·12,000 = 6,120 − 2,880 = 3,240.
    # all-salary $100k: payroll 15,300, QBI 0 → net 15,300; savings 12,060.
    out = optimize_scorp_salary(
        net_business_income_cents=10_000_000, filing_status="single",
        taxable_income_before_qbi_cents=10_000_000, marginal_rate=Decimal("0.24"),
        scorp_config=ty2025_scorp_config(), qbi_config=ty2025_qbi_config(),
        reasonable_min_salary_cents=4_000_000, step_cents=1_000_000,
    )
    assert out.optimal_salary_cents == 4_000_000  # the floor
    assert out.net_cost_at_optimal_cents == 324_000
    assert out.all_salary_net_cost_cents == 1_530_000
    assert out.savings_vs_all_salary_cents == 1_206_000


def test_scorp_salary_above_threshold_interior_optimum() -> None:
    # High earner above the §199A threshold: the W-2 wage limit makes some salary
    # valuable, so the optimum is interior (not the floor, not all-salary) and
    # never worse than all-salary.
    out = optimize_scorp_salary(
        net_business_income_cents=40_000_000, filing_status="single",
        taxable_income_before_qbi_cents=40_000_000, marginal_rate=Decimal("0.35"),
        scorp_config=ty2025_scorp_config(), qbi_config=ty2025_qbi_config(),
        reasonable_min_salary_cents=5_000_000, step_cents=500_000,
    )
    assert 5_000_000 <= out.optimal_salary_cents <= 40_000_000
    assert out.optimal_salary_cents > 5_000_000  # wage limit makes salary worth raising
    assert out.savings_vs_all_salary_cents >= 0
    assert out.qbi_deduction_at_optimal_cents > 0
