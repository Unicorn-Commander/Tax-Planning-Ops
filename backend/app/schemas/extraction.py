from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh", "qss"]


class ClientTaxYearCreate(BaseModel):
    client_id: UUID
    tax_year: int = Field(ge=1900, le=2100)
    # Only base (filed) years are created directly; plan/future years are
    # created via /plans so their 4 quarterly rows + snapshots are seeded and
    # their invariants hold. Validated as an enum to reject typos that would
    # otherwise surface as a confusing "bracket set not found" 404 at confirm.
    role: Literal["base"] = "base"
    filing_status: FilingStatus
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


class ConfirmReturnRequest(BaseModel):
    # Explicit advisor acknowledgment required to confirm a baseline that has
    # no field values at all (spec: nothing flows into the calc engine from an
    # unconfirmed/empty base without an explicit "compute anyway" ack).
    compute_anyway: bool = False


class ConfirmReturnResponse(BaseModel):
    extracted_return_id: UUID
    snapshot_id: UUID
    total_tax_cents: int
    effective_rate: str
