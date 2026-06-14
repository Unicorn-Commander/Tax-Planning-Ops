#!/usr/bin/env python3
"""Tests for the Tax-Planning-Ops MCP server.

Self-contained: NO real network calls are made — the HTTP layer is stubbed.
Runnable two ways:
    pytest mcp/test_server.py
    python mcp/test_server.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make ``server`` importable whether run from repo root or from mcp/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402

BASE = "http://test.local/api/v1"
TOKEN = "test-token-123"
WORKSPACE = "ws-abc-789"


# ---------------------------------------------------------------------------
# (a) tools/list returns ALL tools from tools.json, including the new ones
# ---------------------------------------------------------------------------

# Phase-2 tools that MUST be present after this build.
NEW_TOOLS = {
    "run_strategist",
    "get_memo",
    "save_memo",
    "sign_memo",
    "list_pending_memos",
    "recompute_scenario",
    "emr_sweep",
    "optimize_roth",
    "optimize_scorp",
    "list_tasks",
    "create_task",
    "update_task",
    "list_statutory_deadlines",
    "list_realized",
    "reconcile_realized",
    "realized_rollup",
    "read_journal",
}

# A few legacy tools that must still be present (no regressions).
LEGACY_TOOLS = {
    "create_client",
    "get_extracted_return",
    "create_tax_plan",
    "list_strategy_library",
    "scan_book",
}


def test_tools_list_includes_all_from_tools_json():
    tools = server.load_tools()
    names = {t["name"] for t in tools}

    # Every name in tools.json is surfaced (1:1 — the registry IS tools.json).
    json_names = {
        t["name"] for t in json.loads(server._tools_path().read_text())
    }
    assert names == json_names, "registry must equal tools.json exactly"

    # New Phase-2 tools present.
    missing_new = NEW_TOOLS - names
    assert not missing_new, f"missing new tools: {sorted(missing_new)}"

    # Legacy tools still present.
    missing_legacy = LEGACY_TOOLS - names
    assert not missing_legacy, f"missing legacy tools: {sorted(missing_legacy)}"


def test_manifest_lists_every_tool():
    manifest = json.loads(
        (Path(server.__file__).with_name("manifest.json")).read_text()
    )
    manifest_tools = set(manifest["tools"])
    registry_names = {t["name"] for t in server.load_tools()}
    assert manifest_tools == registry_names, (
        "manifest.tools must match the served tool set; "
        f"only-in-manifest={sorted(manifest_tools - registry_names)} "
        f"only-in-registry={sorted(registry_names - manifest_tools)}"
    )
    assert manifest["version"] == "0.2.0"
    assert manifest["status"] == "phase-9-live"


def test_every_tool_has_description_and_input_schema():
    for t in server.load_tools():
        desc = server.tool_description(t)
        assert desc and t["scope"] in desc, f"{t['name']} description must cite scope"
        schema = server.tool_input_schema(t)
        assert schema["type"] == "object"
        # Each path param is a required property.
        method, path = server.parse_route(t["route"])
        for p in server.path_params(path):
            assert p in schema["properties"], f"{t['name']} schema missing {p}"
            assert p in schema["required"], f"{t['name']} {p} must be required"


# ---------------------------------------------------------------------------
# (b) tools/call builds the correct method+URL+headers+body — NO network
# ---------------------------------------------------------------------------


def _tool(name: str) -> dict:
    return next(t for t in server.load_tools() if t["name"] == name)


def test_build_request_recompute_scenario_post_with_body_and_headers():
    """recompute_scenario must POST to the scenario endpoint with the path id
    substituted, the body forwarded, and bearer + workspace headers set."""
    tax_year_id = "ty-2025-xyz"
    args = {
        "tax_year_id": tax_year_id,
        "set_fields": {"wages": 250000},
        "delta_fields": {"roth_conversion": 40000},
    }
    req = server.build_request(
        _tool("recompute_scenario"),
        args,
        base_url=BASE,
        token=TOKEN,
        workspace_id=WORKSPACE,
    )

    assert req["method"] == "POST"
    assert req["url"] == f"{BASE}/agents/clients/tax-years/{tax_year_id}/scenario"

    # Bearer + workspace headers forwarded verbatim.
    assert req["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert req["headers"][server.WORKSPACE_HEADER] == WORKSPACE
    assert req["headers"]["Content-Type"] == "application/json"

    # Path param consumed (not leaked into the body); body fields preserved.
    assert "tax_year_id" not in req["json"]
    assert req["json"]["set_fields"] == {"wages": 250000}
    assert req["json"]["delta_fields"] == {"roth_conversion": 40000}
    # POST carries no query string here.
    assert req["params"] == {}


def test_build_request_get_routes_args_to_query():
    """A GET tool (list_statutory_deadlines) sends remaining args as query
    params and never sets a JSON body."""
    req = server.build_request(
        _tool("list_statutory_deadlines"),
        {"query": {"tax_year": 2025}},
        base_url=BASE,
        token=TOKEN,
    )
    assert req["method"] == "GET"
    assert req["url"] == f"{BASE}/statutory-deadlines"
    assert req["json"] is None
    assert req["params"] == {"tax_year": 2025}
    # No workspace header when not provided.
    assert server.WORKSPACE_HEADER not in req["headers"]


def test_build_request_path_param_substitution_for_id():
    """save_memo (PUT) substitutes {tax_year_id} and forwards body_md."""
    req = server.build_request(
        _tool("save_memo"),
        {"tax_year_id": "ty-7", "body_md": "# Memo\nbody"},
        base_url=BASE,
        token=TOKEN,
    )
    assert req["method"] == "PUT"
    assert req["url"] == f"{BASE}/clients/tax-years/ty-7/memo"
    assert req["json"] == {"body_md": "# Memo\nbody"}


def test_build_request_missing_path_param_raises():
    try:
        server.build_request(_tool("sign_memo"), {}, base_url=BASE)
    except ValueError as exc:
        assert "memo_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for missing memo_id")


def test_call_tool_makes_no_real_network_call(monkeypatch=None):
    """tools/call path: stub execute_request and assert call_tool wires the
    built request through it — proving no real HTTP egress in tests."""
    captured = {}

    def fake_execute(req, **kwargs):
        captured["req"] = req
        return {"ok": True, "echo": req["url"]}

    # Works under pytest (monkeypatch fixture) and standalone.
    original = server.execute_request
    server.execute_request = fake_execute  # type: ignore[assignment]
    try:
        # Provide env-independent config via build_request defaults: set env.
        import os

        os.environ["TPO_API_URL"] = BASE
        os.environ["TPO_MCP_TOKEN"] = TOKEN
        os.environ["TPO_WORKSPACE_ID"] = WORKSPACE

        result = server.call_tool(
            "optimize_roth", {"tax_year_id": "ty-9"}
        )
    finally:
        server.execute_request = original  # type: ignore[assignment]

    assert result["ok"] is True
    req = captured["req"]
    assert req["method"] == "POST"
    assert req["url"] == f"{BASE}/agents/clients/tax-years/ty-9/optimize/roth"
    assert req["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert req["headers"][server.WORKSPACE_HEADER] == WORKSPACE


# ---------------------------------------------------------------------------
# standalone runner
# ---------------------------------------------------------------------------


def _run_standalone() -> int:
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
