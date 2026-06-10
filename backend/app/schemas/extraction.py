from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClientTaxYearCreate(BaseModel):
    client_id: UUID
    tax_year: int
    role: str = "base"
    filing_status: str
    notes: str | None = None


class ClientTaxYearRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_id: UUID
    tax_year: int
    role: str
    filing_status: str
    is_locked: bool


class ExtractedFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    field_key: str
    value_cents: int | None
    value_text: str | None
    confidence: float | None
    status: str
    bbox: dict[str, Any] | None
    corrected_value_cents: int | None


class ExtractedReturnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_tax_year_id: UUID
    form_type: str
    extraction_status: str
    overall_confidence: float | None
    extraction_raw: dict[str, Any]
    fields: list[ExtractedFieldRead]


class CorrectFieldRequest(BaseModel):
    corrected_value_cents: int | None
    value_text: str | None = None


class ConfirmReturnResponse(BaseModel):
    extracted_return_id: UUID
    snapshot_id: UUID
    total_tax_cents: int
    effective_rate: str
