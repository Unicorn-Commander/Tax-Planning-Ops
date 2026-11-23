"""T2 (ea4d1636): branding logo_blob_key must live under the caller's prefix.

logo_blob_key (PUT /api/v1/admin/branding) is caller-supplied and rendered
from the SHARED Garage bucket, so a key naming another workspace's object made
the other tenant's file render into this workspace's PDFs. Pinned: another
workspace's key is refused (ValueError → 422 at the route) with nothing
written; the caller's own key passes; None passes.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.pdf import put_branding
from app.schemas.auth import AuthContext
from app.schemas.pdf import BrandingIn
from app.services.pdf import check_logo_blob_key_scope, upsert_branding

WS = uuid4()
WS_OTHER = uuid4()


def test_own_prefix_ok_other_prefix_refused() -> None:
    check_logo_blob_key_scope(WS, f"{WS}/branding/logo.png")  # own: no raise
    check_logo_blob_key_scope(WS, None)  # unset: no raise
    with pytest.raises(ValueError):
        check_logo_blob_key_scope(WS, f"{WS_OTHER}/branding/logo.png")
    with pytest.raises(ValueError):
        check_logo_blob_key_scope(WS, "branding/logo.png")  # no prefix at all
    with pytest.raises(ValueError):
        # prefix-spoof: "ws-x-evil/" is NOT the workspace prefix
        check_logo_blob_key_scope(WS, f"{WS}-evil/logo.png")


class _ExplodingDb:
    """Any use fails the test: a refused key must be rejected BEFORE writes."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"db.{name} must not be touched")


def _ctx() -> AuthContext:
    return AuthContext(
        claims={}, uc_uid="fictional-admin", workspace_id=WS,
        authorized_workspace_ids={WS}, scopes={"taxplan:admin"},
    )


@pytest.mark.asyncio
async def test_put_branding_route_422_for_foreign_key() -> None:
    payload = BrandingIn(firm_name="Fictional Birch Advisors", logo_blob_key=f"{WS_OTHER}/l.png")
    with pytest.raises(HTTPException) as exc:
        await put_branding(payload, _ctx(), _ExplodingDb())  # type: ignore[arg-type]
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_branding_refuses_foreign_key_before_db() -> None:
    payload = BrandingIn(firm_name="Fictional Birch Advisors", logo_blob_key=f"{WS_OTHER}/l.png")
    with pytest.raises(ValueError):
        await upsert_branding(_ExplodingDb(), workspace_id=WS, payload=payload)  # type: ignore[arg-type]
