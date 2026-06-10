from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClientCreate(BaseModel):
    display_name: str
    filing_status_default: str = "single"
    primary_state: str | None = None
    external_ref: str | None = None
    notes: str | None = None


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    display_name: str
    filing_status_default: str
    primary_state: str | None
    status: str
    external_ref: str | None
    notes: str | None
