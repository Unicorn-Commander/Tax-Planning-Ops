"""Unit tests for the PAT service, the vendored MCP proxy helpers, and the
middleware PAT auth branch. None of these touch a real database or Keycloak —
the DB-backed mint/list/revoke round-trip is curl-verified against the deployed
backend (see the deploy notes)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.security.pat import (
    MAX_TTL_DAYS,
    PAT_PREFIX,
    PATRow,
    generate_secret,
    hash_secret,
    looks_like_pat,
    resolve_ttl,
    secret_prefix,
    validate_scopes,
)

# ---------------------------------------------------------------------------
# PAT primitives
# ---------------------------------------------------------------------------


def test_generate_secret_shape() -> None:
    raw = generate_secret()
    assert raw.startswith(PAT_PREFIX)
    assert 44 <= len(raw) <= 80
    assert secret_prefix(raw) == raw[:12]


def test_hash_secret_is_deterministic_32_bytes() -> None:
    raw = generate_secret()
    h1 = hash_secret(raw)
    h2 = hash_secret(raw)
    assert h1 == h2
    assert isinstance(h1, bytes) and len(h1) == 32
    assert hash_secret(generate_secret()) != h1  # different token, different hash


def test_looks_like_pat() -> None:
    assert looks_like_pat(generate_secret())
    assert looks_like_pat(f"{PAT_PREFIX}{'a' * 43}")
    # Not ours / malformed.
    assert not looks_like_pat("")
    assert not looks_like_pat("Bearer xyz")
    assert not looks_like_pat("aops_pat_" + "a" * 43)  # sibling app's prefix
    assert not looks_like_pat(PAT_PREFIX + "short")
    assert not looks_like_pat("eyJhbGciOi.some.jwt")  # a JWT is not a PAT


def test_validate_scopes_none_returns_all_sorted() -> None:
    owner = {"taxplan:admin", "taxplan:advisor"}
    assert validate_scopes(None, owner) == ("taxplan:admin", "taxplan:advisor")


def test_validate_scopes_subset_ok() -> None:
    owner = {"taxplan:advisor", "taxplan:admin"}
    assert validate_scopes(["taxplan:advisor"], owner) == ("taxplan:advisor",)


def test_validate_scopes_rejects_widening() -> None:
    with pytest.raises(ValueError):
        validate_scopes(["taxplan:admin"], {"taxplan:advisor"})


def test_resolve_ttl_variants() -> None:
    assert resolve_ttl(None) is None
    assert resolve_ttl(0) is None
    with pytest.raises(ValueError):
        resolve_ttl(-1)
    with pytest.raises(ValueError):
        resolve_ttl(MAX_TTL_DAYS + 1)
    exp = resolve_ttl(30)
    assert exp is not None
    delta = exp - datetime.now(UTC)
    assert timedelta(days=29) < delta <= timedelta(days=30)


# ---------------------------------------------------------------------------
# Vendored MCP proxy helpers (must mirror mcp/server.py)
# ---------------------------------------------------------------------------


def test_proxy_build_request_get_with_path_and_query() -> None:
    from app.mcp_proxy import build_request

    tool = {"name": "get_extracted_return", "route": "GET /api/v1/extracted-returns/{id}"}
    req = build_request(
        tool,
        {"id": "abc", "query": {"expand": "fields"}},
        base_url="http://localhost:8000/api/v1",
        token="tpo_pat_secret",  # noqa: S106
        workspace_id="ws-1",
    )
    assert req["method"] == "GET"
    assert req["url"] == "http://localhost:8000/api/v1/extracted-returns/abc"
    assert req["params"] == {"expand": "fields"}
    assert req["json"] is None
    assert req["headers"]["Authorization"] == "Bearer tpo_pat_secret"
    assert req["headers"]["X-Workspace-Id"] == "ws-1"
    assert req["headers"]["X-UC-Door"] == "mcp"


def test_proxy_build_request_post_body_merge() -> None:
    from app.mcp_proxy import build_request

    tool = {"name": "create_client", "route": "POST /api/v1/clients"}
    req = build_request(
        tool,
        {"name": "Acme", "body": {"entity_type": "s_corp"}},
        base_url="http://localhost:8000/api/v1",
        token="t",  # noqa: S106
    )
    assert req["method"] == "POST"
    assert req["url"] == "http://localhost:8000/api/v1/clients"
    assert req["json"] == {"name": "Acme", "entity_type": "s_corp"}


def test_proxy_missing_path_param_raises() -> None:
    from app.mcp_proxy import build_request

    tool = {"name": "get_extracted_return", "route": "GET /api/v1/extracted-returns/{id}"}
    with pytest.raises(ValueError):
        build_request(tool, {}, base_url="http://localhost:8000/api/v1")


def test_proxy_input_schema_requires_path_param() -> None:
    from app.mcp_proxy import tool_input_schema

    schema = tool_input_schema(
        {"name": "x", "route": "PATCH /api/v1/plans/{id}/assumptions"}
    )
    assert schema["type"] == "object"
    assert "id" in schema["properties"]
    assert schema["required"] == ["id"]
    assert "body" in schema["properties"]  # write method gets a body bag


def test_proxy_join_url_collapses_duplicate_prefix() -> None:
    from app.mcp_proxy import join_url

    assert (
        join_url("http://localhost:8000/api/v1", "/api/v1/clients")
        == "http://localhost:8000/api/v1/clients"
    )


def test_vendored_tools_match_canonical() -> None:
    """The vendored backend copy must equal the canonical mcp/tools.json."""
    import json
    from pathlib import Path

    from app import mcp_proxy

    vendored = mcp_proxy.load_tools()
    canonical_path = (
        Path(mcp_proxy.__file__).resolve().parents[2] / "mcp" / "tools.json"
    )
    canonical = json.loads(canonical_path.read_text())
    assert {t["name"] for t in vendored} == {t["name"] for t in canonical}


# ---------------------------------------------------------------------------
# Middleware PAT auth branch (monkeypatched — no DB, no Keycloak)
# ---------------------------------------------------------------------------


class _DummySession:
    async def execute(self, *a, **k):  # pragma: no cover - touch is best-effort
        return None

    async def commit(self):  # pragma: no cover
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _dummy_session_maker():
    return _DummySession()


def _build_request(token: str, path: str = "/api/v1/me"):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "server": ("localhost", 8000),
        "scheme": "http",
        "state": {},
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope)


class _StubVerifier:
    async def verify(self, token: str):  # pragma: no cover - not hit for PATs
        raise AssertionError("Keycloak verify must NOT run for a tpo_pat_ token")


def _make_middleware(monkeypatch, pat_row: PATRow | None):
    from app.core import auth as authmod
    from app.core.config import Settings

    async def _find(session, token):
        return pat_row

    monkeypatch.setattr(authmod, "find_active_pat_by_token", _find)
    monkeypatch.setattr(authmod, "async_session_maker", _dummy_session_maker)

    async def _touch(pat_id):
        return None

    monkeypatch.setattr(authmod, "_touch_pat_last_used", _touch)

    settings = Settings()  # ENTITLEMENT_CHECK_ENABLED defaults False -> entitled
    return authmod.JWTAuthMiddleware(
        app=lambda *a, **k: None, settings=settings, verifier=_StubVerifier()
    )


def test_middleware_pat_branch_authenticates(monkeypatch) -> None:
    ws = uuid4()
    pat = PATRow(
        id=uuid4(),
        owner_uc_uid="uc-user-1",
        name="laptop",
        secret_prefix="tpo_pat_a3f9",  # noqa: S106
        scopes=("taxplan:advisor",),
        workspace_scope=(ws,),
        expires_at=None,
        created_at=datetime.now(UTC),
        last_used_at=None,
        revoked_at=None,
    )
    mw = _make_middleware(monkeypatch, pat)
    token = generate_secret()
    request = _build_request(token)

    captured = {}

    async def call_next(req):
        from starlette.responses import Response

        captured["ctx"] = req.state.auth_context
        captured["via_pat"] = getattr(req.state, "auth_via_pat", False)
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(request, call_next))
    assert resp.status_code == 200
    ctx = captured["ctx"]
    assert ctx.uc_uid == "uc-user-1"
    assert ctx.workspace_id == ws
    assert ctx.scopes == {"taxplan:advisor"}
    assert captured["via_pat"] is True


def test_middleware_bad_pat_is_401_without_keycloak(monkeypatch) -> None:
    mw = _make_middleware(monkeypatch, None)  # lookup miss
    request = _build_request(generate_secret())

    async def call_next(req):  # pragma: no cover - must not be reached
        raise AssertionError("must not reach downstream on a bad PAT")

    resp = asyncio.run(mw.dispatch(request, call_next))
    assert resp.status_code == 401
