"""Personal Access Token self-service — mint / list / revoke.

Routes (included at ``prefix="/api/v1"`` -> ``/api/v1/auth/pats``):

    GET    /auth/pats
    POST   /auth/pats
    DELETE /auth/pats/{pat_id}     (soft revoke)

All routes require a REAL Keycloak session (any authenticated user may manage
THEIR OWN tokens — no special scope). A PAT is blocked from minting more PATs
(``request.state.auth_via_pat`` set by the middleware PAT branch) — chicken-and-
egg defense in depth.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.db.session import async_session_maker, get_auth_context
from app.schemas.auth import AuthContext
from app.security.pat import (
    DEFAULT_TTL_DAYS,
    MAX_ACTIVE_PATS_PER_USER,
    MAX_TTL_DAYS,
    PATRow,
    count_active_pats,
    create_pat,
    list_pats,
    resolve_ttl,
    revoke_pat,
    validate_scopes,
)
from app.services.workspaces import is_workspace_member

router = APIRouter(tags=["personal-access-tokens"])

# Canonical PAT-grantable scope catalog. A PAT may only carry a subset of the
# scopes its owner currently holds (intersected with this catalog).
_ALL_SCOPES: tuple[str, ...] = ("taxplan:advisor", "taxplan:admin")


def _require_keycloak(request: Request) -> None:
    """A PAT cannot mint/list/revoke PATs (only an interactive session can)."""
    if getattr(request.state, "auth_via_pat", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="a token cannot mint tokens",
        )


def _owner_allowed_scopes(ctx: AuthContext) -> set[str]:
    return {s for s in ctx.scopes if s in _ALL_SCOPES}


async def _validate_workspace_scope(
    ctx: AuthContext, requested: list[str] | None
) -> tuple[UUID, ...]:
    """Resolve + authorize the PAT's workspace scope.

    ``None`` -> default to the caller's active workspace (deterministic scoping).
    A provided list must be non-empty and every entry must be a workspace the
    caller can actually reach (claim-authorized OR a recorded membership).
    """
    if requested is None:
        return (ctx.workspace_id,)
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_scope must contain at least one workspace UUID "
            "(or be omitted for the caller's active workspace).",
        )
    try:
        wanted = [UUID(str(v)) for v in requested]
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"workspace_scope entries must be UUIDs: {exc}",
        ) from exc

    missing: list[UUID] = []
    for ws in wanted:
        if ws in ctx.authorized_workspace_ids:
            continue
        if await is_workspace_member(ctx.uc_uid, ws):
            continue
        missing.append(ws)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "workspace_scope contains workspaces the caller cannot reach: "
                f"{[str(m) for m in missing]}"
            ),
        )
    return tuple(wanted)


def _public_pat(p: PATRow) -> dict[str, Any]:
    """Public-facing PAT shape (no secret material)."""
    if p.revoked_at is not None:
        state = "revoked"
    elif p.is_expired:
        state = "expired"
    else:
        state = "active"
    return {
        "id": str(p.id),
        "name": p.name,
        "prefix": p.secret_prefix,
        "scopes": list(p.scopes),
        "workspace_scope": (
            [str(w) for w in p.workspace_scope] if p.workspace_scope else None
        ),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "revoked_at": p.revoked_at.isoformat() if p.revoked_at else None,
        "state": state,
    }


class CreatePATRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] | None = Field(
        default=None,
        description="Subset of the owner's scopes. Omit for the full set the "
        "owner currently holds.",
    )
    workspace_scope: list[str] | None = Field(
        default=None,
        description="UUIDs of workspaces the PAT can reach. Omit to scope it to "
        "the caller's active workspace.",
    )
    ttl_days: int | None = Field(
        default=DEFAULT_TTL_DAYS,
        ge=0,
        le=MAX_TTL_DAYS,
        description=f"Lifetime in days. 0 = never expires. Default "
        f"{DEFAULT_TTL_DAYS}, max {MAX_TTL_DAYS}.",
    )


class CreatePATResponse(BaseModel):
    id: str
    name: str
    secret: str  # raw — shown ONCE
    prefix: str
    scopes: list[str]
    workspace_scope: list[str] | None
    expires_at: str | None
    created_at: str


@router.get("/auth/pats")
async def list_my_pats(
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
) -> list[dict[str, Any]]:
    _require_keycloak(request)
    async with async_session_maker() as session:
        rows = await list_pats(session, ctx.uc_uid)
    return [_public_pat(r) for r in rows]


@router.post("/auth/pats", status_code=status.HTTP_201_CREATED)
async def mint_pat(
    body: CreatePATRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
) -> CreatePATResponse:
    _require_keycloak(request)

    # Cap on active tokens.
    async with async_session_maker() as session:
        active = await count_active_pats(session, ctx.uc_uid)
    if active >= MAX_ACTIVE_PATS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Active personal-access-token limit reached "
                f"({MAX_ACTIVE_PATS_PER_USER}). Revoke one before minting another."
            ),
        )

    # Scope intersection against what the caller currently holds.
    owner_allowed = _owner_allowed_scopes(ctx)
    if not owner_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="caller holds no grantable taxplan scopes.",
        )
    try:
        scopes = validate_scopes(body.scopes, owner_allowed)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    workspace_scope = await _validate_workspace_scope(ctx, body.workspace_scope)

    try:
        expires_at = resolve_ttl(body.ttl_days)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    async with async_session_maker() as session:
        minted = await create_pat(
            session,
            owner_uc_uid=ctx.uc_uid,
            name=body.name.strip(),
            scopes=scopes,
            workspace_scope=workspace_scope,
            expires_at=expires_at,
        )
        await session.commit()

    return CreatePATResponse(
        id=str(minted.id),
        name=minted.name,
        secret=minted.secret,
        prefix=minted.prefix,
        scopes=list(minted.scopes),
        workspace_scope=(
            [str(w) for w in minted.workspace_scope]
            if minted.workspace_scope
            else None
        ),
        expires_at=minted.expires_at.isoformat() if minted.expires_at else None,
        created_at=minted.created_at.isoformat() if minted.created_at else None,
    )


@router.delete("/auth/pats/{pat_id}")
async def revoke_my_pat(
    pat_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    _require_keycloak(request)
    async with async_session_maker() as session:
        ok = await revoke_pat(session, owner_uc_uid=ctx.uc_uid, pat_id=pat_id)
        await session.commit()
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {
        "id": str(pat_id),
        "revoked_at": datetime.now(UTC).isoformat(),
    }
