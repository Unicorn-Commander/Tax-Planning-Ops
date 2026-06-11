"""Golden tests for the Phase-3 multi-entity engines (TY2025).

All vectors adversarially verified (SE tax, §199A QBI full rules, S-corp
reasonable-comp split). Dollars ×100 = cents.
"""

from __future__ import annotations

from decimal import Decimal

from app.engine_configs import ty2025_qbi_config, ty2025_scorp_config, ty2025_se_tax_config
from app.engines.qbi import QBIInput, calculate_qbi
from app.engines.scorp import SCorpInput, calculate_scorp_split
from app.engines.se_tax import SETaxInput, calculate_se_tax

SE = ty2025_se_tax_config()
QBI = ty2025_qbi_config()
SC = ty2025_scorp_config()


# ----------------------------- SE tax ------------------------------------


def test_se_below_base_no_w2() -> None:
    out = calculate_se_tax(SETaxInput(net_self_employment_profit_cents=10_000_000), SE)
    assert out.net_se_earnings_cents == 9_235_000
    assert out.oasdi_taxable_base_cents == 9_235_000
    assert out.total_se_tax_cents == 1_412_900  # $14,129
    assert out.half_se_deduction_cents == 706_500  # $7,065 (half-up tie)


def test_se_above_base_medicare_uncapped() -> None:
    out = calculate_se_tax(SETaxInput(net_self_employment_profit_cents=25_000_000), SE)
    assert out.net_se_earnings_cents == 23_087_500
    assert out.oasdi_taxable_base_cents == 17_610_000  # capped at wage base
    assert out.total_se_tax_cents == 2_853_100  # $28,531
    assert out.half_se_deduction_cents == 1_426_600  # $14,266


def test_se_w2_coordination() -> None:
    # $120k profit, $150k W-2 SS wages already taxed → OASDI only on remaining
    # $26,100 of base; Medicare uncapped on full net earnings.
    out = calculate_se_tax(
        SETaxInput(net_self_employment_profit_cents=12_000_000,
                   w2_social_security_wages_cents=15_000_000),
        SE,
    )
    assert out.net_se_earnings_cents == 11_082_000
    assert out.oasdi_taxable_base_cents == 2_610_000
    assert out.total_se_tax_cents == 645_000  # $6,450
    assert out.half_se_deduction_cents == 322_500


def test_se_config_guard() -> None:
    assert SE.ss_wage_base_cents == 17_610_000
    assert SE.net_earnings_factor == Decimal("0.9235")


# ----------------------------- §199A QBI ---------------------------------


def test_qbi_below_threshold() -> None:
    out = calculate_qbi(
        QBIInput(filing_status="single", qualified_business_income_cents=10_000_000,
                 taxable_income_before_qbi_cents=15_000_000),
        QBI,
    )
    assert out.regime == "below"
    assert out.allowed_qbi_deduction_cents == 2_000_000  # 20% of QBI
    assert out.overall_cap_cents == 3_000_000


def test_qbi_full_wage_limit_binds() -> None:
    out = calculate_qbi(
        QBIInput(filing_status="mfj", qualified_business_income_cents=30_000_000,
                 w2_wages_cents=8_000_000, ubia_cents=20_000_000,
                 taxable_income_before_qbi_cents=60_000_000, net_capital_gain_cents=4_000_000),
        QBI,
    )
    assert out.regime == "full"
    assert out.wage_limit_cents == 4_000_000  # max(50%·80k, 25%·80k+2.5%·200k)
    assert out.qbi_component_cents == 4_000_000
    assert out.overall_cap_cents == 11_200_000
    assert out.allowed_qbi_deduction_cents == 4_000_000


def test_qbi_phase_in_sstb() -> None:
    # single, full QBI $200k, W-2 $50k, SSTB, TI $222,300 → fraction 0.5,
    # SSTB-reduced first then wage-limit phase-in → allowed $16,250.
    out = calculate_qbi(
        QBIInput(filing_status="single", qualified_business_income_cents=20_000_000,
                 w2_wages_cents=5_000_000, taxable_income_before_qbi_cents=22_230_000,
                 is_sstb=True),
        QBI,
    )
    assert out.regime == "phase_in"
    assert out.phase_in_fraction == Decimal("0.5")
    assert out.tentative_deduction_cents == 4_000_000  # 20% of full QBI
    assert out.qbi_component_cents == 1_625_000
    assert out.allowed_qbi_deduction_cents == 1_625_000


def test_qbi_config_guard() -> None:
    assert QBI.thresholds["single"].threshold_cents == 19_730_000
    assert QBI.thresholds["mfj"].threshold_cents == 39_460_000
    assert QBI.thresholds["mfs"].threshold_cents == 19_730_000  # NOT halved


# ----------------------- S-corp reasonable comp --------------------------


def test_scorp_below_ss_base() -> None:
    out = calculate_scorp_split(
        SCorpInput(filing_status="single", net_business_income_cents=12_000_000,
                   reasonable_salary_cents=6_000_000),
        SC,
    )
    assert out.chosen.total_cents == 918_000  # $9,180
    assert out.baseline_all_salary.total_cents == 1_836_000  # $18,360
    assert out.fica_savings_cents == 918_000
    assert out.distribution_cents == 6_000_000


def test_scorp_salary_under_base_large_distribution() -> None:
    out = calculate_scorp_split(
        SCorpInput(filing_status="single", net_business_income_cents=30_000_000,
                   reasonable_salary_cents=15_000_000),
        SC,
    )
    assert out.chosen.total_cents == 2_295_000  # $22,950
    assert out.baseline_all_salary.total_cents == 3_143_600  # $31,436 (SS capped + add'l medicare)
    assert out.fica_savings_cents == 848_600  # $8,486


def test_scorp_salary_exceeds_base() -> None:
    out = calculate_scorp_split(
        SCorpInput(filing_status="single", net_business_income_cents=50_000_000,
                   reasonable_salary_cents=20_000_000),
        SC,
    )
    assert out.chosen.total_cents == 2_763_600  # $27,636
    assert out.baseline_all_salary.total_cents == 3_903_600  # $39,036
    assert out.fica_savings_cents == 1_140_000  # $11,400


def test_scorp_config_guard() -> None:
    assert SC.ss_wage_base_cents == 17_610_000
    assert SC.additional_medicare_threshold_cents["single"] == 20_000_000
    assert SC.additional_medicare_threshold_cents["mfj"] == 25_000_000


# --------------------- §199A multi-business aggregate --------------------


def test_qbi_aggregate_below_threshold() -> None:
    from app.engines.qbi import QBIBusiness, calculate_qbi_aggregate

    out = calculate_qbi_aggregate(
        [
            QBIBusiness(qualified_business_income_cents=10_000_000),
            QBIBusiness(qualified_business_income_cents=5_000_000),
        ],
        filing_status="single",
        taxable_income_before_qbi_cents=15_000_000,
        net_capital_gain_cents=0,
        config=QBI,
    )
    # components 20% each: 2,000,000 + 1,000,000 = 3,000,000; cap 0.20·150k = 3,000,000.
    assert out.combined_qbi_component_cents == 3_000_000
    assert out.allowed_qbi_deduction_cents == 3_000_000


def test_qbi_aggregate_wage_limit_per_business() -> None:
    from app.engines.qbi import QBIBusiness, calculate_qbi_aggregate

    out = calculate_qbi_aggregate(
        [
            # above-threshold business with wages → component 40,000 (vector B)
            QBIBusiness(qualified_business_income_cents=30_000_000, w2_wages_cents=8_000_000,
                        ubia_cents=20_000_000),
            # above-threshold business with NO wages → wage limit 0 → component 0
            QBIBusiness(qualified_business_income_cents=10_000_000),
        ],
        filing_status="mfj",
        taxable_income_before_qbi_cents=60_000_000,
        net_capital_gain_cents=4_000_000,
        config=QBI,
    )
    assert out.per_business[0].qbi_component_cents == 4_000_000
    assert out.per_business[1].qbi_component_cents == 0
    assert out.combined_qbi_component_cents == 4_000_000
    assert out.overall_cap_cents == 11_200_000
    assert out.allowed_qbi_deduction_cents == 4_000_000
