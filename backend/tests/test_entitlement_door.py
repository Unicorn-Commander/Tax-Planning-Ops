"""The door: every authenticated request asks Ops-Center for tax_ops_access.

Drives JWTAuthMiddleware.dispatch directly with a stub Keycloak verifier and a
fake Ops-Center (httpx.MockTransport); no network, no database. A refused
caller gets 403 before any route runs, so no workspace row can be written and
no self-serve workspace is derived. All subjects and hosts are fictional.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core import auth as authmod
from app.core.config import Settings
from app.integrations import control_plane
from app.security.pat import PATRow, generate_secret

OPS_CENTER = "https://ops-center.example.com"
REFUSED = "Tax-Planning-Ops is not included in your plan"
FIRM_WS = UUID("00000000-0000-4000-8000-0000000000f1")


def _body(authorized: bool) -> dict[str, Any]:
    return {
        "org_id": "11111111-2222-4333-8444-555555555555" if authorized else None,
        "org_name": None,
        "display_name": None,
        "slug": None,
        "tier": "professional" if authorized else None,
        "role": "member" if authorized else None,
        "entitlements": ["tax_ops_access"] if authorized else [],
        "authorized": authorized,
    }


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("fictional timeout", request=request)


ANSWERS: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "authorized-false": lambda r: httpx.Response(200, json=_body(False)),
    "401": lambda r: httpx.Response(401, json={"detail": "bad token"}),
    "403": lambda r: httpx.Response(403, json={"detail": "not a member"}),
    "503": lambda r: httpx.Response(
        503, json={"detail": "Organization entitlements are temporarily unavailable."}
    ),
    "timeout": _timeout,
    "malformed": lambda r: httpx.Response(200, content=b"not json"),
}


class _StubVerifier:
    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims

    async def verify(self, token: str) -> dict[str, Any]:
        del token
        return dict(self.claims)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    control_plane.clear_entitlement_cache()


@pytest.fixture
def ops_center(monkeypatch: pytest.MonkeyPatch):
    seen: list[httpx.Request] = []

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(recording)
            return real(*args, **kwargs)

        monkeypatch.setattr(control_plane.httpx, "AsyncClient", factory)
        return seen

    return install


def _settings(enabled: bool = True) -> Settings:
    return Settings(
        ENTITLEMENT_CHECK_ENABLED=enabled,
        OPS_CENTER_URL=OPS_CENTER if enabled else "",
        STANDALONE_MODE=False,
    )


def _request(token: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(b"authorization", f"Bearer {token}".encode())]
    for name, value in (headers or {}).items():
        raw.append((name.lower().encode(), value.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "raw_path": b"/api/v1/me",
            "query_string": b"",
            "headers": raw,
            "server": ("localhost", 8000),
            "scheme": "http",
            "state": {},
            "client": ("127.0.0.1", 1234),
        }
    )


def _dispatch(
    claims: dict[str, Any],
    *,
    enabled: bool = True,
    token: str = "fictional.keycloak.jwt",  # noqa: S107
    headers: dict[str, str] | None = None,
) -> tuple[Response, dict[str, Any]]:
    mw = authmod.JWTAuthMiddleware(
        app=lambda *a, **k: None, settings=_settings(enabled), verifier=_StubVerifier(claims)
    )
    reached: dict[str, Any] = {}

    async def call_next(req: Request) -> Response:
        reached["ctx"] = req.state.auth_context
        return Response(status_code=200)

    return asyncio.run(mw.dispatch(_request(token, headers), call_next)), reached


def _self_serve_claims(sub: str = "fictional-signup-001") -> dict[str, Any]:
    return {"sub": sub, "scope": "openid profile"}


def test_entitled_self_serve_caller_gets_own_workspace(ops_center) -> None:
    seen = ops_center(lambda r: httpx.Response(200, json=_body(True)))
    claims = _self_serve_claims()
    resp, reached = _dispatch(claims)
    assert resp.status_code == 200
    ctx = reached["ctx"]
    assert ctx.workspace_id == authmod.derive_self_serve_workspace(claims)
    assert "taxplan:advisor" in ctx.scopes
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == "Bearer fictional.keycloak.jwt"
    assert seen[0].url.params["feature_key"] == "tax_ops_access"


@pytest.mark.parametrize("answer", sorted(ANSWERS))
def test_refused_self_serve_caller_gets_403_and_no_workspace(
    ops_center, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    ops_center(ANSWERS[answer])

    def _must_not_derive(claims: dict[str, Any]) -> UUID | None:
        raise AssertionError("a refused caller must never be given a self-serve workspace")

    monkeypatch.setattr(authmod, "derive_self_serve_workspace", _must_not_derive)
    resp, reached = _dispatch(_self_serve_claims())
    assert resp.status_code == 403
    assert REFUSED in resp.body.decode()
    # The route (and get_tenant_db's ensure_workspace) never ran.
    assert reached == {}


@pytest.mark.parametrize("answer", ["authorized-false", "403"])
def test_member_with_workspace_claim_whose_org_lost_access_is_403(
    ops_center, answer: str
) -> None:
    ops_center(ANSWERS[answer])
    claims = {
        "sub": "fictional-advisor-777",
        "workspace_id": str(FIRM_WS),
        "scope": "taxplan:advisor",
    }
    resp, reached = _dispatch(claims)
    assert resp.status_code == 403
    assert REFUSED in resp.body.decode()
    assert reached == {}


def test_member_with_workspace_claim_entitled_is_allowed(ops_center) -> None:
    ops_center(lambda r: httpx.Response(200, json=_body(True)))
    claims = {
        "sub": "fictional-advisor-778",
        "workspace_id": str(FIRM_WS),
        "scope": "taxplan:advisor",
    }
    resp, reached = _dispatch(claims)
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == FIRM_WS


def test_refused_header_selection_skips_membership_lookup(
    ops_center, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops_center(ANSWERS["authorized-false"])

    async def _no_db(uc_uid: str, workspace_id: UUID) -> bool:
        raise AssertionError("a refused caller must not reach the membership lookup")

    monkeypatch.setattr(authmod, "is_workspace_member", _no_db)
    resp, reached = _dispatch(
        {"sub": "fictional-advisor-779", "scope": "taxplan:advisor"},
        headers={"X-Workspace-Id": str(FIRM_WS)},
    )
    assert resp.status_code == 403
    assert reached == {}


def test_flag_off_keeps_todays_behaviour(ops_center) -> None:
    seen = ops_center(lambda r: httpx.Response(500))
    claims = _self_serve_claims("fictional-signup-002")
    resp, reached = _dispatch(claims, enabled=False)
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == authmod.derive_self_serve_workspace(claims)
    assert "taxplan:advisor" in reached["ctx"].scopes
    assert seen == []


def test_empty_ops_center_url_with_flag_on_refuses(ops_center) -> None:
    seen = ops_center(lambda r: httpx.Response(200, json=_body(True)))
    mw = authmod.JWTAuthMiddleware(
        app=lambda *a, **k: None,
        settings=Settings(ENTITLEMENT_CHECK_ENABLED=True, OPS_CENTER_URL=""),
        verifier=_StubVerifier(_self_serve_claims("fictional-signup-003")),
    )

    async def call_next(req: Request) -> Response:  # pragma: no cover - must not run
        raise AssertionError("refused caller reached the route")

    resp = asyncio.run(mw.dispatch(_request("fictional.keycloak.jwt"), call_next))
    assert resp.status_code == 403
    assert seen == []


def test_pat_is_never_sent_to_ops_center_and_refused_when_enabled(
    ops_center, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PAT is our credential, not a Keycloak token Ops-Center can verify: it
    must never leave this service. With the check on, a PAT caller is refused
    (fail closed) until a service-side entitlement lookup exists."""
    seen = ops_center(lambda r: httpx.Response(200, json=_body(True)))
    pat = PATRow(
        id=uuid4(),
        owner_uc_uid="fictional-pat-owner",
        name="laptop",
        secret_prefix="tpo_pat_a3f9",  # noqa: S106
        scopes=("taxplan:advisor",),
        workspace_scope=(),
        expires_at=None,
        created_at=datetime.now(UTC),
        last_used_at=None,
        revoked_at=None,
    )

    async def _find(session: Any, token: str) -> PATRow:
        return pat

    async def _touch(pat_id: UUID) -> None:
        return None

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(authmod, "find_active_pat_by_token", _find)
    monkeypatch.setattr(authmod, "_touch_pat_last_used", _touch)
    monkeypatch.setattr(authmod, "async_session_maker", lambda: _Session())
    token = generate_secret()
    resp, reached = _dispatch({}, token=token)
    assert resp.status_code == 403
    assert reached == {}
    assert all(token not in str(r.headers) for r in seen)
    assert seen == []
