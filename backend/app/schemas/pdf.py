from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class BrandingIn(BaseModel):
    firm_name: str
    logo_blob_key: str | None = None
    primary_color: str = "#0f766e"
    advisor_signature: str | None = None


class PlanDocumentOut(BaseModel):
    id: UUID
    garage_key: str
    version: int
    payload_hash: str
