from __future__ import annotations

from pydantic import BaseModel

from app.engines.form1040 import Form1040Inputs, Form1040Result, TaxConfig, calculate_form1040


class ProjectionDelta(BaseModel):
    total_income_cents: int
    agi_cents: int
    taxable_income_cents: int
    total_tax_cents: int


class ProjectionResult(BaseModel):
    projected: Form1040Result
    delta: ProjectionDelta | None = None


def project_tax_situation(
    inputs: Form1040Inputs,
    config: TaxConfig,
    base: Form1040Result | None = None,
) -> ProjectionResult:
    projected = calculate_form1040(inputs, config)
    if base is None:
        return ProjectionResult(projected=projected)
    return ProjectionResult(
        projected=projected,
        delta=ProjectionDelta(
            total_income_cents=projected.total_income_cents - base.total_income_cents,
            agi_cents=projected.agi_cents - base.agi_cents,
            taxable_income_cents=projected.taxable_income_cents - base.taxable_income_cents,
            total_tax_cents=projected.total_tax_cents - base.total_tax_cents,
        ),
    )
