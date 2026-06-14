"""Golden tests for the flat + no-tax state configs against the adversarially
verified 2025 vectors. Dollars ×100 = cents."""

from __future__ import annotations

from app.engine_configs import state_corporate_config
from app.engines.state_tax import StateTaxInput, calculate_state_tax
from app.state_configs import NO_INCOME_TAX, get_state_config

# The 50 states + DC. Every entry must resolve to a StateTaxConfig, be a
# no-income-tax state, or be one of the explicitly-modeled-as-None exceptions
# below (a state whose mechanics the current engine can't represent yet).
ALL_JURISDICTIONS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]
# OH grades from statutory base amounts the bracket engine can't yet model, so
# it intentionally resolves to None (flagged not-yet-modeled, like the docstring
# in state_configs.py / state_brackets.py says). Not a coverage gap.
MODELED_AS_NONE = {"OH"}


def _tax(state: str, agi: int, *, fti: int = 0, ss: int = 0, retirement: int = 0,
         status: str = "single", year: int = 2025) -> int:
    cfg = get_state_config(state, year)
    assert cfg is not None
    return calculate_state_tax(
        StateTaxInput(filing_status=status, federal_agi_cents=agi,
                      federal_taxable_income_cents=fti,
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


def test_ca_single_and_mfj() -> None:
    # AGI $80k, $15k SS excluded → taxable $59,294 → $2,128.
    assert _tax("CA", 8_000_000, ss=1_500_000) == 212_800
    # MFJ AGI $250k → taxable $238,588 → $15,066.
    assert _tax("CA", 25_000_000, status="mfj") == 1_506_600


def test_ny_single() -> None:
    # AGI $80k, $10k SS excluded → taxable $62,000 → $3,245.
    assert _tax("NY", 8_000_000, ss=1_000_000) == 324_500


def test_nj_mfj_and_single() -> None:
    assert _tax("NJ", 12_000_000, status="mfj") == 385_500  # $120k → $3,855
    assert _tax("NJ", 60_000_000) == 3_869_400  # $600k → $38,694


def test_va_single() -> None:
    # AGI $60k → taxable $51,250 → $2,689.
    assert _tax("VA", 6_000_000) == 268_900


# --- "All 50 states + DC supported" guarantee ------------------------------

def test_all_jurisdictions_resolve() -> None:
    """Every state + DC resolves to a config, a no-income-tax state, or one of
    the explicitly-modeled-as-None exceptions. This is the coverage promise."""
    assert len(ALL_JURISDICTIONS) == 51
    for code in ALL_JURISDICTIONS:
        cfg = get_state_config(code, 2025)
        if code in NO_INCOME_TAX:
            assert cfg is not None and cfg.has_income_tax is False, code
        elif code in MODELED_AS_NONE:
            assert cfg is None, f"{code} expected modeled-as-None"
        else:
            assert cfg is not None and cfg.has_income_tax is True, code


def test_every_income_tax_state_computes_nonzero() -> None:
    """Each income-taxing jurisdiction produces a positive tax on a healthy
    income (smoke test that brackets/flat rate/starting point are wired)."""
    for code in ALL_JURISDICTIONS:
        if code in NO_INCOME_TAX or code in MODELED_AS_NONE:
            continue
        # $200k for both starting points so FTI-based states (CO/ID/ME/MT/ND/OR)
        # also see income above their zero brackets.
        tax = _tax(code, 20_000_000, fti=20_000_000)
        assert tax > 0, f"{code} returned {tax}"


# --- Golden hand-checks for the new fill (computed by hand, ±$1) ------------

def test_ky_single_flat() -> None:
    # New FLAT (federal_agi). std $3,270. (50,000−3,270)·4.0% = $1,869.20 → $1,869.
    assert _tax("KY", 5_000_000) == 186_900


def test_ct_single_graduated() -> None:
    # New GRADUATED (federal_agi). $100k, std $15,000 → taxable $85,000.
    # 10k·2% + 40k·4.5% + 35k·5.5% = 200 + 1,800 + 1,925 = $3,925.
    assert _tax("CT", 10_000_000) == 392_500


def test_co_single_fti() -> None:
    # New FLAT (federal_taxable_income). No CO std. 80,000·4.40% = $3,520.
    assert _tax("CO", 8_000_000, fti=8_000_000) == 352_000


def test_mt_single_fti_graduated() -> None:
    # New GRADUATED on federal_taxable_income, std 0. $40k FTI:
    # 21,100·4.7% + 18,900·5.9% = 991.70 + 1,115.10 = $2,106.80 → $2,107.
    assert _tax("MT", 4_000_000, fti=4_000_000) == 210_700


# --- Corporate-rate coverage -----------------------------------------------

def test_corporate_rates_for_new_states() -> None:
    from decimal import Decimal

    # A graded-rate state (top marginal used) and a flat-rate state.
    assert state_corporate_config("MN", 2025).corporate_rate == Decimal("0.098")
    assert state_corporate_config("CO", 2025).corporate_rate == Decimal("0.044")
    # No-corporate-income-tax jurisdictions stay None (TX margin tax, OH CAT, WY).
    for code in ("TX", "OH", "WY", "SD", "NV", "WA"):
        assert state_corporate_config(code, 2025) is None, code
