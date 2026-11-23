"""TPO-MCPP-2: the HTTP MCP door (/api/v1/mcp) must quote path params and
refuse traversal.

The stdio twin (mcp/server.py) got the refusal + quote(value, safe='') fix in
commit f64a1d3 but the vendored HTTP copy (app/mcp_proxy.py) still filled path
params raw, so a tools/call over HTTP could smuggle '../../x' into a different
route or '1?y=z' into a query string against the loopback API. These tests
drive tools/call through the real HTTP door with the loopback client stubbed,
assert every probe is refused with an isError MCP result and that the stubbed
client saw NOTHING (no outbound call), and that a normal uuid still reaches the
API. All subjects and hosts are fictional.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

BASE_URL = "http://mcp-door.test/api/v1"

# Traversal probes: each must be refused by the path-param rule itself, with
# no outbound call (the stdio twin refuses the same four, commit f64a1d3).
TRAVERSALS = ("../x", "..%2f", "a/b", "/api/v1/admin")

# Smuggling probes: no '/' or '..' in them, so the (shared) refusal rule lets
# them through; they must instead be percent-quoted so the '?', '=' and '#'
# never reach the wire as a query string or fragment.
SMUGGLING = ("1?x=1", "1#f")

# The full probe list both doors are compared on.
PROBE_LIST = TRAVERSALS + SMUGGLING

# The auth middleware resolves the workspace from the token claims, not the
# X-Workspace-Id header (a header for a workspace the claims do not cover
# 403s without any DB lookup). Drive the door the same way
# test_mcp_oauth.py does: no workspace header at all.


def _app(
    monkeypatch: Any, seen: list[dict[str, Any]]
) -> TestClient:
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("STANDALONE_MODE", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.taxplanningops.example")
    monkeypatch.setenv("ENTITLEMENT_CHECK_ENABLED", "false")
    get_settings.cache_clear()

    import app.mcp_proxy as mcp_proxy
    from app.api import mcp as mcp_door

    # The door resolves its helpers by name from app.mcp_proxy at CALL time;
    # patch both the module and the router's own namespace so the loopback
    # client is the recording stub and the base URL is a fictional host.
    async def fake_execute(req: dict[str, Any], **kwargs: Any) -> Any:
        seen.append(req)
        return {"ok": True, "url": req["url"]}

    monkeypatch.setattr(mcp_proxy, "DEFAULT_API_URL", BASE_URL)
    monkeypatch.setattr(mcp_proxy, "execute_request", fake_execute)
    monkeypatch.setattr(mcp_door, "DEFAULT_API_URL", BASE_URL)
    monkeypatch.setattr(mcp_door, "execute_request", fake_execute)
    return TestClient(create_app())


def _call(
    client: TestClient, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    response = client.post(
        "/api/v1/mcp",
        headers={"Authorization": "Bearer fictional-mcp-bearer"},
        json=message,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert "result" in body
    return body["result"]


def test_http_door_refuses_traversal_with_no_outbound_call(
    monkeypatch: Any,
) -> None:
    """Every probe in PROBE_LIST is refused through the HTTP door and the
    stubbed loopback client sees no request at all."""
    seen: list[dict[str, Any]] = []
    client = _app(monkeypatch, seen)

    for probe in TRAVERSALS:
        result = _call(client, "save_memo", {"tax_year_id": probe, "body_md": "x"})
        assert result["isError"] is True, f"probe {probe!r} was not refused"
        text = result["content"][0]["text"]
        assert "path parameter" in text and "tax_year_id" in text, text
        assert "must not contain" in text
    assert seen == [], f"stubbed client saw {len(seen)} outbound call(s)"


def test_http_door_quoted_param_still_reaches_api(
    monkeypatch: Any,
) -> None:
    """A normal uuid passes through unquoted and the API IS called."""
    seen: list[dict[str, Any]] = []
    client = _app(monkeypatch, seen)

    uuid_id = str(uuid4())
    result = _call(client, "save_memo", {"tax_year_id": uuid_id, "body_md": "# m"})
    assert result["isError"] is False
    assert len(seen) == 1
    assert seen[0]["url"] == f"{BASE_URL}/clients/tax-years/{uuid_id}/memo"
    assert seen[0]["method"] == "PUT"
    assert seen[0]["json"] == {"body_md": "# m"}
    assert seen[0]["headers"]["Authorization"] == "Bearer fictional-mcp-bearer"
    assert "X-Workspace-Id" not in seen[0]["headers"]


def test_http_door_quotes_reserved_chars_in_path_param(
    monkeypatch: Any,
) -> None:
    """A value with a space is percent-encoded, matching the stdio twin."""
    seen: list[dict[str, Any]] = []
    client = _app(monkeypatch, seen)

    result = _call(client, "save_memo", {"tax_year_id": "ty 7", "body_md": "x"})
    assert result["isError"] is False
    assert seen[0]["url"] == f"{BASE_URL}/clients/tax-years/ty%207/memo"


def test_http_and_stdio_doors_behave_identically_on_probe_list(
    monkeypatch: Any,
) -> None:
    """Guard the SYNC CONTRACT: the vendored HTTP copy and the canonical
    stdio server must agree on refusal vs quoting for the whole probe list.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp"))
    import server as stdio_server  # noqa: E402

    import app.mcp_proxy as http_proxy

    tool = {"name": "save_memo", "route": "PUT /api/v1/clients/tax-years/{tax_year_id}/memo", "scope": "taxplan:advisor"}

    def outcome(module: Any, value: str) -> tuple[str, str]:
        try:
            req = module.build_request(tool, {"tax_year_id": value}, base_url=BASE_URL)
        except ValueError as exc:
            return ("refused", str(exc))
        return ("sent", req["url"])

    probes = list(PROBE_LIST) + ["ty 7", "11111111-2222-4333-8444-555555555555"]
    for probe in probes:
        http_outcome = outcome(http_proxy, probe)
        stdio_outcome = outcome(stdio_server, probe)
        assert http_outcome[0] == stdio_outcome[0], (
            f"probe {probe!r}: http={http_outcome} stdio={stdio_outcome}"
        )
        if http_outcome[0] == "sent":
            assert http_outcome[1] == stdio_outcome[1], (
                f"probe {probe!r}: http={http_outcome} stdio={stdio_outcome}"
            )
