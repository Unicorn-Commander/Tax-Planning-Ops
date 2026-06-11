"""S-corporation reasonable-compensation split planner — tax year 2025.

An S-corp owner pays FICA on W-2 salary but not on distributions, so shifting
income from salary to distribution saves payroll tax — provided a REASONABLE
salary is paid first. This models the payroll tax at a chosen salary vs the
all-salary baseline and reports the savings, using combined employer+employee
FICA as the single-owner's economic burden.

Tradeoffs surfaced (not modeled numerically): a lower salary also shrinks the
§199A QBI base and the owner's Social Security benefit basis, and the salary
must withstand IRS reasonable-comp scrutiny. All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class SCorpConfig(BaseModel):
    tax_year: int
    ss_wage_base_cents: int  # Social Security wage base
    oasdi_rate: Decimal  # combined employer+employee
    medicare_rate: Decimal  # combined
    additional_medicare_rate: Decimal
    additional_medicare_threshold_cents: dict[str, int]


class SCorpInput(BaseModel):
    filing_status: FilingStatus
    net_business_income_cents: int
    reasonable_salary_cents: int


class PayrollComponents(BaseModel):
    ss_cents: int
    medicare_cents: int
    additional_medicare_cents: int
    total_cents: int


class SCorpResult(BaseModel):
    chosen: PayrollComponents
    baseline_all_salary: PayrollComponents
    fica_savings_cents: int
    distribution_cents: int
    tradeoffs: list[str] = Field(default_factory=list)


def _cents(value: Decimal) -> int:
    # Payroll tax lines round to whole dollars.
    return int((value / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def _payroll_tax(salary: int, config: SCorpConfig, addl_threshold: int) -> PayrollComponents:
    salary = max(salary, 0)
    ss = _cents(Decimal(min(salary, config.ss_wage_base_cents)) * config.oasdi_rate)
    medicare = _cents(Decimal(salary) * config.medicare_rate)
    addl = _cents(
        Decimal(max(salary - addl_threshold, 0)) * config.additional_medicare_rate
    )
    return PayrollComponents(
        ss_cents=ss, medicare_cents=medicare, additional_medicare_cents=addl,
        total_cents=ss + medicare + addl,
    )


def calculate_scorp_split(inputs: SCorpInput, config: SCorpConfig) -> SCorpResult:
    addl_threshold = config.additional_medicare_threshold_cents.get(
        inputs.filing_status, 20_000_000
    )
    chosen = _payroll_tax(inputs.reasonable_salary_cents, config, addl_threshold)
    baseline = _payroll_tax(inputs.net_business_income_cents, config, addl_threshold)
    distribution = max(inputs.net_business_income_cents - inputs.reasonable_salary_cents, 0)
    return SCorpResult(
        chosen=chosen,
        baseline_all_salary=baseline,
        fica_savings_cents=baseline.total_cents - chosen.total_cents,
        distribution_cents=distribution,
        tradeoffs=[
            "A lower salary reduces the §199A QBI wage base (50% of W-2 wages) and may "
            "lower the §199A wage limit for high earners.",
            "A lower salary reduces the owner's Social Security earnings record / future benefit.",
            "Salary must be defensible as reasonable compensation for services (IRS scrutiny).",
        ],
    )
