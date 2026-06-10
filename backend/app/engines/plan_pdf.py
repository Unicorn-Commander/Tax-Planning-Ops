from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

DISCLAIMER = (
    "Planning estimate only. Not a filed tax return and not tax advice. Figures are "
    "projections based on advisor-entered assumptions and editable bracket tables."
)


class BrandingPayload(BaseModel):
    firm_name: str
    logo_blob_key: str | None = None
    primary_color: str = "#0f766e"
    advisor_signature: str | None = None


class PlanPdfPayload(BaseModel):
    branding: BrandingPayload
    client_name: str
    tax_year: int
    current: dict[str, Any]
    next_year: dict[str, Any]
    strategies: list[dict[str, Any]] = Field(default_factory=list)
    quarterly: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    footnotes: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def assemble_plan_pdf_payload(
    *,
    branding: BrandingPayload,
    client_name: str,
    tax_year: int,
    current: dict[str, Any],
    next_year: dict[str, Any],
    strategies: list[dict[str, Any]],
    quarterly: list[dict[str, Any]],
    has_manual_override: bool,
    bracket_provenance: str,
) -> PlanPdfPayload:
    footnotes = [f"Bracket/config provenance: {bracket_provenance}."]
    if has_manual_override:
        footnotes.append("Manual overrides are flagged and included in the displayed estimates.")
    return PlanPdfPayload(
        branding=branding,
        client_name=client_name,
        tax_year=tax_year,
        current=current,
        next_year=next_year,
        strategies=strategies,
        quarterly=quarterly,
        footnotes=footnotes,
    )
