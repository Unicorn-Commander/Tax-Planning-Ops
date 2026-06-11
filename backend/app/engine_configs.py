"""2025 default configs for the multi-entity engines.

These live OUTSIDE app/engines/ so the engine modules stay free of hardcoded
high-liability constants (enforced by tests/test_engine_constant_guard.py): the
engines are pure logic that take a config, and the year's statutory values are
assembled here. Firms can later override these via stored config.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.qbi import QBIConfig, QBIThreshold
from app.engines.scorp import SCorpConfig
from app.engines.se_tax import SETaxConfig


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
