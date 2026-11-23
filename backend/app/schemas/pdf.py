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
    # Kept: the frontend fetches the rendered PDF from Garage by this key
    # (frontend/app/(app)/clients/[clientId]/pdf/page.tsx, (v3)/.../plan/page.tsx).
    # It is scope-safe: server-generated as `{workspace_id}/...` and the listing
    # is RLS-scoped to the caller's workspace, so it can only ever name the
    # caller's own objects.
    garage_key: str
    version: int
    payload_hash: str
