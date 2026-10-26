"""HTTP MCP endpoint — the third door over streamable-http (single POST).

``POST /api/v1/mcp`` speaks Model Context Protocol as JSON-RPC 2.0 over one HTTP
request/response (no SSE — Claude Code's streamable-http client accepts a plain
``application/json`` reply for request/response methods). It reuses the SAME tool
registry (vendored ``app/mcp_tools.json``) and proxy semantics as the canonical
stdio server (``mcp/server.py``) via ``app.mcp_proxy``; only the transport
differs.

Auth: this route is covered by ``JWTAuthMiddleware`` (NOT in SKIP_PREFIXES), so a
valid ``tpo_pat_*`` (or Keycloak) bearer authenticates it and a bad/missing one
401s before the handler runs. The 401 carries ``WWW-Authenticate`` with the
protected-resource metadata URL. Cookie or session headers are not credentials
on this path. ``GET`` (and every non-POST method) returns 405: this door is one
JSON-RPC response, not an SSE stream. ``tools/call`` forwards the caller's own
``Authorization`` + ``X-Workspace-Id`` headers to the loopback REST API, so the
backend re-applies auth, entitlement, RLS and scope enforcement on every tool —
this router adds no tax logic and no privilege of its own.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.mcp_proxy import (
    DEFAULT_API_URL,
    ToolHTTPError,
    build_request,
    execute_request,
    load_tools,
    tool_description,
    tool_input_schema,
)

router = APIRouter(tags=["mcp"])

# Protocol version we implement; echoed back if the client doesn't pin one.
_PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC 2.0 standard error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


def _server_info() -> dict[str, Any]:
    settings = get_settings()
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION}


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": t["name"],
            "description": tool_description(t),
            "inputSchema": tool_input_schema(t),
        }
        for t in load_tools()
    ]


async def _handle_tools_call(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    """Proxy a single tool call to the loopback REST API and shape the MCP
    result. Never raises — a REST/transport error is returned as an isError
    tool result so the model sees the faithful status+body."""
    name = params.get("name")
    arguments = dict(params.get("arguments") or {})

    tool = next((t for t in load_tools() if t["name"] == name), None)
    if tool is None:
        return {
            "content": [{"type": "text", "text": f"unknown tool: {name}"}],
            "isError": True,
        }

    # Workspace selector: explicit argument wins, else the incoming header.
    workspace_id = (
        arguments.pop("workspace_id", None)
        or arguments.pop("X-Workspace-Id", None)
        or request.headers.get("X-Workspace-Id")
    )
    # Forward the caller's own bearer verbatim so the backend re-authenticates.
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header else None

    try:
        proxy_req = build_request(
            tool,
            arguments,
            base_url=DEFAULT_API_URL,
            token=token,
            workspace_id=str(workspace_id) if workspace_id else None,
        )
        result = await execute_request(proxy_req)
    except ToolHTTPError as exc:
        err = {
            "error": "rest_api_error",
            "status": exc.status,
            "method": exc.method,
            "url": exc.url,
            "body": exc.body,
        }
        return {
            "content": [{"type": "text", "text": json.dumps(err, indent=2)}],
            "isError": True,
        }
    except Exception as exc:  # noqa: BLE001 - report any build/transport error
        err = {"error": "tool_error", "message": str(exc)}
        return {
            "content": [{"type": "text", "text": json.dumps(err, indent=2)}],
            "isError": True,
        }

    text = result if isinstance(result, str) else json.dumps(result, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


async def _dispatch(request: Request, message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns a response dict, or None for a
    notification (no ``id``) which must not produce a response body."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(None, _INVALID_REQUEST, "invalid JSON-RPC 2.0 request")

    method = message.get("method")
    req_id = message.get("id")
    is_notification = "id" not in message
    params = message.get("params") or {}

    # Notifications (initialized, cancelled, ...) get no response body.
    if is_notification:
        return None

    if method == "initialize":
        client_version = params.get("protocolVersion") or _PROTOCOL_VERSION
        return _rpc_result(
            req_id,
            {
                "protocolVersion": client_version,
                "capabilities": {"tools": {}},
                "serverInfo": _server_info(),
            },
        )

    if method == "ping":
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": _tools_list()})

    if method == "tools/call":
        result = await _handle_tools_call(request, params)
        return _rpc_result(req_id, result)

    return _rpc_error(req_id, _METHOD_NOT_FOUND, f"method not found: {method}")


@router.api_route("/mcp", methods=["GET", "PUT", "PATCH", "DELETE", "HEAD"])
async def mcp_method_not_allowed() -> Response:
    """Streamable HTTP allows a GET SSE stream. This server is POST-only.

    A client that is already authenticated gets 405. An unauthenticated client
    still gets 401 from the bearer gate, which runs first.
    """
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=200,
            content=_rpc_error(None, _PARSE_ERROR, "parse error"),
        )

    # Batch (JSON array) support: dispatch each, drop notification (None) results.
    if isinstance(payload, list):
        responses = []
        for message in payload:
            resp = await _dispatch(request, message)
            if resp is not None:
                responses.append(resp)
        if not responses:
            # An all-notification batch => 202 with no body.
            return Response(status_code=202)
        return JSONResponse(status_code=200, content=responses)

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=200,
            content=_rpc_error(None, _INVALID_REQUEST, "invalid JSON-RPC 2.0 request"),
        )

    resp = await _dispatch(request, payload)
    if resp is None:
        # A single notification (e.g. notifications/initialized) => 202 no body.
        return Response(status_code=202)
    return JSONResponse(status_code=200, content=resp)
