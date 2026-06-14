#!/usr/bin/env python3
"""Tax-Planning-Ops MCP server — "the third door".

NO WRAPPERS. TPO exposes three co-equal doors over ONE engine: the GUI, the
language Console, and this MCP/API surface. Every tool here EXECUTES by proxying
to the corresponding existing FastAPI REST endpoint under ``/api/v1``. This
server is a thin, faithful client of that REST API: it forwards the same
``Authorization: Bearer`` token and ``X-Workspace-Id`` header, so the backend
applies the same auth, entitlement, RLS and scope enforcement. It reimplements
NO tax logic.

The tool->endpoint map lives in ``tools.json``; the Brigade-discoverable
manifest lives in ``manifest.json``. Add a tool by adding one line to
``tools.json`` — no code change required.

Transport: Model Context Protocol over stdio (JSON-RPC 2.0). Implemented with
the official ``mcp`` Python SDK's low-level ``Server`` (chosen over FastMCP
because tools are registered dynamically from ``tools.json`` rather than as
statically-decorated functions). HTTP proxying uses ``httpx`` (already a backend
dependency).

Environment:
  TPO_API_URL       Base URL of the REST API. Default ``http://localhost:8000/api/v1``.
  TPO_MCP_TOKEN     Bearer token forwarded as ``Authorization: Bearer <token>``.
  TPO_WORKSPACE_ID  Forwarded as ``X-Workspace-Id`` (optional; omitted if unset).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000/api/v1"
WORKSPACE_HEADER = "X-Workspace-Id"

# Every path param a tool route may declare. (Documented in the task spec; we
# also auto-discover any ``{param}`` token in a route so new params Just Work.)
KNOWN_PATH_PARAMS = (
    "id",
    "tax_year_id",
    "client_tax_year_id",
    "memo_id",
    "task_id",
    "plan_tax_year_id",
    "field_id",
    "extracted_return_id",
)

# Argument keys that are reserved (not treated as path/body/query field values).
RESERVED_ARG_KEYS = {"query", "body"}

_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


# ---------------------------------------------------------------------------
# Tool registry (loaded from tools.json)
# ---------------------------------------------------------------------------


def _tools_path() -> Path:
    return Path(__file__).with_name("tools.json")


def load_tools() -> list[dict[str, Any]]:
    """Load the tool->endpoint map from tools.json."""
    return json.loads(_tools_path().read_text())


def parse_route(route: str) -> tuple[str, str]:
    """Split a ``"METHOD /path"`` route string into ``(method, path)``."""
    method, _, path = route.strip().partition(" ")
    return method.upper(), path.strip()


def path_params(path: str) -> list[str]:
    """Return the ``{param}`` names that appear in a route path, in order."""
    return _PATH_PARAM_RE.findall(path)


def tool_input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema for a tool's input.

    Properties:
      * one string property per path param (each required),
      * a generic ``body`` object (free-form) for write methods, and a generic
        ``query`` object for filters/params on any method.
    Additional top-level properties are allowed: any extra argument the caller
    passes (and that is not a path param) becomes part of the body (for
    POST/PUT/PATCH) or the query string (for GET/DELETE).
    """
    method, path = parse_route(tool["route"])
    params = path_params(path)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        properties[p] = {
            "type": "string",
            "description": f"Path parameter `{p}` for {tool['route']}.",
        }
        required.append(p)

    # Generic query bag (always allowed).
    properties["query"] = {
        "type": "object",
        "description": "Query-string parameters to send (merged with any extra top-level args on GET).",
        "additionalProperties": True,
    }
    # Generic body bag for write methods.
    if method in {"POST", "PUT", "PATCH"}:
        properties["body"] = {
            "type": "object",
            "description": "Request body fields (merged with any extra top-level args).",
            "additionalProperties": True,
        }

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        # Extra args beyond path params are accepted and routed to body/query.
        "additionalProperties": True,
    }


def tool_description(tool: dict[str, Any]) -> str:
    """Human/LLM-facing description: the tool's purpose + route + required scope."""
    base = tool.get("description") or tool["name"].replace("_", " ").capitalize()
    parts = [base, f"Proxies {tool['route']}.", f"Required scope: {tool['scope']}."]
    if tool.get("params"):
        parts.append(f"Params — {tool['params']}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# HTTP request building (pure, testable — no network here)
# ---------------------------------------------------------------------------


def _env_base_url() -> str:
    return os.environ.get("TPO_API_URL", DEFAULT_API_URL).rstrip("/")


def join_url(base: str, path: str) -> str:
    """Join the API base URL with a route path, avoiding a duplicated prefix.

    ``tools.json`` route paths are written with the full ``/api/v1/...`` prefix,
    but ``TPO_API_URL`` already points at ``.../api/v1`` by default. If the base
    already ends with the leading segment(s) of the path, collapse the overlap
    so we don't produce ``/api/v1/api/v1/...``. If the base is a bare host (no
    ``/api/v1``), nothing is stripped and the full path is used as-is.
    """
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    base_segs = [s for s in base.split("/") if s and "://" not in s]
    # Reconstruct just the path portion of the base (after scheme+host).
    # Find the longest suffix of base path-segments that is a prefix of the
    # route path-segments and drop it from the route path.
    path_segs = [s for s in path.split("/") if s]
    # Only consider the trailing path segments of the base (everything after host).
    # base like "http://h:8000/api/v1" -> base_segs includes host; isolate path tail.
    if "//" in base:
        after_host = base.split("//", 1)[1]
        host_and_path = after_host.split("/", 1)
        base_path_segs = (
            [s for s in host_and_path[1].split("/") if s]
            if len(host_and_path) > 1
            else []
        )
    else:
        base_path_segs = base_segs

    overlap = 0
    max_k = min(len(base_path_segs), len(path_segs))
    for k in range(max_k, 0, -1):
        if base_path_segs[-k:] == path_segs[:k]:
            overlap = k
            break
    remaining = path_segs[overlap:]
    return base + ("/" + "/".join(remaining) if remaining else "")


def build_request(
    tool: dict[str, Any],
    arguments: dict[str, Any] | None,
    *,
    base_url: str | None = None,
    token: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Build the HTTP request for a ``tools/call`` invocation.

    Pure function — performs no I/O. Returns a dict:
        {method, url, headers, params, json}

    Routing rules (faithful proxy):
      * Path params (``{name}``) are substituted from ``arguments``.
      * ``query`` (a dict) is always sent as query-string params.
      * For GET/DELETE, remaining (non-path, non-reserved) args are ALSO sent as
        query params; ``body`` (if present) is merged into them too.
      * For POST/PUT/PATCH, remaining args are sent as the JSON body; an explicit
        ``body`` dict is merged in (and takes precedence on key collisions).

    Auth/workspace headers are forwarded verbatim so the backend enforces RLS,
    entitlement and scopes — this server adds no logic of its own.
    """
    arguments = dict(arguments or {})
    method, path = parse_route(tool["route"])
    base = (base_url if base_url is not None else _env_base_url()).rstrip("/")

    # 1) Substitute path params.
    needed = path_params(path)
    missing = [p for p in needed if arguments.get(p) in (None, "")]
    if missing:
        raise ValueError(
            f"tool '{tool['name']}' is missing required path parameter(s): {', '.join(missing)}"
        )
    consumed: set[str] = set()
    for p in needed:
        path = path.replace("{" + p + "}", str(arguments[p]))
        consumed.add(p)

    url = join_url(base, path)

    # 2) Headers — forward auth + workspace, nothing more.
    headers: dict[str, str] = {"Accept": "application/json"}
    tok = token if token is not None else os.environ.get("TPO_MCP_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    ws = workspace_id if workspace_id is not None else os.environ.get("TPO_WORKSPACE_ID")
    if ws:
        headers[WORKSPACE_HEADER] = str(ws)

    # 3) Remaining args (not path params, not reserved) route to body or query.
    explicit_query = arguments.get("query") or {}
    explicit_body = arguments.get("body") or {}
    if not isinstance(explicit_query, dict):
        raise ValueError("'query' argument must be an object/dict")
    if not isinstance(explicit_body, dict):
        raise ValueError("'body' argument must be an object/dict")

    leftover = {
        k: v
        for k, v in arguments.items()
        if k not in consumed and k not in RESERVED_ARG_KEYS
    }

    params: dict[str, Any] = {}
    json_body: dict[str, Any] | None = None

    if method in {"GET", "DELETE"}:
        params = {**leftover, **explicit_body, **explicit_query}
    else:
        json_body = {**leftover, **explicit_body}
        params = dict(explicit_query)

    if json_body is not None:
        headers["Content-Type"] = "application/json"

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "json": json_body,
    }


# ---------------------------------------------------------------------------
# HTTP execution (the only place that touches the network)
# ---------------------------------------------------------------------------


class ToolHTTPError(Exception):
    """Raised when the REST API returns a non-2xx response."""

    def __init__(self, status: int, body: Any, *, method: str, url: str):
        self.status = status
        self.body = body
        self.method = method
        self.url = url
        super().__init__(f"{method} {url} -> HTTP {status}: {body}")


def execute_request(req: dict[str, Any], *, timeout: float = 60.0) -> Any:
    """Perform the HTTP request and return parsed JSON (or text).

    Raises ToolHTTPError on a non-2xx status. Imported lazily so the module can
    be loaded for tests / tools-listing without httpx present.
    """
    import httpx

    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            req["method"],
            req["url"],
            headers=req["headers"],
            params=req["params"] or None,
            json=req["json"],
        )
        # Parse body best-effort.
        try:
            payload: Any = resp.json()
        except Exception:
            payload = resp.text

        if resp.status_code >= 400:
            raise ToolHTTPError(
                resp.status_code,
                payload,
                method=req["method"],
                url=req["url"],
            )
        return payload


def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Any:
    """Look up a tool by name, build its request, and execute it. Returns JSON."""
    registry = tools if tools is not None else load_tools()
    tool = next((t for t in registry if t["name"] == name), None)
    if tool is None:
        raise ValueError(f"unknown tool: {name}")
    req = build_request(tool, arguments)
    return execute_request(req)


# ---------------------------------------------------------------------------
# MCP server (low-level SDK, stdio)
# ---------------------------------------------------------------------------


def build_server():  # pragma: no cover - exercised via stdio, not unit tests
    """Construct the low-level MCP ``Server`` with dynamic handlers."""
    from mcp.server import Server
    import mcp.types as types

    tools = load_tools()
    by_name = {t["name"]: t for t in tools}

    server = Server("tax-planning-ops")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=tool_description(t),
                inputSchema=tool_input_schema(t),
            )
            for t in tools
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None):
        tool = by_name.get(name)
        if tool is None:
            return [types.TextContent(type="text", text=f"unknown tool: {name}")]
        req = build_request(tool, arguments)
        try:
            result = await _execute_async(req)
        except ToolHTTPError as exc:
            # Faithful error surface: status + body from the REST API.
            err = {
                "error": "rest_api_error",
                "status": exc.status,
                "method": exc.method,
                "url": exc.url,
                "body": exc.body,
            }
            return [types.TextContent(type="text", text=json.dumps(err, indent=2))]
        except Exception as exc:  # noqa: BLE001 - report any build/transport error
            err = {"error": "tool_error", "message": str(exc)}
            return [types.TextContent(type="text", text=json.dumps(err, indent=2))]

        text = result if isinstance(result, str) else json.dumps(result, indent=2)
        return [types.TextContent(type="text", text=text)]

    return server


async def _execute_async(req: dict[str, Any], *, timeout: float = 60.0) -> Any:
    """Async variant of execute_request using httpx.AsyncClient."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            req["method"],
            req["url"],
            headers=req["headers"],
            params=req["params"] or None,
            json=req["json"],
        )
        try:
            payload: Any = resp.json()
        except Exception:
            payload = resp.text
        if resp.status_code >= 400:
            raise ToolHTTPError(
                resp.status_code, payload, method=req["method"], url=req["url"]
            )
        return payload


async def _amain() -> None:  # pragma: no cover - stdio runtime
    from mcp.server.stdio import stdio_server

    server = build_server()
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


def main() -> None:  # pragma: no cover - stdio runtime
    import anyio

    anyio.run(_amain)


if __name__ == "__main__":
    main()
