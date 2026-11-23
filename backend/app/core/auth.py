from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID, uuid5

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.request_context import current_door, normalize_door
from app.db.session import async_session_maker
from app.integrations.control_plane import tax_ops_org
from app.integrations.keycloak import KeycloakVerifier
from app.oauth_discovery import bearer_token_present, is_mcp_path, mcp_www_authenticate
from app.schemas.auth import AuthContext
from app.security.pat import (
    find_active_pat_by_token,
    looks_like_pat,
    touch_last_used,
)
from app.services.workspaces import is_workspace_member, workspace_org

logger = logging.getLogger("tax_planning_ops.entitlement")

DOOR_HEADER = "X-UC-Door"

WORKSPACE_HEADER = "X-Workspace-Id"

# Stable namespace for deriving a self-serve workspace from a user's subject.
# A UC user with no explicit workspace claim becomes the advisor of their OWN
# deterministic workspace (uuid5 of `sub`) — auto-provisioned by ensure_workspace
# and isolated by RLS. This is what makes the suite SSO genuinely multi-user:
# any authenticated UC user can transact in their own isolated tenant without an
# out-of-band provisioning step, while managed/firm workspaces still require an
# explicitly granted workspace_id + taxplan role.
_SELF_SERVE_WS_NAMESPACE = UUID("d5f7e2a0-7c3b-4e6a-9f1d-7461782d706c")
# Baseline scope a self-serve user holds WITHIN their own derived workspace.
_SELF_SERVE_SCOPES = frozenset({"taxplan:advisor"})

# 403 body for a caller whose Ops-Center org lacks tax_ops_access.
NOT_ENTITLED_DETAIL = "Tax-Planning-Ops is not included in your plan"


def _scopes_from_claims(claims: dict[str, Any]) -> set[str]:
    scopes = set(str(claims.get("scope", "")).split())
    realm_access = claims.get("realm_access") or {}
    scopes.update(str(role) for role in realm_access.get("roles", []))
    resource_access = claims.get("resource_access") or {}
    for access in resource_access.values():
        scopes.update(str(role) for role in access.get("roles", []))
    return scopes


def _claim_workspace_ids(claims: dict[str, Any]) -> tuple[UUID | None, set[UUID]]:
    """Return (primary, all-authorized). Primary = the token's `workspace_id`/
    `tenant_id` claim, used as the deterministic default when no header is sent
    (a set's iteration order is not stable, which previously made the default
    workspace effectively random for multi-workspace users)."""
    ids: set[UUID] = set()
    primary: UUID | None = None
    for key in ("workspace_id", "tenant_id"):
        value = claims.get(key)
        if value:
            parsed = UUID(str(value))
            if primary is None:
                primary = parsed
            ids.add(parsed)
    for item in claims.get("workspaces") or claims.get("tenants") or []:
        if isinstance(item, dict):
            value = item.get("workspaceId") or item.get("workspace_id") or item.get("id")
        else:
            value = item
        if value:
            ids.add(UUID(str(value)))
    return primary, ids


def derive_self_serve_workspace(claims: dict[str, Any]) -> UUID | None:
    """The deterministic own-workspace a token self-serves into, or None.

    Returns None when the token carries an explicit workspace claim (a managed
    or firm workspace) — those still require an explicitly granted role. When
    there is NO workspace claim, any authenticated subject gets their own
    `uuid5(sub)` workspace (stable, unique, RLS-isolated, auto-provisioned)."""
    _, authorized = _claim_workspace_ids(claims)
    if authorized:
        return None
    sub = claims.get("sub")
    return uuid5(_SELF_SERVE_WS_NAMESPACE, str(sub)) if sub else None


def resolve_workspace_id(
    claims: dict[str, Any], header_workspace_id: str | None
) -> tuple[UUID, set[UUID]]:
    primary, authorized = _claim_workspace_ids(claims)
    if not authorized:
        derived = derive_self_serve_workspace(claims)
        if derived is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="workspace claim missing",
            )
        primary, authorized = derived, {derived}
    if header_workspace_id:
        selected = UUID(str(header_workspace_id))
    else:
        selected = primary or sorted(authorized, key=str)[0]
    if selected not in authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="workspace selector is not authorized for this token",
        )
    return selected, authorized


def _target_workspace(claims: dict[str, Any], header_ws: str | None) -> UUID | None:
    """The workspace this request would enter (header, else the claim's primary,
    else the self-serve derivation): the same pick as resolve_workspace_id,
    before it is authorized. None when there is none or the header is not a uuid."""
    if header_ws:
        try:
            return UUID(str(header_ws))
        except ValueError:
            return None
    primary, authorized = _claim_workspace_ids(claims)
    if authorized:
        return primary or sorted(authorized, key=str)[0]
    return derive_self_serve_workspace(claims)


async def _touch_pat_last_used(pat_id: UUID) -> None:
    """Best-effort last_used_at bump in its own committed session. Fire-and-
    forget: any failure is swallowed so auth is never blocked on telemetry."""
    try:
        async with async_session_maker() as session:
            await touch_last_used(session, pat_id)
            await session.commit()
    except Exception:  # noqa: S110  # pragma: no cover - never block auth on telemetry
        pass


class JWTAuthMiddleware(BaseHTTPMiddleware):
    SKIP_PREFIXES = (
        "/docs",
        "/openapi.json",
        "/redoc",
        "/livez",
        "/api/v1/livez",
        "/api/v1/auth/keycloak",
        # The refresh token IS the credential here; this path mints a new access
        # token precisely when the old one has expired, so it can't require a
        # valid bearer.
        "/api/v1/auth/refresh",
        # RFC 9728 metadata is public. A bearer must not be required, and a
        # rejected bearer must not turn discovery into a 401.
        "/.well-known/oauth-protected-resource",
    )

    def __init__(
        self,
        app: Any,
        settings: Settings,
        verifier: KeycloakVerifier | None = None,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.verifier = verifier or KeycloakVerifier(settings)

    async def _entitled_org(
        self, claims: dict[str, Any], target: UUID | None, bearer: str
    ) -> UUID | None:
        """The org that entitles this caller to the workspace being entered.

        The org is the workspace's own, read server-side (workspaces.org_id),
        never a request value: a caller entitled in org A who holds a claim,
        header or membership for org B's workspace is asked about B, and only
        an answer for exactly B lets them in. The one unbound case allowed is
        the caller's OWN self-serve workspace: it is bound (by get_tenant_db)
        to the org Ops-Center answers for the caller. Any other workspace
        without a bound org is refused (fail closed)."""
        if not bearer:
            # A PAT (or anything without a user bearer): nothing Ops-Center can
            # verify, so refuse before touching the database.
            logger.warning("tax_ops_access refused: no user bearer to present")
            return None
        if target is None:
            logger.warning("tax_ops_access refused: no workspace to enter")
            return None
        bound = await workspace_org(target)
        if bound is None and target != derive_self_serve_workspace(claims):
            logger.warning("tax_ops_access refused: workspace has no bound org")
            return None
        answered = await tax_ops_org(
            bearer=bearer,
            sub=str(claims.get("sub") or ""),
            settings=self.settings,
            org_id=str(bound) if bound else None,
        )
        return UUID(answered) if answered else None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Stamp which door this request came through (GUI / Console / MCP / API)
        # so audit events carry it as provenance and door-usage stats can count it.
        # Server-side callers (the MCP server) set X-UC-Door explicitly; a browser
        # request is recognised as the GUI by its Origin matching our frontend —
        # no custom cross-origin header (and so no CORS-preflight change) needed.
        door = request.headers.get(DOOR_HEADER)
        if not door:
            raw = request.headers.get("origin") or request.headers.get("referer") or ""
            origin = raw.rstrip("/")
            allowed = [o.rstrip("/") for o in self.settings.CORS_ORIGINS]
            if origin and any(origin.startswith(o) for o in allowed):
                door = "gui"
        current_door.set(normalize_door(door))
        if request.method == "OPTIONS" or request.url.path.startswith(self.SKIP_PREFIXES):
            return await call_next(request)
        # HTTPException raised inside BaseHTTPMiddleware bypasses FastAPI's
        # exception handlers (it would surface as a 500), so translate to a
        # JSON response here.
        try:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="missing bearer token",
                )
            token = auth_header.removeprefix("Bearer ").strip()
            if looks_like_pat(token):
                # Durable-token path: a `tpo_pat_*` bearer authenticates WITHOUT
                # a Keycloak round-trip. A token of this shape is unambiguously a
                # PAT, so a lookup miss 401s here (no fall-through to Keycloak).
                async with async_session_maker() as session:
                    pat = await find_active_pat_by_token(session, token)
                if pat is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="invalid or revoked token",
                    )
                owner = pat.owner_uc_uid
                # Synthesize minimal claims so the SAME downstream flow
                # (resolve_workspace_id + _scopes_from_claims + self-serve) fences a
                # PAT caller identically to a browser. The entitlement differs: see below.
                claims: dict[str, Any] = {
                    "sub": owner,
                    "uc_uid": owner,
                    "scope": " ".join(pat.scopes),
                }
                if pat.workspace_scope:
                    # An explicit workspace claim => managed (non-self-serve)
                    # path, exactly like a Keycloak token carrying workspace_id.
                    claims["workspace_id"] = str(pat.workspace_scope[0])
                # Let the mint endpoint 403 a PAT-mints-PAT attempt.
                request.state.auth_via_pat = True
                # Fire-and-forget last_used bump; never block auth on it.
                asyncio.create_task(_touch_pat_last_used(pat.id))
                # A PAT is our own credential: never send it to Ops-Center.
                # With the check on, a PAT caller has no user bearer to present
                # and is refused (fail closed).
                user_bearer = ""
            else:
                claims = await self.verifier.verify(token)
                user_bearer = token
            header_ws = request.headers.get(WORKSPACE_HEADER)
            # The door. Asked BEFORE the workspace selection is authorized
            # (no membership lookup) and before any route runs (so a refused
            # caller never gets a workspace row). Off
            # (ENTITLEMENT_CHECK_ENABLED=false) = allowed, today's behaviour.
            org_id: UUID | None = None
            target = _target_workspace(claims, header_ws)
            if self.settings.ENTITLEMENT_CHECK_ENABLED:
                org_id = await self._entitled_org(claims, target, user_bearer)
                if org_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ENTITLED_DETAIL
                    )
            # The caller's own user bearer (None for PAT callers): kept on the
            # request so routes that must ask another service "may THIS caller
            # see X?" (e.g. the Accounting-Ops link check) can present it
            # instead of TPO's own service token (confused-deputy guard).
            request.state.user_bearer = user_bearer or None
            uc_uid = str(claims.get("uc_uid") or claims.get("sub") or "")
            try:
                workspace_id, authorized = resolve_workspace_id(claims, header_ws)
            except HTTPException as exc:
                # Multi-workspace: a header selecting a workspace the token's
                # claims don't cover is allowed ONLY if the user is a member of
                # it (authorized against workspace_membership under RLS). Any
                # other 403 (and all 401s) propagate unchanged.
                if exc.status_code == status.HTTP_403_FORBIDDEN and header_ws and uc_uid:
                    selected = UUID(str(header_ws))
                    if await is_workspace_member(uc_uid, selected):
                        _, claims_authorized = _claim_workspace_ids(claims)
                        workspace_id, authorized = selected, claims_authorized | {selected}
                    else:
                        raise
                else:
                    raise
            if org_id is not None and workspace_id != target:
                # Never let an answer for one workspace's org admit another.
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ENTITLED_DETAIL
                )
            scopes = _scopes_from_claims(claims)
            # Self-serve: a UC user with no explicit workspace claim is the
            # advisor of their own derived workspace (RLS-isolated). Managed /
            # firm workspaces still require an explicitly granted taxplan role.
            if derive_self_serve_workspace(claims) is not None:
                scopes = scopes | _SELF_SERVE_SCOPES
            request.state.auth_context = AuthContext(
                claims=claims,
                uc_uid=str(claims.get("uc_uid") or claims.get("sub") or ""),
                workspace_id=workspace_id,
                authorized_workspace_ids=authorized,
                scopes=scopes,
                org_id=org_id,
            )
        except HTTPException as exc:
            headers = None
            if exc.status_code == 401:
                if is_mcp_path(request.url.path):
                    headers = {
                        "WWW-Authenticate": mcp_www_authenticate(
                            request,
                            token_present=bearer_token_present(request.headers),
                        )
                    }
                else:
                    headers = {"WWW-Authenticate": "Bearer"}
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )
        return await call_next(request)


def get_user_bearer(request: Request) -> str | None:
    """The caller's own user bearer, or None (PAT callers have none). Routes
    that verify something AGAINST another suite service on the caller's behalf
    must present this, never TPO's service token."""
    value = getattr(request.state, "user_bearer", None)
    return str(value) if value else None


def service_azp_client_ids(settings: Settings) -> set[str]:
    """azp values this deployment knows are service (M2M) clients, not the
    end-user login client: the Accounting-Ops audience and the Brigade
    exchange client. KEYCLOAK_CLIENT_ID is deliberately NOT here: the
    frontend signs users in through that same client, so a real advisor's
    token carries azp = KEYCLOAK_CLIENT_ID and testing azp against it would
    refuse every real user (TPO23-R3-1)."""
    configured = (
        settings.ACCOUNTING_OPS_AUDIENCE,
        settings.BRIGADE_CLIENT_ID,
    )
    return {item.strip() for item in configured if isinstance(item, str) and item.strip()}


def caller_is_user_principal(claims: dict[str, Any], settings: Settings) -> bool:
    """True only for a real end-user principal, never a service/M2M token.

    ``JWTAuthMiddleware`` stamps ``user_bearer`` on ANY verified JWT (auth.py),
    so a client-credentials service token reaches a route looking like a user
    bearer. AO's link-verification route answers membership honestly only for a
    user token (a service token is floored to viewer on every workspace), so a
    service principal must never be used to verify an Accounting-Ops link.

    A client-credentials token is told apart by: no ``uc_uid`` claim, OR a
    ``preferred_username`` starting ``service-account-``, OR a ``client_id`` /
    ``clientId`` claim (Keycloak stamps those on service-account tokens). The
    ``azp`` is only ever tested against the service denylist, never against
    the app's own login client, because users log in through that client too."""
    if not claims.get("uc_uid"):
        return False
    preferred = claims.get("preferred_username")
    if isinstance(preferred, str) and preferred.startswith("service-account-"):
        return False
    if claims.get("client_id") or claims.get("clientId"):
        return False
    return claims.get("azp") not in service_azp_client_ids(settings)


def require_scopes(required: Iterable[str]) -> Callable[[Request], AuthContext]:
    required_set = set(required)

    def dependency(request: Request) -> AuthContext:
        ctx = getattr(request.state, "auth_context", None)
        if not isinstance(ctx, AuthContext):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )
        if "taxplan:admin" in ctx.scopes:
            return ctx
        if not required_set.issubset(ctx.scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")
        return ctx

    return dependency
