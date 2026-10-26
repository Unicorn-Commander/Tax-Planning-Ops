"""OAuth protected-resource discovery and the MCP HTTP edge.

RFC 9728 metadata and the MCP bearer challenge live here so the resource URL,
issuer, and realm stay aligned on both rings. Ring-specific values come from
settings (``PUBLIC_BASE_URL``, ``KEYCLOAK_ISSUER``) or, when the public origin
is unset, from ``X-Forwarded-Proto`` / ``Host`` on the request. No hostname is
hard-coded.
"""
from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

MCP_PATH = "/api/v1/mcp"
MCP_REALM = "tax-planning-ops-mcp"
PRM_PATH = "/.well-known/oauth-protected-resource"
PRM_MCP_PATH = f"{PRM_PATH}{MCP_PATH}"
MCP_CORS_METHODS = "GET, POST, OPTIONS"
MCP_CORS_HEADERS = (
    "Authorization, Content-Type, Accept, Mcp-Session-Id, "
    "Mcp-Protocol-Version, Last-Event-ID"
)
MCP_CORS_EXPOSE_HEADERS = "Mcp-Session-Id"
MCP_RESOURCE_DOCUMENTATION = "https://unicorncommander.ai/platform/bring-your-own-ai"
MCP_SCOPES = ("openid", "profile", "taxplan:advisor", "taxplan:admin")

router = APIRouter(tags=["oauth-discovery"])


def _first_header(value: str) -> str:
    return value.split(",")[0].strip()


def _safe_forwarded_host(value: str) -> str:
    """Return a single host header, or empty when it is not a host."""
    host = _first_header(value)
    if not host or any(char in host for char in " \r\n/@\\"):
        return ""
    return host


def _safe_scheme(value: str, fallback: str) -> str:
    scheme = _first_header(value).lower()
    if scheme in {"http", "https"}:
        return scheme
    fallback_scheme = fallback.lower()
    if fallback_scheme in {"http", "https"}:
        return fallback_scheme
    return "http"


def public_base_url(request: Request | None = None) -> str:
    """Public origin for this ring. Config wins over forwarded headers."""
    configured = get_settings().PUBLIC_BASE_URL.strip().rstrip("/")
    if configured:
        return configured
    if request is None:
        return ""
    scheme = _safe_scheme(
        request.headers.get("x-forwarded-proto", ""),
        request.url.scheme,
    )
    host = _safe_forwarded_host(request.headers.get("x-forwarded-host", ""))
    if not host:
        host = _safe_forwarded_host(request.headers.get("host", ""))
    if not host:
        host = _safe_forwarded_host(request.url.netloc)
    if not host:
        return ""
    return f"{scheme}://{host}"


def canonical_mcp_url(request: Request | None = None) -> str:
    """Canonical MCP URL. The slash form is not canonical."""
    return f"{public_base_url(request)}{MCP_PATH}"


def protected_resource_metadata_url(request: Request | None = None) -> str:
    """Path-suffixed RFC 9728 URL advertised on the MCP 401 challenge."""
    return f"{public_base_url(request)}{PRM_MCP_PATH}"


def metadata_document(request: Request | None = None) -> dict[str, object]:
    """RFC 9728 document. ``authorization_servers`` is the configured issuer."""
    issuer = get_settings().KEYCLOAK_ISSUER.strip().rstrip("/")
    return {
        "resource": canonical_mcp_url(request),
        "authorization_servers": [issuer] if issuer else [],
        "bearer_methods_supported": ["header"],
        "scopes_supported": list(MCP_SCOPES),
        "resource_name": "Tax-Planning-Ops MCP",
        "resource_documentation": MCP_RESOURCE_DOCUMENTATION,
    }


def _prm_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": MCP_CORS_HEADERS,
        "Cache-Control": "public, max-age=3600",
    }


def metadata_response(request: Request | None = None) -> JSONResponse:
    return JSONResponse(metadata_document(request), headers=_prm_headers())


def mcp_www_authenticate(request: Request, *, token_present: bool) -> str:
    """Challenge for an MCP 401. The value never includes the bearer token."""
    challenge = (
        f'Bearer realm="{MCP_REALM}", '
        f'resource_metadata="{protected_resource_metadata_url(request)}"'
    )
    if token_present:
        challenge += ', error="invalid_token"'
    return challenge


def bearer_token_present(headers: Mapping[str, str]) -> bool:
    """True when an Authorization bearer value was sent (not logged)."""
    header = headers.get("authorization") or headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        return False
    return bool(header.removeprefix("Bearer ").strip())


def is_mcp_path(path: str) -> bool:
    """True for the canonical MCP path and its single trailing-slash form."""
    return path == MCP_PATH or path == f"{MCP_PATH}/"


def is_prm_path(path: str) -> bool:
    return path == PRM_PATH or path.startswith(f"{PRM_PATH}/")


def _normalise_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def allowed_mcp_origins() -> set[str]:
    """Browser origins allowed to call the MCP path."""
    settings = get_settings()
    values = (
        *settings.CORS_ORIGINS,
        settings.FRONTEND_URL,
        settings.PUBLIC_BASE_URL,
        *settings.MCP_ALLOWED_ORIGINS,
    )
    return {_normalise_origin(value) for value in values if value}


def _mcp_cors_headers(origin: str | None) -> dict[str, str]:
    headers = {
        "Access-Control-Allow-Methods": MCP_CORS_METHODS,
        "Access-Control-Allow-Headers": MCP_CORS_HEADERS,
        "Access-Control-Expose-Headers": MCP_CORS_EXPOSE_HEADERS,
        "Access-Control-Max-Age": "3600",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return headers


def _upsert_header(message: Message, name: str, value: str) -> None:
    headers = list(message.get("headers") or [])
    encoded_name = name.lower().encode("latin-1")
    headers = [(key, raw) for key, raw in headers if key.lower() != encoded_name]
    headers.append((encoded_name, value.encode("latin-1")))
    message["headers"] = headers


class MCPPathCORSMiddleware:
    """Browser rules for ``/api/v1/mcp`` and stable headers on the PRM routes.

    OPTIONS and a disallowed ``Origin`` are answered here, before the bearer
    gate. Requests without ``Origin`` (curl, desktop clients) pass through.
    Protected-resource responses keep ``Access-Control-Allow-Origin: *`` even
    if the app-wide CORS middleware would replace it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        headers = Headers(scope=scope)
        origin = headers.get("origin")

        if path == f"{MCP_PATH}/":
            query = scope.get("query_string", b"")
            if not isinstance(query, bytes) or b"\r" in query or b"\n" in query:
                query = b""
            location = MCP_PATH
            if query:
                location = f"{MCP_PATH}?{query.decode('latin-1')}"
            await RedirectResponse(url=location, status_code=308)(scope, receive, send)
            return

        if is_prm_path(path) and method == "OPTIONS":
            if path.endswith("/") and path != f"{PRM_PATH}/":
                target = path.rstrip("/") or PRM_PATH
                response: Response = RedirectResponse(url=target, status_code=308)
            elif path == f"{PRM_PATH}/":
                response = RedirectResponse(url=PRM_PATH, status_code=308)
            else:
                response = metadata_response(Request(scope, receive))
            await response(scope, receive, send)
            return

        if is_mcp_path(path):
            if origin and _normalise_origin(origin) not in allowed_mcp_origins():
                await JSONResponse(
                    {"detail": "Origin not allowed"},
                    status_code=403,
                )(scope, receive, send)
                return
            if method == "OPTIONS":
                await Response(
                    status_code=204,
                    headers=_mcp_cors_headers(origin),
                )(scope, receive, send)
                return

        async def send_wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                if is_prm_path(path):
                    for name, value in _prm_headers().items():
                        _upsert_header(message, name, value)
                elif is_mcp_path(path) and origin:
                    existing = {
                        key.lower()
                        for key, _value in message.get("headers", [])
                    }
                    for name, value in _mcp_cors_headers(origin).items():
                        if name.lower().encode("latin-1") not in existing:
                            _upsert_header(message, name, value)
            await send(message)

        await self.app(scope, receive, send_wrapped)


@router.api_route(PRM_PATH, methods=["GET", "OPTIONS"], include_in_schema=False)
async def protected_resource_metadata_root(request: Request) -> JSONResponse:
    return metadata_response(request)


@router.api_route(PRM_MCP_PATH, methods=["GET", "OPTIONS"], include_in_schema=False)
async def protected_resource_metadata_mcp(request: Request) -> JSONResponse:
    return metadata_response(request)


@router.api_route(f"{PRM_PATH}/", methods=["GET", "OPTIONS"], include_in_schema=False)
async def protected_resource_metadata_root_slash() -> RedirectResponse:
    return RedirectResponse(url=PRM_PATH, status_code=308)


@router.api_route(
    f"{PRM_MCP_PATH}/",
    methods=["GET", "OPTIONS"],
    include_in_schema=False,
)
async def protected_resource_metadata_mcp_slash() -> RedirectResponse:
    return RedirectResponse(url=PRM_MCP_PATH, status_code=308)


__all__ = (
    "MCPPathCORSMiddleware",
    "MCP_PATH",
    "MCP_REALM",
    "PRM_MCP_PATH",
    "PRM_PATH",
    "bearer_token_present",
    "canonical_mcp_url",
    "is_mcp_path",
    "mcp_www_authenticate",
    "metadata_document",
    "protected_resource_metadata_url",
    "router",
)
