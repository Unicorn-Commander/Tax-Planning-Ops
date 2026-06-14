from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

# Reuse the firm-branding shape that pdf.py already defines for the PUT side,
# instead of duplicating it. The GET letterhead reads these same four fields
# straight off the workspace_branding row.
from app.schemas.pdf import BrandingIn

# How the advisory fee is struck. Recorded so the Present plates can phrase the
# net-of-fee framing honestly rather than implying a flat retainer.
FEE_BASES = frozenset({"flat", "aum", "hourly", "value"})


class BrandingOut(BaseModel):
    """The firm letterhead read straight from the workspace's branding row."""

    model_config = ConfigDict(from_attributes=True)

    firm_name: str
    logo_blob_key: str | None
    primary_color: str
    advisor_signature: str | None


class FeeIn(BaseModel):
    """Operator-supplied advisory fee. ``fee_cents`` is integer cents entered by
    the advisor — it is never computed by the engine."""

    fee_cents: int
    fee_basis: str = "flat"
    fee_note: str | None = None

    @field_validator("fee_basis")
    @classmethod
    def _check_basis(cls, value: str) -> str:
        if value not in FEE_BASES:
            raise ValueError(f"fee_basis must be one of {sorted(FEE_BASES)}")
        return value


class EngagementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    fee_cents: int
    fee_basis: str
    fee_note: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["BrandingIn", "BrandingOut", "EngagementOut", "FeeIn"]
