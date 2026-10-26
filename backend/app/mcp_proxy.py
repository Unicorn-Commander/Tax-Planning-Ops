"""Vendored MCP proxy helpers for the in-process HTTP MCP endpoint.

These pure functions are COPIED VERBATIM from the canonical stdio MCP server at
``<repo>/mcp/server.py`` (route parsing, path-param substitution, JSON-Schema
building, and the httpx request builder). They are duplicated here — rather than
imported — because ``mcp/server.py`` lives OUTSIDE the backend Docker build
context (the context is ``backend/``), so it does not ship in the image. The
``app/api/mcp.py`` router serves the HTTP JSON-RPC transport by reusing exactly
this logic; only the transport differs (HTTP JSON-RPC in vs. stdio) and the base
URL is loopback (``http://localhost:8000/api/v1``).

SYNC CONTRACT: if you change route parsing / schema building / proxy semantics
in ``mcp/server.py``, mirror the change here (and re-vendor ``mcp/tools.json``
into ``app/mcp_tools.json``). ``mcp/test_server.py`` and the backend tests both
exercise this logic so drift is caught.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

DEFAULT_API_URL = "http://localhost:8000/api/v1"
WORKSPACE_HEADER = "X-Workspace-Id"

# Argument keys that are reserved (not treated as path/body/query field values).
RESERVED_ARG_KEYS = {"query", "body"}

_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


# ---------------------------------------------------------------------------
# Tool registry (loaded from the VENDORED app/mcp_tools.json)
# ---------------------------------------------------------------------------


def _tools_path() -> Path:
    # Vendored copy of the canonical <repo>/mcp/tools.json. MUST stay in sync
    # with it (see mcp/README.md). Kept inside app/ so it ships in the image.
    return Path(__file__).with_name("mcp_tools.json")


def load_tools() -> list[dict[str, Any]]:
    """Load the tool->endpoint map from the vendored mcp_tools.json."""
    # The checked-in registry is the trusted list-of-objects boundary; retain
    # json.loads' runtime behavior while giving the rest of the module its shape.
    return cast(list[dict[str, Any]], json.loads(_tools_path().read_text()))


def parse_route(route: str) -> tuple[str, str]:
    """Split a ``"METHOD /path"`` route string into ``(method, path)``."""
    method, _, path = route.strip().partition(" ")
    return method.upper(), path.strip()


def path_params(path: str) -> list[str]:
    """Return the ``{param}`` names that appear in a route path, in order."""
    return _PATH_PARAM_RE.findall(path)


def tool_input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema for a tool's input (one string property per path
    param + generic ``query``/``body`` bags). Copied from mcp/server.py."""
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

    properties["query"] = {
        "type": "object",
        "description": (
            "Query-string parameters to send (merged with any extra "
            "top-level args on GET)."
        ),
        "additionalProperties": True,
    }
    if method in {"POST", "PUT", "PATCH"}:
        properties["body"] = {
            "type": "object",
            "description": (
                "Request body fields (merged with any extra top-level args)."
            ),
            "additionalProperties": True,
        }

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def tool_description(tool: dict[str, Any]) -> str:
    """Human/LLM-facing description: purpose + route + required scope."""
    base = tool.get("description") or tool["name"].replace("_", " ").capitalize()
    parts = [base, f"Proxies {tool['route']}.", f"Required scope: {tool['scope']}."]
    if tool.get("params"):
        parts.append(f"Params — {tool['params']}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# HTTP request building (pure, testable — no network here)
# ---------------------------------------------------------------------------


def join_url(base: str, path: str) -> str:
    """Join the API base URL with a route path, avoiding a duplicated prefix.

    ``tools.json`` route paths are written with the full ``/api/v1/...`` prefix,
    but the base URL already points at ``.../api/v1``. Collapse any overlap so
    we don't produce ``/api/v1/api/v1/...``. Copied from mcp/server.py.
    """
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    path_segs = [s for s in path.split("/") if s]
    if "//" in base:
        after_host = base.split("//", 1)[1]
        host_and_path = after_host.split("/", 1)
        base_path_segs = (
            [s for s in host_and_path[1].split("/") if s]
            if len(host_and_path) > 1
            else []
        )
    else:
        base_path_segs = [s for s in base.split("/") if s]

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
    base_url: str = DEFAULT_API_URL,
    token: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Build the HTTP request for a ``tools/call`` invocation (pure — no I/O).

    Returns ``{method, url, headers, params, json}``. Faithful proxy routing
    rules copied from mcp/server.py: path params substituted from ``arguments``;
    ``query`` always sent as query-string; for GET/DELETE remaining args + body
    go to the query; for POST/PUT/PATCH remaining args + ``body`` form the JSON
    body. Auth/workspace headers are forwarded verbatim so the backend enforces
    RLS, entitlement and scopes.
    """
    arguments = dict(arguments or {})
    method, path = parse_route(tool["route"])
    base = base_url.rstrip("/")

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

    headers: dict[str, str] = {"Accept": "application/json", "X-UC-Door": "mcp"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if workspace_id:
        headers[WORKSPACE_HEADER] = str(workspace_id)

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


async def execute_request(req: dict[str, Any], *, timeout: float = 60.0) -> Any:
    """Perform the request over httpx.AsyncClient, return parsed JSON (or text).

    Raises ToolHTTPError on a non-2xx status. Copied from mcp/server.py's
    ``_execute_async``.
    """
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
