"""2025 default configs for the multi-entity engines.

These live OUTSIDE app/engines/ so the engine modules stay free of hardcoded
high-liability constants (enforced by tests/test_engine_constant_guard.py): the
engines are pure logic that take a config, and the year's statutory values are
assembled here. Firms can later override these via stored config.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.corporate import CorporateConfig, StateCorporateConfig
from app.engines.qbi import QBIConfig, QBIThreshold
from app.engines.scorp import SCorpConfig
from app.engines.se_tax import SETaxConfig

# State C-corp income-tax rates for TY2025, keyed by state. Value = the rate a
# typical (small/mid) C-corp pays on its state taxable income: a flat rate, or
# the top marginal rate where the top bracket is readily reached. High-income
# SURTAXES that bite only very large corporations are NOT folded in (consistent
# with using CT's 7.5% base, not its >$100M 8.25% surtax): NJ base 9.0% (a 2.5%
# transit surtax applies over $10M income); NY base 6.5% (7.25% over $5M business
# income). IL 9.5% = the 7.0% income tax + the 2.5% PPRT, which applies to ALL
# C-corps. DE and OR ALSO levy a separate gross-receipts tax on top of the income
# rate shown (not added here). NH (Business Profits Tax) and TN (excise) are
# income-measured, so included. States with NO net-income corporate tax are
# intentionally absent so state_corporate_config(_for) returns None: SD, WY (none
# at all); OH (CAT gross-receipts), WA (B&O), NV (commerce), TX (franchise/margin)
# — none of which is a net-income tax. SC's license fee is a separate non-income
# levy, not represented here.
STATE_CORPORATE_RATES: dict[str, str] = {
    "SC": "0.05",
    "AL": "0.065", "AR": "0.043", "CO": "0.044", "CT": "0.075", "DE": "0.087",
    "DC": "0.0825", "HI": "0.064", "IA": "0.071", "ID": "0.053", "IN": "0.049",
    "KS": "0.07", "KY": "0.05", "LA": "0.055", "MD": "0.0825", "ME": "0.0893",
    "MI": "0.06", "MN": "0.098", "MO": "0.04", "MS": "0.05", "MT": "0.0675",
    "NE": "0.052", "NM": "0.059", "ND": "0.0431", "OK": "0.04", "OR": "0.076",
    "RI": "0.07", "UT": "0.045", "VT": "0.085", "WI": "0.079", "WV": "0.065",
    # TY2025 fill — the remaining income-taxing jurisdictions:
    "AK": "0.094", "AZ": "0.049", "CA": "0.0884", "FL": "0.055", "GA": "0.0519",
    "IL": "0.095", "MA": "0.08", "NH": "0.075", "NJ": "0.09", "NY": "0.065",
    "NC": "0.0225", "PA": "0.0799", "TN": "0.065", "VA": "0.06",
}


def state_corporate_config(state: str, tax_year: int) -> StateCorporateConfig | None:
    rate = STATE_CORPORATE_RATES.get((state or "").upper())
    if rate is None:
        return None
    return StateCorporateConfig(
        state=state.upper(), tax_year=tax_year, corporate_rate=Decimal(rate)
    )


def ty2025_corporate_config() -> CorporateConfig:
    return CorporateConfig(
        tax_year=2025,
        corporate_rate=Decimal("0.21"),  # flat federal C-corp rate
        nol_limit_pct=Decimal("0.80"),  # §172 80%-of-taxable-income limit
        qsbs_rate=Decimal("0.28"),  # §1202 28% rate on the taxable gain
        qsbs_cap_new_cents=1_500_000_000,  # $15M (stock acquired after 7/4/2025)
        qsbs_cap_old_cents=1_000_000_000,  # $10M (older stock)
        qsbs_assets_ceiling_new_cents=7_500_000_000,  # $75M
        qsbs_assets_ceiling_old_cents=5_000_000_000,  # $50M
        aet_rate=Decimal("0.20"),  # §531 accumulated earnings tax
        aet_credit_cents=25_000_000,  # $250,000
        aet_credit_psc_cents=15_000_000,  # $150,000 (personal service corps)
    )


def ty2025_se_tax_config() -> SETaxConfig:
    return SETaxConfig(
        tax_year=2025,
        net_earnings_factor=Decimal("0.9235"),
        ss_wage_base_cents=17_610_000,  # $176,100
        oasdi_rate=Decimal("0.124"),
        medicare_rate=Decimal("0.029"),
        half_deduction_rate=Decimal("0.50"),
        filing_floor_cents=40_000,  # $400
    )


def ty2025_qbi_config() -> QBIConfig:
    single = QBIThreshold(threshold_cents=19_730_000, phase_in_width_cents=5_000_000)
    mfj = QBIThreshold(threshold_cents=39_460_000, phase_in_width_cents=10_000_000)
    return QBIConfig(
        tax_year=2025,
        thresholds={"single": single, "hoh": single, "qss": mfj, "mfs": single, "mfj": mfj},
    )


def ty2025_scorp_config() -> SCorpConfig:
    return SCorpConfig(
        tax_year=2025,
        ss_wage_base_cents=17_610_000,  # $176,100
        oasdi_rate=Decimal("0.124"),
        medicare_rate=Decimal("0.029"),
        additional_medicare_rate=Decimal("0.009"),
        additional_medicare_threshold_cents={
            "single": 20_000_000,  # $200,000
            "hoh": 20_000_000,
            "qss": 25_000_000,
            "mfj": 25_000_000,  # $250,000
            "mfs": 12_500_000,  # $125,000
        },
    )
