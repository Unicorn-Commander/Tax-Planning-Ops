"""Golden tests for the flat + no-tax state configs against the adversarially
verified 2025 vectors. Dollars ×100 = cents."""

from __future__ import annotations

from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.state_configs import NO_INCOME_TAX, get_state_config


def _tax(state: str, agi: int, *, ss: int = 0, retirement: int = 0,
         status: str = "single", year: int = 2025) -> int:
    cfg = get_state_config(state, year)
    assert cfg is not None
    return calculate_state_tax(
        StateTaxInput(filing_status=status, federal_agi_cents=agi,
                      social_security_taxable_cents=ss, retirement_income_cents=retirement),
        cfg,
    ).total_state_tax_cents


def test_no_income_tax_states() -> None:
    for s in NO_INCOME_TAX:
        assert _tax(s, 20_000_000, ss=3_000_000, retirement=5_000_000) == 0


def test_il_single() -> None:
    assert _tax("IL", 8_000_000) == 381_900  # (80,000−2,850)·4.95% = $3,819


def test_il_mfj_retiree_zero() -> None:
    # $60k retirement + $30k SS, both exempt → $0.
    assert _tax("IL", 9_000_000, ss=3_000_000, retirement=6_000_000, status="mfj") == 0


def test_pa_single() -> None:
    assert _tax("PA", 8_000_000) == 245_600  # 80,000·3.07% = $2,456


def test_ma_single() -> None:
    assert _tax("MA", 8_000_000) == 378_000  # (80,000−4,400)·5% = $3,780


def test_ma_mfj_millionaire_surtax() -> None:
    # (1,200,000−8,800)·5% + 4%·(1,191,200−1,083,150) = 59,560 + 4,322 = $63,882.
    assert _tax("MA", 120_000_000, status="mfj") == 6_388_200


def test_ga_single() -> None:
    assert _tax("GA", 8_000_000) == 352_900  # (80,000−12,000)·5.19% = $3,529


def test_nc_single_2025_and_2026_rate() -> None:
    assert _tax("NC", 8_000_000) == 285_800  # 2025: (80,000−12,750)·4.25% = $2,858
    # 2026 rate drops to 3.99%: (80,000−12,750)·3.99% = $2,683.
    assert _tax("NC", 8_000_000, year=2026) == 268_300


def test_nc_mfj_retiree_ss_exempt() -> None:
    # AGI $150k incl $20k taxable SS (NC exempt) → (150,000−25,500−20,000)·4.25% = $4,441.
    assert _tax("NC", 15_000_000, ss=2_000_000, status="mfj") == 444_100


def test_az_single() -> None:
    assert _tax("AZ", 5_000_000) == 85_600  # (50,000−15,750)·2.5% = $856


def test_unknown_state_returns_none() -> None:
    assert get_state_config("ZZ") is None
