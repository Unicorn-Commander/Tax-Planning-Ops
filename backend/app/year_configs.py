"""Year-aware engine config selection.

It is the active 2026 planning year, so the engines must use the right year's
constants. Federal brackets are already year-keyed in the DB; this module does
the same for the inflation-adjusted engine configs (AMT, QBI, IRMAA, SE tax,
Form 2210). 2026 figures are research- and adversarially-verified (Rev. Proc.
2025-32 + OBBBA, 2026 CMS IRMAA tables, 2026 SSA wage base).

Unchanged for 2026 (selectors return the 2025 config): CTC ($2,200/$1,700 held
flat by the $100 rounding rule), §86 SS taxability (statutory fixed bases), and
the C-corp engine (21% / 80% NOL / §1202 caps indexed only from 2027).
"""

from __future__ import annotations

from decimal import Decimal

from app.engine_configs import (
    ty2025_corporate_config,
    ty2025_qbi_config,
    ty2025_scorp_config,
    ty2025_se_tax_config,
)
from app.engines.amt import AMTBracketParams, AMTConfig, ty2025_amt_config
from app.engines.corporate import CorporateConfig
from app.engines.ctc import CTCConfig, ty2025_ctc_config
from app.engines.form2210 import Form2210Config, ty2025_form2210_config
from app.engines.irmaa import IRMAAConfig, ty2025_irmaa_config
from app.engines.qbi import QBIConfig, QBIThreshold
from app.engines.scorp import SCorpConfig
from app.engines.se_tax import SETaxConfig
from app.engines.ss_taxability import SSConfig, ty2025_ss_config

# ---- 2026 configs (OBBBA + Rev. Proc. 2025-32 + 2026 CMS/SSA) --------------


def ty2026_amt_config() -> AMTConfig:
    # OBBBA reset the phaseout thresholds to (inflation-adjusted) 2018 levels
    # AND doubled the phaseout rate to 50%, effective TY2026.
    single = AMTBracketParams(
        exemption_cents=9_010_000, phaseout_threshold_cents=50_000_000,
        rate_breakpoint_cents=24_450_000, breakpoint_subtraction_cents=489_000)
    mfj = AMTBracketParams(
        exemption_cents=14_020_000, phaseout_threshold_cents=100_000_000,
        rate_breakpoint_cents=24_450_000, breakpoint_subtraction_cents=489_000)
    mfs = AMTBracketParams(
        exemption_cents=7_010_000, phaseout_threshold_cents=50_000_000,
        rate_breakpoint_cents=12_225_000, breakpoint_subtraction_cents=244_500)
    return AMTConfig(
        tax_year=2026,
        params={"single": single, "hoh": single, "qss": mfj, "mfj": mfj, "mfs": mfs},
        phaseout_rate=Decimal("0.50"),
    )


def ty2026_qbi_config() -> QBIConfig:
    # OBBBA widened the phase-in ranges to $75k single / $150k MFJ.
    single = QBIThreshold(threshold_cents=20_175_000, phase_in_width_cents=7_500_000)
    mfj = QBIThreshold(threshold_cents=40_350_000, phase_in_width_cents=15_000_000)
    mfs = QBIThreshold(threshold_cents=20_177_500, phase_in_width_cents=7_500_000)
    return QBIConfig(
        tax_year=2026,
        thresholds={"single": single, "hoh": single, "qss": mfj, "mfs": mfs, "mfj": mfj},
    )


def ty2026_se_tax_config() -> SETaxConfig:
    return SETaxConfig(
        tax_year=2026, net_earnings_factor=Decimal("0.9235"),
        ss_wage_base_cents=18_450_000,  # $184,500 (2026)
        oasdi_rate=Decimal("0.124"), medicare_rate=Decimal("0.029"),
        half_deduction_rate=Decimal("0.50"), filing_floor_cents=40_000,
    )


def ty2026_irmaa_config() -> IRMAAConfig:
    surcharges = [
        (0, 0), (8_120, 1_450), (20_290, 3_750), (32_460, 6_040), (44_630, 8_330),
        (48_700, 9_100),
    ]
    cliffs = {
        "single": [(10_900_000, 1), (13_700_000, 2), (17_100_000, 3), (20_500_000, 4),
                   (50_000_000, 5)],
        "mfj": [(21_800_000, 1), (27_400_000, 2), (34_200_000, 3), (41_000_000, 4),
                (75_000_000, 5)],
        "mfs_lived_with_spouse": [(10_900_000, 4), (39_100_000, 5)],
    }
    return IRMAAConfig(
        plan_year=2026, part_b_base_cents=20_290, tier_surcharges=surcharges, cliffs=cliffs)


def ty2026_form2210_config() -> Form2210Config:
    # 2026 IRS underpayment rate varied (Q1/Q3 7%, Q2 6%); a flat 7% is the
    # representative planning rate across the penalty window.
    return Form2210Config(tax_year=2026)


def ty2026_scorp_config() -> SCorpConfig:
    return SCorpConfig(
        tax_year=2026, ss_wage_base_cents=18_450_000,  # $184,500
        oasdi_rate=Decimal("0.124"), medicare_rate=Decimal("0.029"),
        additional_medicare_rate=Decimal("0.009"),
        additional_medicare_threshold_cents={
            "single": 20_000_000, "hoh": 20_000_000, "qss": 25_000_000,
            "mfj": 25_000_000, "mfs": 12_500_000,
        },
    )


# ---- year-aware selectors --------------------------------------------------


def amt_config_for(year: int) -> AMTConfig:
    return ty2026_amt_config() if year >= 2026 else ty2025_amt_config()


def qbi_config_for(year: int) -> QBIConfig:
    return ty2026_qbi_config() if year >= 2026 else ty2025_qbi_config()


def se_config_for(year: int) -> SETaxConfig:
    return ty2026_se_tax_config() if year >= 2026 else ty2025_se_tax_config()


def irmaa_config_for(year: int) -> IRMAAConfig:
    return ty2026_irmaa_config() if year >= 2026 else ty2025_irmaa_config()


def form2210_config_for(year: int) -> Form2210Config:
    return ty2026_form2210_config() if year >= 2026 else ty2025_form2210_config()


def ctc_config_for(year: int) -> CTCConfig:  # 2026 == 2025
    return ty2025_ctc_config()


def ss_config_for(year: int) -> SSConfig:  # statutory fixed bases
    return ty2025_ss_config()


def corporate_config_for(year: int) -> CorporateConfig:  # unchanged for 2026
    return ty2025_corporate_config()


def scorp_config_for(year: int) -> SCorpConfig:
    return ty2026_scorp_config() if year >= 2026 else ty2025_scorp_config()
