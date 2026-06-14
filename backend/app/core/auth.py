from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID, uuid5

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.integrations.control_plane import check_entitlement
from app.integrations.keycloak import KeycloakVerifier
from app.schemas.auth import AuthContext

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


class JWTAuthMiddleware(BaseHTTPMiddleware):
    SKIP_PREFIXES = (
        "/docs",
        "/openapi.json",
        "/redoc",
        "/livez",
        "/api/v1/livez",
        "/api/v1/auth/keycloak",
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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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
            claims = await self.verifier.verify(auth_header.removeprefix("Bearer ").strip())
            workspace_id, authorized = resolve_workspace_id(
                claims, request.headers.get(WORKSPACE_HEADER)
            )
            scopes = _scopes_from_claims(claims)
            # Self-serve: a UC user with no explicit workspace claim is the
            # advisor of their own derived workspace (RLS-isolated). Managed /
            # firm workspaces still require an explicitly granted taxplan role.
            if derive_self_serve_workspace(claims) is not None:
                scopes = scopes | _SELF_SERVE_SCOPES
            entitled = await check_entitlement(workspace_id, self.settings)
            if not entitled:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="module not entitled"
                )
            request.state.auth_context = AuthContext(
                claims=claims,
                uc_uid=str(claims.get("uc_uid") or claims.get("sub") or ""),
                workspace_id=workspace_id,
                authorized_workspace_ids=authorized,
                scopes=scopes,
            )
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
            )
        return await call_next(request)


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
