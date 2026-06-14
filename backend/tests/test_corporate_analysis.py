"""Tests for the integrated C-corp (Form 1120) planning analysis.

Pure-engine: `build_corporate_analysis` takes already-loaded inputs, so these
run without a DB and assert that every figure is engine-computed — the corporate
tax equals the corporate engine's 21% + state output, the owner side equals the
Form 1040 engine's incremental tax, and the optimization lands on the REAL
minimum of the integrated total (recomputed independently here). Dollars ×100 =
cents.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.engine_configs import ty2025_corporate_config
from app.engines.corporate import (
    CorporateTaxInput,
    StateCorporateConfig,
    calculate_corporate_tax,
    calculate_state_corporate_tax,
)
from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    RateBracket,
    TaxConfig,
    calculate_form1040,
)
from app.models.entity import BusinessEntity
from app.services.corporate_analysis import (
    _employee_fica_cents,
    build_corporate_analysis,
)
from app.year_configs import scorp_config_for


def _config() -> TaxConfig:
    """A realistic-ish 2025 single-filer config (figures don't need to be exact
    statutory values — the tests assert the engine is USED, not the dollar)."""
    return TaxConfig(
        tax_year=2025,
        filing_status="single",
        standard_deduction_cents=1_500_000,  # $15k
        ordinary_brackets=[
            RateBracket(lower_bound_cents=0, upper_bound_cents=1_160_000, rate=Decimal("0.10")),
            RateBracket(
                lower_bound_cents=1_160_000, upper_bound_cents=4_715_000, rate=Decimal("0.12")
            ),
            RateBracket(
                lower_bound_cents=4_715_000, upper_bound_cents=10_052_500, rate=Decimal("0.22")
            ),
            RateBracket(
                lower_bound_cents=10_052_500, upper_bound_cents=19_195_000, rate=Decimal("0.24")
            ),
            RateBracket(
                lower_bound_cents=19_195_000, upper_bound_cents=24_372_500, rate=Decimal("0.32")
            ),
            RateBracket(
                lower_bound_cents=24_372_500, upper_bound_cents=60_935_000, rate=Decimal("0.35")
            ),
            RateBracket(lower_bound_cents=60_935_000, upper_bound_cents=None, rate=Decimal("0.37")),
        ],
        auxiliary=AuxiliaryConfig(
            ltcg_brackets=[
                RateBracket(lower_bound_cents=0, upper_bound_cents=4_862_500, rate=Decimal("0.00")),
                RateBracket(
                    lower_bound_cents=4_862_500,
                    upper_bound_cents=53_340_000,
                    rate=Decimal("0.15"),
                ),
                RateBracket(
                    lower_bound_cents=53_340_000, upper_bound_cents=None, rate=Decimal("0.20")
                ),
            ],
            niit_threshold_cents=20_000_000,
            niit_rate=Decimal("0.038"),
            additional_medicare_threshold_cents=20_000_000,
            additional_medicare_rate=Decimal("0.009"),
            capital_loss_limit_cents=300_000,
        ),
    )


def _c_corp(**kw: object) -> BusinessEntity:
    defaults = dict(
        name="Test C-corp", amount_cents=0, w2_wages_paid_cents=0, ubia_cents=0,
        guaranteed_payments_cents=0, shareholder_w2_wages_cents=0,
        is_general_partner=True, is_sstb=False, is_qbi=False,
        dividends_cents=0, nol_available_cents=0,
    )
    defaults.update(kw)
    return BusinessEntity(kind="c_corp", **defaults)  # type: ignore[arg-type]


def test_no_c_corp_unavailable() -> None:
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(),
        tax_year=2025,
        filing_status="single",
        state="SC",
        client_name="Acme",
        c_corps=[],
        base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    assert out.available is False
    assert out.corporate_return is None
    assert out.optimization is None


def test_corporate_return_federal_only_matches_engine() -> None:
    # $300k corporate taxable income (post-salary), no state → 21% = $63,000.
    corp = _c_corp(amount_cents=30_000_000, shareholder_w2_wages_cents=10_000_000,
                   dividends_cents=5_000_000)
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(),
        tax_year=2025,
        filing_status="single",
        state=None,  # no state corporate tax
        client_name="Acme",
        c_corps=[corp],
        base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    assert out.available is True
    cr = out.corporate_return
    assert cr is not None
    # Federal corporate tax = the engine's 21%.
    engine = calculate_corporate_tax(
        CorporateTaxInput(pre_nol_taxable_income_cents=30_000_000), ty2025_corporate_config()
    )
    assert cr.federal_corporate_tax_cents == engine.corporate_tax_cents == 6_300_000
    assert cr.state_has_corporate_tax is False
    assert cr.state_corporate_tax_cents == 0
    assert cr.total_corporate_tax_cents == 6_300_000
    # Effective corporate rate = 21% (no NOL, no state).
    assert Decimal(cr.effective_corporate_rate) == Decimal("0.21")


def test_state_corporate_tax_layered_matches_engine() -> None:
    # SC 5% on the same $300k post-NOL taxable income = $15,000 on top of fed.
    corp = _c_corp(amount_cents=30_000_000, shareholder_w2_wages_cents=10_000_000,
                   dividends_cents=5_000_000)
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(),
        tax_year=2025,
        filing_status="single",
        state="SC",
        client_name="Acme",
        c_corps=[corp],
        base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    cr = out.corporate_return
    assert cr is not None
    state_engine = calculate_state_corporate_tax(
        30_000_000, StateCorporateConfig(state="SC", tax_year=2025, corporate_rate=Decimal("0.05"))
    )
    assert cr.state_has_corporate_tax is True
    assert cr.state_corporate_tax_cents == state_engine.state_corporate_tax_cents == 1_500_000
    assert cr.total_corporate_tax_cents == 6_300_000 + 1_500_000
    # Effective corporate rate = (fed + state) / pre-NOL income = 26%.
    assert Decimal(cr.effective_corporate_rate) == Decimal("0.26")


def test_nol_applied_in_corporate_return() -> None:
    # Pre-NOL $200k, $500k NOL → deduct 80%·200k = $160k → taxable $40k, tax $8,400.
    corp = _c_corp(amount_cents=20_000_000, nol_available_cents=50_000_000,
                   shareholder_w2_wages_cents=8_000_000)
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(),
        tax_year=2025,
        filing_status="single",
        state=None,
        client_name="Acme",
        c_corps=[corp],
        base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    cr = out.corporate_return
    assert cr is not None
    assert cr.nol_applied_cents == 16_000_000
    assert cr.corporate_taxable_income_cents == 4_000_000
    assert cr.federal_corporate_tax_cents == 840_000
    assert cr.nol_carryforward_remaining_cents == 34_000_000


def test_double_tax_identity_and_retained_earnings() -> None:
    corp = _c_corp(amount_cents=30_000_000, shareholder_w2_wages_cents=10_000_000,
                   dividends_cents=5_000_000)
    cfg = _config()
    base = Form1040Inputs(filing_status="single")
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(), tax_year=2025, filing_status="single", state=None,
        client_name="Acme", c_corps=[corp], base_inputs=base, config=cfg,
    )
    dt = out.double_tax
    cr = out.corporate_return
    assert dt is not None and cr is not None

    # Owner personal tax = the Form 1040 engine's incremental tax on +$100k wages
    # + $50k qualified dividends over the (empty) base — engine-computed, not faked.
    base_tax = calculate_form1040(base, cfg).total_tax_cents
    with_corp = calculate_form1040(
        base.model_copy(update={
            "wages_cents": 10_000_000,
            "qualified_dividends_cents": 5_000_000,
            "ordinary_dividends_cents": 5_000_000,
        }),
        cfg,
    ).total_tax_cents
    assert dt.owner_personal_tax_cents == with_corp - base_tax

    # Payroll = the employee-side FICA helper (engine constants).
    assert dt.owner_payroll_tax_cents == _employee_fica_cents(
        10_000_000, scorp_config_for(2025), "single"
    )

    # The integrated total IS the sum of its parts (no hidden fabrication).
    assert dt.integrated_total_tax_cents == (
        dt.corporate_tax_cents + dt.owner_personal_tax_cents + dt.owner_payroll_tax_cents
    )
    # Retained earnings = corporate taxable income − corp tax − dividends.
    assert dt.retained_earnings_cents == (
        cr.corporate_taxable_income_cents - cr.total_corporate_tax_cents - 5_000_000
    )


def test_optimization_picks_the_real_minimum() -> None:
    corp = _c_corp(amount_cents=30_000_000, shareholder_w2_wages_cents=10_000_000,
                   dividends_cents=5_000_000)
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(), tax_year=2025, filing_status="single", state="SC",
        client_name="Acme", c_corps=[corp], base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    opt = out.optimization
    assert opt is not None
    # Pool = current salary ($100k) + current dividends ($50k) = $150k; held constant.
    assert opt.comp_pool_cents == 15_000_000
    # Every point keeps salary + dividends == pool.
    for p in opt.curve:
        assert p.salary_cents + p.dividends_cents == opt.comp_pool_cents
        # Each point's integrated total is the sum of its engine parts.
        assert p.integrated_total_tax_cents == (
            p.corporate_tax_cents + p.owner_personal_tax_cents + p.owner_payroll_tax_cents
        )
    # The reported optimum IS the real argmin of the swept curve.
    true_min = min(p.integrated_total_tax_cents for p in opt.curve)
    assert opt.optimal_integrated_total_tax_cents == true_min
    optimal_point = next(
        p for p in opt.curve if p.salary_cents == opt.optimal_salary_cents
    )
    assert optimal_point.integrated_total_tax_cents == true_min
    # Savings vs the current split is non-negative (the optimum is at least as good).
    assert opt.savings_vs_current_cents >= 0
    assert opt.optimal_integrated_total_tax_cents <= opt.current_integrated_total_tax_cents


def test_optimization_favors_salary_when_corp_rate_high() -> None:
    # With a LOW owner marginal rate (empty base) and a 21%+5% corporate rate,
    # shifting a dollar from dividend to salary removes 26% corporate tax and adds
    # only the owner's low ordinary + FICA — so the optimum should be salary-heavy.
    corp = _c_corp(amount_cents=20_000_000, shareholder_w2_wages_cents=2_000_000,
                   dividends_cents=8_000_000)  # $20k salary, $80k dividends, pool $100k
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(), tax_year=2025, filing_status="single", state="SC",
        client_name="Acme", c_corps=[corp], base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    opt = out.optimization
    assert opt is not None
    # More salary is favored over the current dividend-heavy split.
    assert opt.optimal_salary_cents > opt.current_salary_cents


def test_aet_watch_flags_large_retained_earnings() -> None:
    # $2M corporate taxable income, no dividends → big retained earnings, AET-exposed.
    corp = _c_corp(amount_cents=200_000_000, shareholder_w2_wages_cents=10_000_000,
                   dividends_cents=0)
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(), tax_year=2025, filing_status="single", state=None,
        client_name="Acme", c_corps=[corp], base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    aet = out.aet
    assert aet is not None
    # ATI proxy = corp taxable income ($2M) − corp tax ($420k) − dividends ($0).
    assert aet.accumulated_taxable_income_cents == 200_000_000 - 42_000_000
    assert aet.credit_cents == 25_000_000  # $250k
    assert aet.exposed is True
    assert aet.estimated_aet_cents > 0


def test_multiple_c_corps_summed() -> None:
    corps = [
        _c_corp(name="A", amount_cents=20_000_000, shareholder_w2_wages_cents=10_000_000,
                dividends_cents=5_000_000),
        _c_corp(name="B", amount_cents=10_000_000, shareholder_w2_wages_cents=5_000_000,
                dividends_cents=2_000_000),
    ]
    out = build_corporate_analysis(
        client_tax_year_id=uuid4(), tax_year=2025, filing_status="single", state=None,
        client_name="Acme", c_corps=corps, base_inputs=Form1040Inputs(filing_status="single"),
        config=_config(),
    )
    cr = out.corporate_return
    assert cr is not None
    assert out.entity_count == 2
    # Federal corp tax = 21%·($200k + $100k) = $63,000.
    assert cr.federal_corporate_tax_cents == 6_300_000
    # Pool = ($100k + $50k) + ($50k + $20k) = $220k.
    assert out.optimization is not None
    assert out.optimization.comp_pool_cents == 22_000_000
