"""Schemas for the integrated C-corp (Form 1120) planning view.

The corporate-analysis endpoint assembles, for the C-corp entity(ies) on a
client tax year, the integrated double-tax picture: the corporation's own
return (federal 21% + state), the accumulated-earnings-tax watch, the
salary-vs-dividend split that minimises the COMBINED corporate + owner tax, and
the retained-earnings alternative. Every figure is engine-computed (the
corporate engine + the Form 1040 engine for the owner side); the schemas only
shape the output. Money is integer cents throughout.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CorporateReturn(BaseModel):
    """The C-corp's own Form 1120 tax (federal 21% + flat state), after the
    §172 NOL deduction. `effective_corporate_rate` is total corporate tax over
    pre-NOL taxable income, as a string (Decimal-faithful)."""

    pre_nol_taxable_income_cents: int
    nol_applied_cents: int
    nol_carryforward_remaining_cents: int
    corporate_taxable_income_cents: int
    federal_corporate_tax_cents: int
    state: str | None = None
    state_has_corporate_tax: bool = False
    state_corporate_tax_cents: int = 0
    state_marginal_rate: str | None = None
    total_corporate_tax_cents: int
    effective_corporate_rate: str


class AETWatch(BaseModel):
    """Accumulated-earnings-tax exposure (§531/§535): the 20% penalty on
    earnings retained beyond the $250k ($150k PSC) credit. The endpoint passes
    the corporate taxable income net of corp tax and dividends as the
    accumulated taxable income (a planning proxy — true ATI has more
    adjustments), and flags exposure rather than asserting liability."""

    accumulated_taxable_income_cents: int
    credit_cents: int
    amount_over_credit_cents: int
    estimated_aet_cents: int
    exposed: bool
    is_psc: bool = False
    note: str


class DoubleTax(BaseModel):
    """The double tax at the CURRENT (stored) salary/dividend split: the corp's
    own tax plus the owner's personal tax on salary (ordinary + payroll) and
    dividends (qualified). `retained_earnings_cents` is what stays in the corp
    after corp tax and dividends — the alternative to distributing."""

    owner_salary_cents: int
    owner_dividends_cents: int
    corporate_tax_cents: int  # federal + state
    owner_personal_tax_cents: int  # incremental 1040 tax on salary + dividends
    owner_payroll_tax_cents: int  # employee-side FICA on the salary
    integrated_total_tax_cents: int
    retained_earnings_cents: int


class SplitPoint(BaseModel):
    """One point on the salary-vs-dividend optimization curve. Every tax figure
    is engine-computed for THIS split; `integrated_total_tax_cents` is the value
    the optimizer minimises."""

    salary_cents: int
    dividends_cents: int
    corporate_taxable_income_cents: int
    corporate_tax_cents: int  # federal + state on this split
    owner_personal_tax_cents: int  # incremental 1040 tax on salary + dividends
    owner_payroll_tax_cents: int  # employee-side FICA on the salary
    integrated_total_tax_cents: int


class SalaryDividendOptimization(BaseModel):
    """The swept split curve + the integrated-tax-minimising point. The owner
    compensation pool (salary + dividends) is held constant across the sweep so
    the comparison is apples-to-apples; the only choice is how to label each
    dollar pulled out. The optimum is the real minimum of the engine-computed
    `integrated_total_tax_cents`, not a heuristic."""

    comp_pool_cents: int
    current_salary_cents: int
    current_dividends_cents: int
    optimal_salary_cents: int
    optimal_dividends_cents: int
    optimal_integrated_total_tax_cents: int
    current_integrated_total_tax_cents: int
    savings_vs_current_cents: int
    step_cents: int
    curve: list[SplitPoint]
    assumptions: list[str] = Field(default_factory=list)


class CorporateAnalysis(BaseModel):
    """The integrated 1120 planning picture for the C-corp(s) on a tax year.

    When several C-corp entities are present the figures are summed at the
    corporate level and the optimization runs on the combined pool; `entities`
    lists the contributing rows. `available` is False with a `reason` when there
    is no C-corp on the year (the GUI shows an honest empty state)."""

    available: bool = True
    reason: str | None = None
    client_tax_year_id: str
    client_name: str | None = None
    tax_year: int
    state: str | None = None
    entity_count: int = 0
    entities: list[str] = Field(default_factory=list)
    corporate_return: CorporateReturn | None = None
    aet: AETWatch | None = None
    double_tax: DoubleTax | None = None
    optimization: SalaryDividendOptimization | None = None
    assumptions: list[str] = Field(default_factory=list)
