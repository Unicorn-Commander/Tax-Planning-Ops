"""2026 config golden checks (verified Rev. Proc. 2025-32 + OBBBA + 2026
CMS/SSA) and the year-aware selectors."""

from __future__ import annotations

from decimal import Decimal

from app.engines.amt import AMTInput, calculate_amt
from app.engines.irmaa import IRMAAInput, calculate_irmaa
from app.engines.se_tax import SETaxInput, calculate_se_tax
from app.year_configs import (
    amt_config_for,
    irmaa_config_for,
    qbi_config_for,
    se_config_for,
    ty2026_amt_config,
    ty2026_irmaa_config,
    ty2026_qbi_config,
    ty2026_se_tax_config,
)


def test_amt_2026_exemption_phaseout_rate() -> None:
    cfg = ty2026_amt_config()
    assert cfg.params["single"].exemption_cents == 9_010_000  # $90,100
    assert cfg.params["mfj"].phaseout_threshold_cents == 100_000_000  # $1M (OBBBA reset)
    assert cfg.phaseout_rate == Decimal("0.50")  # OBBBA doubled it
    # AMTI $300k single → exemption $90,100, excess $209,900 ≤ $244,500 →
    # 26%·209,900 = $54,574 TMT.
    out = calculate_amt(
        AMTInput(filing_status="single", regular_taxable_income_cents=30_000_000,
                 regular_tax_for_amt_cents=0),
        cfg,
    )
    assert out.tentative_minimum_tax_cents == 5_457_400


def test_qbi_2026_widened_thresholds() -> None:
    cfg = ty2026_qbi_config()
    assert cfg.thresholds["single"].threshold_cents == 20_175_000  # $201,750
    assert cfg.thresholds["single"].phase_in_width_cents == 7_500_000  # $75k (was $50k)
    assert cfg.thresholds["mfj"].threshold_cents == 40_350_000  # $403,500
    assert cfg.thresholds["mfj"].phase_in_width_cents == 15_000_000  # $150k


def test_se_2026_wage_base() -> None:
    cfg = ty2026_se_tax_config()
    assert cfg.ss_wage_base_cents == 18_450_000  # $184,500
    # $250k profit → OASDI capped at $184,500: 184,500·12.4% = $22,878.
    out = calculate_se_tax(SETaxInput(net_self_employment_profit_cents=25_000_000), cfg)
    assert out.oasdi_cents == 2_287_800
    assert out.oasdi_taxable_base_cents == 18_450_000


def test_irmaa_2026_part_b_base_and_tiers() -> None:
    cfg = ty2026_irmaa_config()
    assert cfg.part_b_base_cents == 20_290  # $202.90 (up from $185)
    # single MAGI $150k → tier 2: Part B total $405.80, surcharge $202.90.
    out = calculate_irmaa(IRMAAInput(filing_status="single", magi_cents=15_000_000), cfg)
    assert out.irmaa_tier == 2
    assert out.part_b_total_monthly_cents == 40_580
    assert out.part_b_surcharge_monthly_cents == 20_290


def test_selectors_pick_year() -> None:
    assert amt_config_for(2025).tax_year == 2025
    assert amt_config_for(2026).tax_year == 2026
    assert amt_config_for(2027).tax_year == 2026  # latest known
    assert qbi_config_for(2026).thresholds["single"].threshold_cents == 20_175_000
    assert se_config_for(2025).ss_wage_base_cents == 17_610_000
    assert se_config_for(2026).ss_wage_base_cents == 18_450_000
    assert irmaa_config_for(2026).part_b_base_cents == 20_290
