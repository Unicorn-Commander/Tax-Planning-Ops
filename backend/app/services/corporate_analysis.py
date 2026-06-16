"""Integrated C-corporation (Form 1120) planning analysis for a tax year.

A C-corp pays its OWN tax (flat federal 21% + a flat state rate, after the §172
NOL deduction); the owner is taxed AGAIN on the salary it deducts (1040 wages,
ordinary + payroll) and on the dividends it can't deduct (qualified dividends) —
the double tax. This service reads the C-corp entity row(s) on a client tax
year, runs the corporate engine for the corporate-level tax + AET watch, and
runs the Form 1040 engine on the owner side to find the salary/dividend split
that minimises the COMBINED corporate + owner tax.

Everything is engine-computed: the corporate tax/NOL/AET come from
`app.engines.corporate`; the owner's incremental personal tax comes from
`app.engines.form1040` (run on the client's real 1040 base + the C-corp pieces,
so the marginal rate is the owner's actual marginal rate, not a flat guess); the
owner's payroll is the employee-side FICA from the SE/S-corp constants. The
optimizer returns the real minimum of the engine-computed integrated total over
a swept range — never a heuristic or fabricated figure.

Pure-compute helpers (`build_corporate_analysis`) take already-loaded inputs so
they can be golden-tested without a DB; the DB entry point loads the tax year,
client, snapshot, and bracket set and delegates to them.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.corporate import (
    AETInput,
    CorporateConfig,
    CorporateTaxInput,
    StateCorporateConfig,
    calculate_aet,
    calculate_corporate_tax,
    calculate_state_corporate_tax,
)
from app.engines.form1040 import Form1040Inputs, TaxConfig, calculate_form1040
from app.engines.scorp import SCorpConfig
from app.models.client import Client
from app.models.entity import BusinessEntity
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.schemas.corporate import (
    AETWatch,
    CorporateAnalysis,
    CorporateReturn,
    CorporateSource,
    DoubleTax,
    SalaryDividendOptimization,
    SplitPoint,
)
from app.services.entities import list_entities
from app.services.tax_config import resolve_bracket_set, to_engine_config
from app.year_configs import (
    corporate_config_for,
    scorp_config_for,
    state_corporate_config_for,
)

# Number of sweep points across the comp pool. 41 → ~2.5% granularity, fine
# enough to land on the integrated-tax minimum without an expensive sweep.
_SWEEP_POINTS = 41


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _employee_fica_cents(salary_cents: int, scorp_cfg: SCorpConfig, filing_status: str) -> int:
    """Employee-side FICA on a C-corp owner's W-2 salary.

    The S-corp/SE configs store the COMBINED employer+employee OASDI and
    Medicare rates, so the employee share is half of each; the 0.9% Additional
    Medicare Tax is employee-only (no employer match), applied above the
    filing-status threshold. Rounds each line to whole dollars (payroll
    convention). This is the owner's own payroll cost of taking salary instead
    of a dividend — the employer half is a separate corporate cost not modelled
    in this simplified pool."""
    salary = max(salary_cents, 0)
    half = Decimal("0.5")
    oasdi = _round_cents(
        Decimal(min(salary, scorp_cfg.ss_wage_base_cents)) * scorp_cfg.oasdi_rate * half
    )
    medicare = _round_cents(Decimal(salary) * scorp_cfg.medicare_rate * half)
    threshold = scorp_cfg.additional_medicare_threshold_cents.get(filing_status, 20_000_000)
    addl = _round_cents(
        Decimal(max(salary - threshold, 0)) * scorp_cfg.additional_medicare_rate
    )
    return oasdi + medicare + addl


def _owner_personal_tax_cents(
    base_inputs: Form1040Inputs,
    config: TaxConfig,
    *,
    salary_cents: int,
    dividends_cents: int,
) -> int:
    """Incremental owner 1040 income tax from adding `salary_cents` to wages and
    `dividends_cents` to (qualified + ordinary) dividends, computed on the
    client's real return base so the marginal stacking is correct.

    Returns the DELTA over the base return's tax (the owner-side cost of the
    C-corp compensation), engine-computed twice and differenced. Never negative
    (a loss base can't make the C-corp pieces tax-negative here)."""
    base = calculate_form1040(base_inputs, config)
    withed = calculate_form1040(
        base_inputs.model_copy(
            update={
                "wages_cents": base_inputs.wages_cents + max(salary_cents, 0),
                "qualified_dividends_cents": (
                    base_inputs.qualified_dividends_cents + max(dividends_cents, 0)
                ),
                "ordinary_dividends_cents": (
                    base_inputs.ordinary_dividends_cents + max(dividends_cents, 0)
                ),
            }
        ),
        config,
    )
    return max(withed.total_tax_cents - base.total_tax_cents, 0)


def _corporate_tax_for(
    pre_nol_taxable_income_cents: int,
    nol_available_cents: int,
    corp_cfg: CorporateConfig,
    state_corp_cfg: StateCorporateConfig | None,
) -> tuple[int, int, int, int, int]:
    """Run the corporate engine for a given pre-NOL taxable income.

    Returns (federal_tax, state_tax, corporate_taxable_income, nol_applied,
    nol_remaining). State tax is on the SAME post-NOL corporate taxable income
    (a flat-rate planning approximation; true state taxable income has its own
    modifications + apportionment)."""
    corp = calculate_corporate_tax(
        CorporateTaxInput(
            pre_nol_taxable_income_cents=pre_nol_taxable_income_cents,
            nol_available_cents=nol_available_cents,
        ),
        corp_cfg,
    )
    state_tax = 0
    if state_corp_cfg is not None:
        state = calculate_state_corporate_tax(
            corp.corporate_taxable_income_cents, state_corp_cfg
        )
        state_tax = state.state_corporate_tax_cents
    return (
        corp.corporate_tax_cents,
        state_tax,
        corp.corporate_taxable_income_cents,
        corp.nol_deduction_cents,
        corp.nol_carryforward_remaining_cents,
    )


def _optimize_split(
    *,
    pre_salary_operating_income_cents: int,
    comp_pool_cents: int,
    nol_available_cents: int,
    current_salary_cents: int,
    current_dividends_cents: int,
    base_inputs: Form1040Inputs,
    config: TaxConfig,
    corp_cfg: CorporateConfig,
    state_corp_cfg: StateCorporateConfig | None,
    scorp_cfg: SCorpConfig,
    filing_status: str,
) -> SalaryDividendOptimization:
    """Sweep salary ∈ [0, comp_pool] (dividends = pool − salary) and return the
    curve + the integrated-tax-minimising point.

    For each candidate salary the corp's pre-NOL taxable income is
    `pre_salary_operating_income − salary` (salary is deductible), so more salary
    lowers corp tax but adds owner ordinary income + payroll; dividends are not
    deductible (double-taxed) but carry no payroll. The minimum is the real
    argmin of the engine-computed integrated total."""
    pool = max(comp_pool_cents, 0)
    step = max(pool // (_SWEEP_POINTS - 1), 1) if pool > 0 else 1

    def integrated_at(salary: int) -> SplitPoint:
        salary = max(min(salary, pool), 0)
        dividends = pool - salary
        fed, state, corp_ti, _applied, _rem = _corporate_tax_for(
            pre_salary_operating_income_cents - salary,
            nol_available_cents,
            corp_cfg,
            state_corp_cfg,
        )
        corp_tax = fed + state
        owner_income_tax = _owner_personal_tax_cents(
            base_inputs, config, salary_cents=salary, dividends_cents=dividends
        )
        payroll = _employee_fica_cents(salary, scorp_cfg, filing_status)
        return SplitPoint(
            salary_cents=salary,
            dividends_cents=dividends,
            corporate_taxable_income_cents=corp_ti,
            corporate_tax_cents=corp_tax,
            owner_personal_tax_cents=owner_income_tax,
            owner_payroll_tax_cents=payroll,
            integrated_total_tax_cents=corp_tax + owner_income_tax + payroll,
        )

    # Build the swept grid, then ensure the endpoints and the current split are
    # represented so the optimum is never missed at a boundary.
    salaries: set[int] = {min(i * step, pool) for i in range(_SWEEP_POINTS)}
    salaries.update({0, pool, max(min(current_salary_cents, pool), 0)})
    curve = [integrated_at(s) for s in sorted(salaries)]

    best = min(curve, key=lambda p: p.integrated_total_tax_cents)
    current = integrated_at(max(min(current_salary_cents, pool), 0))

    assumptions = [
        "Owner compensation pool (salary + dividends) held constant across the sweep; "
        "the only variable is how each dollar pulled out is labelled.",
        "More salary is deductible to the corp (lowers the 21% + state corporate tax) but "
        "is ordinary income + employee FICA to the owner; dividends are not deductible "
        "(double-taxed) but carry no payroll.",
        "Owner income tax is the incremental Form 1040 tax on the client's real return base "
        "(actual marginal rate); payroll is employee-side FICA (the employer half is a "
        "separate corporate cost not modelled in this pool).",
        "Reasonable-compensation rules (IRC §162) require salary to be defensible for "
        "services rendered; a low-salary optimum may not survive IRS scrutiny.",
    ]
    return SalaryDividendOptimization(
        comp_pool_cents=pool,
        current_salary_cents=current_salary_cents,
        current_dividends_cents=current_dividends_cents,
        optimal_salary_cents=best.salary_cents,
        optimal_dividends_cents=best.dividends_cents,
        optimal_integrated_total_tax_cents=best.integrated_total_tax_cents,
        current_integrated_total_tax_cents=current.integrated_total_tax_cents,
        savings_vs_current_cents=(
            current.integrated_total_tax_cents - best.integrated_total_tax_cents
        ),
        step_cents=step,
        curve=curve,
        assumptions=assumptions,
    )


def build_corporate_analysis(
    *,
    client_tax_year_id: UUID,
    tax_year: int,
    filing_status: str,
    state: str | None,
    client_name: str | None,
    c_corps: list[BusinessEntity],
    base_inputs: Form1040Inputs,
    config: TaxConfig,
) -> CorporateAnalysis:
    """Assemble the integrated 1120 picture from already-loaded inputs (pure
    compute; no DB). When several C-corps are present the corporate figures are
    summed and the optimization runs on the combined pool."""
    if not c_corps:
        return CorporateAnalysis(
            available=False,
            reason="No C-corporation entity on this tax year.",
            client_tax_year_id=str(client_tax_year_id),
            client_name=client_name,
            tax_year=tax_year,
            state=state,
            entity_count=0,
        )

    corp_cfg = corporate_config_for(tax_year)
    scorp_cfg = scorp_config_for(tax_year)
    state_corp_cfg = (
        state_corporate_config_for(state.upper(), tax_year) if state else None
    )

    # --- Corporate return: sum the per-entity engine results -----------------
    pre_nol_total = 0
    corp_ti_total = 0
    fed_total = 0
    state_total = 0
    nol_applied_total = 0
    nol_remaining_total = 0
    # The owner-compensation pool (current salary + current dividends) and the
    # pre-salary operating income (corp taxable income + the salary already
    # deducted from it) that the sweep re-derives the corp tax from.
    current_salary_total = 0
    current_dividends_total = 0
    pre_salary_operating_income_total = 0
    nol_available_total = 0
    book_income_total = 0  # raw synced BOOK net income (AO-linked entities)
    adjustment_total = 0  # net Schedule M-1 book-to-tax adjustment
    ao_synced_ats: list[Any] = []
    for e in c_corps:
        # amount_cents is BOOK net income when synced from AO; the M-1 adjustment
        # reconciles it to corporate taxable income (pre-NOL).
        pre_nol = e.amount_cents + (e.book_to_tax_adjustment_cents or 0)
        fed, state_tax, corp_ti, nol_applied, nol_rem = _corporate_tax_for(
            pre_nol, e.nol_available_cents, corp_cfg, state_corp_cfg
        )
        pre_nol_total += max(pre_nol, 0)
        corp_ti_total += corp_ti
        fed_total += fed
        state_total += state_tax
        nol_applied_total += nol_applied
        nol_remaining_total += nol_rem
        current_salary_total += e.shareholder_w2_wages_cents
        current_dividends_total += e.dividends_cents
        # pre-NOL taxable income is AFTER the owner's salary deduction, so
        # pre-salary operating income adds the salary back.
        pre_salary_operating_income_total += pre_nol + e.shareholder_w2_wages_cents
        nol_available_total += e.nol_available_cents
        adjustment_total += e.book_to_tax_adjustment_cents or 0
        if e.accounting_ops_workspace_id:
            book_income_total += e.amount_cents
            if e.accounting_ops_synced_at is not None:
                ao_synced_ats.append(e.accounting_ops_synced_at)

    total_corp_tax = fed_total + state_total
    eff_rate = (
        Decimal(total_corp_tax) / Decimal(pre_nol_total)
        if pre_nol_total > 0
        else Decimal("0")
    )
    corporate_return = CorporateReturn(
        pre_nol_taxable_income_cents=pre_nol_total,
        book_to_tax_adjustment_cents=adjustment_total,
        nol_applied_cents=nol_applied_total,
        nol_carryforward_remaining_cents=nol_remaining_total,
        corporate_taxable_income_cents=corp_ti_total,
        federal_corporate_tax_cents=fed_total,
        state=state,
        state_has_corporate_tax=state_corp_cfg is not None,
        state_corporate_tax_cents=state_total,
        state_marginal_rate=(
            str(state_corp_cfg.corporate_rate) if state_corp_cfg is not None else None
        ),
        total_corporate_tax_cents=total_corp_tax,
        effective_corporate_rate=str(eff_rate),
    )

    # --- AET watch: ATI proxy = corporate taxable income − corp tax − dividends
    accumulated_ti = max(corp_ti_total - total_corp_tax - current_dividends_total, 0)
    aet_res = calculate_aet(
        AETInput(accumulated_taxable_income_cents=accumulated_ti, is_psc=False),
        corp_cfg,
    )
    aet = AETWatch(
        accumulated_taxable_income_cents=accumulated_ti,
        credit_cents=aet_res.credit_cents,
        amount_over_credit_cents=aet_res.accumulated_taxable_income_over_credit_cents,
        estimated_aet_cents=aet_res.estimated_aet_cents,
        exposed=aet_res.exposed,
        is_psc=False,
        note=(
            "Accumulated taxable income is approximated as corporate taxable income less "
            "corporate tax less dividends paid; the $250k credit ($150k for a personal "
            "service corporation) shelters reasonable retained earnings. This flags "
            "exposure, not a §531 liability — the tax applies only to earnings retained "
            "beyond the reasonable needs of the business."
        ),
    )

    # --- The double tax at the CURRENT split ---------------------------------
    owner_income_tax = _owner_personal_tax_cents(
        base_inputs,
        config,
        salary_cents=current_salary_total,
        dividends_cents=current_dividends_total,
    )
    owner_payroll = _employee_fica_cents(current_salary_total, scorp_cfg, filing_status)
    retained_earnings = corp_ti_total - total_corp_tax - current_dividends_total
    double_tax = DoubleTax(
        owner_salary_cents=current_salary_total,
        owner_dividends_cents=current_dividends_total,
        corporate_tax_cents=total_corp_tax,
        owner_personal_tax_cents=owner_income_tax,
        owner_payroll_tax_cents=owner_payroll,
        integrated_total_tax_cents=total_corp_tax + owner_income_tax + owner_payroll,
        retained_earnings_cents=retained_earnings,
    )

    # --- Salary vs dividend optimization -------------------------------------
    optimization = _optimize_split(
        pre_salary_operating_income_cents=pre_salary_operating_income_total,
        comp_pool_cents=current_salary_total + current_dividends_total,
        nol_available_cents=nol_available_total,
        current_salary_cents=current_salary_total,
        current_dividends_cents=current_dividends_total,
        base_inputs=base_inputs,
        config=config,
        corp_cfg=corp_cfg,
        state_corp_cfg=state_corp_cfg,
        scorp_cfg=scorp_cfg,
        filing_status=filing_status,
    )

    assumptions = [
        f"Federal corporate tax is a flat {corp_cfg.corporate_rate:.0%} on corporate "
        "taxable income after the §172 NOL deduction (80% of pre-NOL income limit).",
    ]
    if state_corp_cfg is not None:
        assumptions.append(
            f"State ({state}) corporate tax is a flat {state_corp_cfg.corporate_rate} on the "
            "post-NOL corporate taxable income (a planning approximation of state taxable "
            "income, which has its own modifications and apportionment)."
        )
    elif state:
        assumptions.append(
            f"State '{state}' has no modelled corporate income tax (federal-only corporate tax)."
        )

    # --- Source/provenance: book-vs-tax + freshness ("the honest notes") -----
    ao_linked = [e for e in c_corps if e.accounting_ops_workspace_id]
    source: CorporateSource | None = None
    if ao_linked:
        latest = max(ao_synced_ats) if ao_synced_ats else None
        source = CorporateSource(
            from_accounting_ops=True,
            synced_at=latest.isoformat() if latest is not None else None,
            period=str(tax_year),
            book_net_income_cents=book_income_total,
        )
        if adjustment_total:
            assumptions.append(
                "Corporate taxable income = the BOOK net income sourced from "
                "Accounting-Ops PLUS your Schedule M-1 book-to-tax adjustment. Book-tax "
                "differences beyond that net adjustment (50% meals, federal tax per books, "
                "book-vs-tax depreciation, tax-exempt income) are not auto-computed."
            )
        else:
            assumptions.append(
                "Corporate taxable income here is the BOOK net income sourced from "
                "Accounting-Ops, used AS-IS — no Schedule M-1 book-to-tax adjustment is "
                "set yet. Book income ≠ taxable income (50% meals, federal tax per books, "
                "book-vs-tax depreciation, …); enter the net M-1 adjustment to reconcile."
            )
        if source.synced_at:
            assumptions.append(
                f"Books synced from Accounting-Ops on {source.synced_at[:10]} for period "
                f"{source.period}; they are maintained externally and may still be in "
                "reconciliation — re-sync to refresh the figure."
            )

    return CorporateAnalysis(
        available=True,
        client_tax_year_id=str(client_tax_year_id),
        client_name=client_name,
        tax_year=tax_year,
        state=state,
        entity_count=len(c_corps),
        entities=[e.name or "(unnamed C-corp)" for e in c_corps],
        corporate_return=corporate_return,
        aet=aet,
        double_tax=double_tax,
        optimization=optimization,
        source=source,
        assumptions=assumptions,
    )


async def get_corporate_analysis(
    db: AsyncSession,
    *,
    tax_year_id: UUID,
) -> dict[str, Any]:
    """DB entry point: load the tax year, client, latest snapshot, and bracket
    set, then build the integrated 1120 analysis. Raises LookupError (→404) when
    the tax year, snapshot, or bracket set is missing."""
    tax_year = await db.get(ClientTaxYear, tax_year_id)
    if tax_year is None:
        raise LookupError("client tax year not found")
    client = await db.get(Client, tax_year.client_id)

    entities = await list_entities(db, client_tax_year_id=tax_year_id)
    c_corps = [e for e in entities if e.kind == "c_corp"]

    # The owner side needs the client's real 1040 base; fall back to an empty
    # base (still engine-computed, marginal rate from $0) when no snapshot
    # exists yet — but a C-corp owner virtually always has a snapshot.
    snapshot: TaxSituationSnapshot | None = await db.scalar(
        select(TaxSituationSnapshot)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    base_dict = dict(snapshot.inputs) if snapshot else {}
    base_inputs = Form1040Inputs(**{**base_dict, "filing_status": tax_year.filing_status})

    bracket_set = await resolve_bracket_set(
        db, tax_year=tax_year.tax_year, filing_status=tax_year.filing_status
    )
    if bracket_set is None:
        raise LookupError("no bracket set for this tax year/filing status")
    config = to_engine_config(bracket_set)

    analysis = build_corporate_analysis(
        client_tax_year_id=tax_year_id,
        tax_year=tax_year.tax_year,
        filing_status=tax_year.filing_status,
        state=client.primary_state if client else None,
        client_name=client.display_name if client else None,
        c_corps=c_corps,
        base_inputs=base_inputs,
        config=config,
    )
    return analysis.model_dump(mode="json")
