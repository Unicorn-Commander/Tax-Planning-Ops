"""Multi-year tax projection + scenario recompute.

Two capabilities, both built ONLY on the existing federal engine
(`calculate_form1040`) so they inherit its correctness:

  * `recompute_scenario` — apply a set of input mutations (absolute sets and/or
    signed deltas) to a base situation, re-run the engine, and return the REAL
    before/after tax delta. This replaces the flat `amount × effective_rate`
    estimate for strategies whose effect is structural (a 401(k) deferral lowers
    AGI, which can cross brackets, change QBI headroom, NIIT exposure, etc.).

  * `project_multi_year` — roll a base year forward N years, inflation-indexing
    the brackets the law actually indexes (ordinary brackets, standard
    deduction, LTCG breakpoints) while holding statutorily-fixed thresholds
    (NIIT §1411, Additional Medicare §3101) constant, growing income by an
    assumed rate, and evaluating one or more NAMED scenarios against the
    baseline. A seeded real config for a future year always wins over indexing.

All money is integer cents. Every assumption the projection makes is surfaced.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.engines.form1040 import (
    AuxiliaryConfig,
    Form1040Inputs,
    Form1040Result,
    RateBracket,
    TaxConfig,
    calculate_form1040,
)

# Income fields that grow with the assumed income-growth rate. Deduction/credit
# and capital fields are intentionally excluded — they are driven by scenario
# mutations or the indexed config, not blanket income growth.
_GROWTH_FIELDS = (
    "wages_cents",
    "taxable_interest_cents",
    "ordinary_dividends_cents",
    "qualified_dividends_cents",
    "ira_taxable_cents",
    "pensions_taxable_cents",
    "schedule_1_income_cents",
)

# IRS indexes most dollar amounts to the nearest $50 (5_000 cents). LTCG
# breakpoints round to the nearest $50 as well.
_IRS_ROUND_CENTS = 5_000


def _round_to(value: int, step: int) -> int:
    if step <= 0:
        return value
    return int(round(value / step)) * step


def _grow(value: int, factor: Decimal) -> int:
    return int((Decimal(value) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Scenario recompute (real before/after through the engine)
# ---------------------------------------------------------------------------


class InputMutation(BaseModel):
    """A structural change to a tax situation.

    `set_fields` overwrite a field absolutely; `delta_fields` add a signed
    amount (cents) to the current value. Deltas compose; unknown field names are
    rejected so a typo can't silently no-op a strategy."""

    set_fields: dict[str, int] = Field(default_factory=dict)
    delta_fields: dict[str, int] = Field(default_factory=dict)

    def apply(self, inputs: Form1040Inputs) -> Form1040Inputs:
        data = inputs.model_dump()
        for key, value in self.set_fields.items():
            if key not in data:
                raise KeyError(f"unknown input field for mutation set: {key}")
            data[key] = value
        for key, value in self.delta_fields.items():
            if key not in data:
                raise KeyError(f"unknown input field for mutation delta: {key}")
            base = data[key]
            if not isinstance(base, int):
                raise TypeError(f"cannot apply a delta to non-integer field: {key}")
            data[key] = base + value
        return Form1040Inputs(**data)


class ScenarioRecompute(BaseModel):
    base: Form1040Result
    scenario: Form1040Result
    tax_delta_cents: int  # scenario.total_tax - base.total_tax (negative = savings)
    agi_delta_cents: int
    taxable_income_delta_cents: int
    marginal_rate_base: Decimal
    marginal_rate_scenario: Decimal


def recompute_scenario(
    base_inputs: Form1040Inputs,
    config: TaxConfig,
    mutation: InputMutation,
    *,
    base_result: Form1040Result | None = None,
) -> ScenarioRecompute:
    """Re-run the engine with the mutation applied; return the real delta."""
    base = base_result or calculate_form1040(base_inputs, config)
    scenario = calculate_form1040(mutation.apply(base_inputs), config)
    return ScenarioRecompute(
        base=base,
        scenario=scenario,
        tax_delta_cents=scenario.total_tax_cents - base.total_tax_cents,
        agi_delta_cents=scenario.agi_cents - base.agi_cents,
        taxable_income_delta_cents=scenario.taxable_income_cents - base.taxable_income_cents,
        marginal_rate_base=base.marginal_rate,
        marginal_rate_scenario=scenario.marginal_rate,
    )


# ---------------------------------------------------------------------------
# Inflation indexing of a TaxConfig
# ---------------------------------------------------------------------------


def index_config(base: TaxConfig, years_forward: int, annual_rate: Decimal) -> TaxConfig:
    """Project a config `years_forward` years using `annual_rate`, indexing only
    what the Code indexes. NIIT and Additional Medicare thresholds are NOT
    inflation-adjusted by statute, so they are carried forward unchanged."""
    if years_forward <= 0:
        return base
    factor = (Decimal(1) + annual_rate) ** years_forward

    def idx_bracket(b: RateBracket) -> RateBracket:
        return RateBracket(
            lower_bound_cents=_round_to(_grow(b.lower_bound_cents, factor), _IRS_ROUND_CENTS),
            upper_bound_cents=(
                None
                if b.upper_bound_cents is None
                else _round_to(_grow(b.upper_bound_cents, factor), _IRS_ROUND_CENTS)
            ),
            rate=b.rate,
        )

    aux = base.auxiliary
    indexed_aux = AuxiliaryConfig(
        ltcg_brackets=[idx_bracket(b) for b in aux.ltcg_brackets],
        # Statutorily fixed — carried forward, NOT indexed.
        niit_threshold_cents=aux.niit_threshold_cents,
        niit_rate=aux.niit_rate,
        additional_medicare_threshold_cents=aux.additional_medicare_threshold_cents,
        additional_medicare_rate=aux.additional_medicare_rate,
        capital_loss_limit_cents=aux.capital_loss_limit_cents,
        qbi_limit_rate=aux.qbi_limit_rate,
    )
    return TaxConfig(
        tax_year=base.tax_year + years_forward,
        filing_status=base.filing_status,
        standard_deduction_cents=_round_to(
            _grow(base.standard_deduction_cents, factor), _IRS_ROUND_CENTS
        ),
        ordinary_brackets=[idx_bracket(b) for b in base.ordinary_brackets],
        auxiliary=indexed_aux,
    )


# ---------------------------------------------------------------------------
# Multi-year projection with named scenarios
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """A named what-if. `mutations_by_offset` maps a year offset (0 = base year,
    1 = next year, …) to the structural change applied in/after that year. A
    mutation persists from the offset it is introduced through the horizon
    (deltas re-apply each year on the grown baseline; sets pin the field)."""

    name: str
    mutations_by_offset: dict[int, InputMutation] = Field(default_factory=dict)


class ProjectedYear(BaseModel):
    tax_year: int
    offset: int
    total_income_cents: int
    agi_cents: int
    taxable_income_cents: int
    total_tax_cents: int
    marginal_rate: Decimal
    effective_rate: Decimal
    config_source: str  # "seeded" | "indexed"
    assumptions: list[str] = Field(default_factory=list)


class ScenarioProjection(BaseModel):
    name: str
    years: list[ProjectedYear]
    cumulative_tax_cents: int
    cumulative_tax_delta_vs_baseline_cents: int  # negative = total savings


class MultiYearInput(BaseModel):
    base_year: int
    base_inputs: Form1040Inputs
    base_config: TaxConfig
    horizon_years: int = 5  # number of years projected INCLUDING the base year
    inflation_rate: Decimal = Decimal("0.025")
    income_growth_rate: Decimal = Decimal("0.03")
    seeded_configs: dict[int, TaxConfig] = Field(default_factory=dict)
    scenarios: list[Scenario] = Field(default_factory=list)


class MultiYearResult(BaseModel):
    baseline: ScenarioProjection
    scenarios: list[ScenarioProjection]
    assumptions: list[str] = Field(default_factory=list)


def _config_for_offset(payload: MultiYearInput, offset: int) -> tuple[TaxConfig, str]:
    year = payload.base_year + offset
    seeded = payload.seeded_configs.get(year)
    if seeded is not None:
        return seeded, "seeded"
    if offset == 0:
        return payload.base_config, "seeded"
    return index_config(payload.base_config, offset, payload.inflation_rate), "indexed"


def _grown_inputs(base: Form1040Inputs, offset: int, growth_rate: Decimal) -> Form1040Inputs:
    if offset == 0 or growth_rate == 0:
        return base
    factor = (Decimal(1) + growth_rate) ** offset
    data = base.model_dump()
    for field in _GROWTH_FIELDS:
        data[field] = _grow(data[field], factor)
    return Form1040Inputs(**data)


def _run_scenario(
    payload: MultiYearInput,
    scenario: Scenario | None,
    baseline_tax_by_offset: list[int] | None,
) -> ScenarioProjection:
    years: list[ProjectedYear] = []
    cumulative = 0
    # A mutation introduced at offset k applies from k through the horizon.
    active: list[InputMutation] = []
    for offset in range(payload.horizon_years):
        config, source = _config_for_offset(payload, offset)
        inputs = _grown_inputs(payload.base_inputs, offset, payload.income_growth_rate)
        if scenario is not None and offset in scenario.mutations_by_offset:
            active.append(scenario.mutations_by_offset[offset])
        for mutation in active:
            inputs = mutation.apply(inputs)
        result = calculate_form1040(inputs, config)
        cumulative += result.total_tax_cents
        years.append(
            ProjectedYear(
                tax_year=payload.base_year + offset,
                offset=offset,
                total_income_cents=result.total_income_cents,
                agi_cents=result.agi_cents,
                taxable_income_cents=result.taxable_income_cents,
                total_tax_cents=result.total_tax_cents,
                marginal_rate=result.marginal_rate,
                effective_rate=result.effective_rate,
                config_source=source,
                assumptions=result.assumptions,
            )
        )
    baseline_total = sum(baseline_tax_by_offset) if baseline_tax_by_offset else cumulative
    return ScenarioProjection(
        name=scenario.name if scenario else "baseline",
        years=years,
        cumulative_tax_cents=cumulative,
        cumulative_tax_delta_vs_baseline_cents=cumulative - baseline_total,
    )


def project_multi_year(payload: MultiYearInput) -> MultiYearResult:
    if payload.horizon_years < 1:
        raise ValueError("horizon_years must be >= 1")
    baseline = _run_scenario(payload, None, None)
    baseline_tax = [y.total_tax_cents for y in baseline.years]
    scenarios = [_run_scenario(payload, s, baseline_tax) for s in payload.scenarios]
    assumptions = [
        f"income_growth_rate={payload.income_growth_rate} applied to wages/interest/"
        "dividends/IRA/pension/Sch-1 income",
        f"inflation_rate={payload.inflation_rate} indexes ordinary brackets, standard "
        "deduction, and LTCG breakpoints for years without a seeded config",
        "NIIT and Additional Medicare thresholds held fixed (not inflation-indexed by law)",
    ]
    return MultiYearResult(baseline=baseline, scenarios=scenarios, assumptions=assumptions)
