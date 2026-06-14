"""Opt-in demo data controls.

The sample "Sample Firm (demo)" book is something an advisor LOADS on demand
into a dedicated, recognizable workspace — it is never seeded into their real
workspaces. ``/demo/load`` provisions (or returns) that workspace and seeds it;
``/demo/reset`` wipes and re-seeds it for a clean walkthrough. The work is done
server-side, bound to the demo workspace under RLS, with every figure computed
by the tax engine (see ``app.services.demo_seed``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import require_scopes
from app.schemas.auth import AuthContext
from app.services.demo_seed import load_demo_workspace, reset_demo_workspace

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/load")
async def post_load_demo(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> dict[str, Any]:
    """Load the caller's demo workspace, creating + seeding it on first use.

    Idempotent: if the user already has a demo workspace it is returned as-is
    (no duplicate, no re-seed). Returns ``{workspace_id, name, client_count}``.
    """
    return await load_demo_workspace(uc_uid=ctx.uc_uid)


@router.post("/reset")
async def post_reset_demo(
    ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> dict[str, Any]:
    """Clear and re-seed the caller's demo workspace.

    Returns ``{workspace_id, name, client_count}``. 404 if the user has no demo
    workspace to reset (load it first).
    """
    try:
        return await reset_demo_workspace(uc_uid=ctx.uc_uid)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
