"""TPO-MACH-1: a machine (M2M) token can never self-serve a tenant.

A service-account token that passes the audience check carries no ``uc_uid``,
so the principal falls back to ``sub`` and the self-serve path provisions a
``uuid5(sub)`` workspace plus an owner membership FOR THE MACHINE (the JIT
write in ``get_tenant_db``). The fix: before the self-serve path runs, require
``caller_is_user_principal``; a non-user principal gets the app's existing
403 shape and the route — and therefore every workspace/membership write —
never runs.

Drives ``JWTAuthMiddleware.dispatch`` directly with a stub verifier and a
fake Ops-Center (httpx.MockTransport): no network, no database. "Zero
workspace/membership rows" is proven the same way the entitlement-door tests
prove it: the write happens only in the route dependency (``get_tenant_db``),
and the refused caller never reaches the route (``reached == {}``). All
principals and hosts are fictional.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from app.core import auth as authmod
from app.core.auth import WORKSPACE_HEADER
from app.core.config import Settings
from app.integrations import control_plane

OPS_CENTER = "https://ops-center.example.com"
ORG_A = "11111111-2222-4333-8444-555555555555"
FIRM_WS = UUID("00000000-0000-4000-8000-0000000000f1")
SERVICE_AUDIENCE = "accounting-ops"


def _body() -> dict[str, Any]:
    return {
        "org_id": ORG_A,
        "org_name": None,
        "display_name": None,
        "slug": None,
        "tier": "professional",
        "role": "member",
        "entitlements": ["tax_ops_access"],
        "authorized": True,
    }


class _StubVerifier:
    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims

    async def verify(self, token: str) -> dict[str, Any]:
        del token
        return dict(self.claims)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    getattr(control_plane, "clear_entitlement_cache", lambda: None)()


@pytest.fixture(autouse=True)
def bound_orgs(monkeypatch: pytest.MonkeyPatch) -> dict[UUID, UUID]:
    """Server-side workspace -> org binding, stubbed: FIRM_WS belongs to org A."""
    bound: dict[UUID, UUID] = {FIRM_WS: UUID(ORG_A)}

    async def _workspace_org(workspace_id: UUID) -> UUID | None:
        return bound.get(workspace_id)

    monkeypatch.setattr(authmod, "workspace_org", _workspace_org, raising=False)
    return bound


@pytest.fixture(autouse=True)
def ops_center(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """A fake Ops-Center that always entitles the caller (the machine token
    must be refused by the identity gate, not by the door). Returns the list
    of requests it actually received."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_body())

    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(recording)
        return real(*args, **kwargs)

    monkeypatch.setattr(control_plane.httpx, "AsyncClient", factory)
    return seen


def _settings() -> Settings:
    return Settings(
        ENTITLEMENT_CHECK_ENABLED=True,
        OPS_CENTER_URL=OPS_CENTER,
        STANDALONE_MODE=False,
        ACCOUNTING_OPS_AUDIENCE=SERVICE_AUDIENCE,
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
        app=lambda *a, **k: None, settings=_settings(), verifier=_StubVerifier(claims)
    )
    if not enabled:
        mw.settings = Settings(
            ENTITLEMENT_CHECK_ENABLED=False,
            OPS_CENTER_URL="",
            STANDALONE_MODE=False,
            ACCOUNTING_OPS_AUDIENCE=SERVICE_AUDIENCE,
        )
    reached: dict[str, Any] = {}

    async def call_next(req: Request) -> Response:
        reached["ctx"] = req.state.auth_context
        return Response(status_code=200)

    req = _request(token, headers)
    return asyncio.run(mw.dispatch(req, call_next)), reached


def _machine_claims() -> dict[str, Any]:
    """Keycloak client-credentials shape: azp + client_id only, no uc_uid,
    no sid. Passes the audience check (it is TPO's own audience) but has no
    end-user identity."""
    return {
        "sub": "service-account-fictional-m2m-client",
        "preferred_username": "service-account-fictional-m2m-client",
        "azp": SERVICE_AUDIENCE,
        "client_id": "fictional-m2m-client",
        "scope": "openid",
    }


def _human_claims(sub: str = "fictional-signup-001") -> dict[str, Any]:
    """A real advisor token: uc_uid (realm default mapper), login-client azp."""
    return {
        "sub": sub,
        "uc_uid": sub,
        "azp": "tax-planning-ops",
        "preferred_username": f"{sub}@example.com",
        "scope": "openid profile",
    }


# --- machine principal: refused, and nothing is written -----------------------


def test_machine_token_self_serve_is_403_and_route_never_runs() -> None:
    resp, reached = _dispatch(_machine_claims())
    assert resp.status_code == 403
    # The route (and get_tenant_db's ensure_home_membership/ensure_workspace)
    # never ran: zero workspace rows, zero membership rows.
    assert reached == {}
    body = json.loads(resp.body.decode())
    assert isinstance(body["detail"], str) and body["detail"]
    # Same {"detail": ...} shape as the app's other middleware 403s, plus the
    # onboarding link (env var with a safe default).
    assert body["onboarding_url"].startswith("https://")


def test_machine_token_self_serve_refused_with_door_flag_off() -> None:
    """The gate is independent of the entitlement door: flag off (today's
    permissive behaviour for humans) must still refuse a machine self-serve."""
    resp, reached = _dispatch(_machine_claims(), enabled=False)
    assert resp.status_code == 403
    assert reached == {}


def test_machine_refusal_happens_before_the_ops_center_call(
    ops_center: list[httpx.Request],
) -> None:
    """F4 ordering: with the door ON, a machine bearer that the identity gate
    will refuse must never be presented to Ops-Center — the gate runs first
    and the refusal writes nothing."""
    resp, reached = _dispatch(_machine_claims())
    assert resp.status_code == 403
    assert reached == {}
    assert ops_center == []


def test_machine_token_onboarding_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(authmod.ONBOARDING_URL_ENV, "https://example.com/get-started")
    resp, _ = _dispatch(_machine_claims())
    assert resp.status_code == 403
    assert json.loads(resp.body.decode())["onboarding_url"] == "https://example.com/get-started"


def test_machine_token_with_workspace_claim_is_unchanged() -> None:
    """Managed path (explicit workspace claim) is NOT self-serve: a service
    token's existing behaviour there is unchanged (no gate, no new 403)."""
    claims = {**_machine_claims(), "workspace_id": str(FIRM_WS)}
    resp, reached = _dispatch(claims)
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == FIRM_WS


# --- human principal: self-serve unchanged ------------------------------------


def test_human_token_self_serve_unchanged() -> None:
    claims = _human_claims()
    resp, reached = _dispatch(claims)
    assert resp.status_code == 200
    ctx = reached["ctx"]
    assert ctx.workspace_id == authmod.derive_self_serve_workspace(claims)
    assert "taxplan:advisor" in ctx.scopes
    assert ctx.uc_uid == claims["uc_uid"]


def test_human_token_already_self_served_is_unchanged(bound_orgs: dict[UUID, UUID]) -> None:
    """A human whose derived workspace already exists (server-side org binding
    = already provisioned, the caller already a member) keeps self-serving:
    same workspace, same 200, twice."""
    claims = _human_claims("fictional-signup-002")
    derived = authmod.derive_self_serve_workspace(claims)
    assert derived is not None
    bound_orgs[derived] = UUID(ORG_A)
    first, reached_first = _dispatch(claims)
    assert first.status_code == 200
    assert reached_first["ctx"].workspace_id == derived
    second, reached_second = _dispatch(claims)
    assert second.status_code == 200
    assert reached_second["ctx"].workspace_id == derived
    assert "taxplan:advisor" in reached_second["ctx"].scopes


# --- F1: the gate covers the WHOLE self-serve flow, not just the derived ws ----


def test_machine_token_header_plus_membership_is_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: a machine token with NO workspace claim must not enter the
    self-serve flow through the membership fallback either. Precondition the
    reviewer proved reachable: the machine's `sub` already has a membership
    row (an owner added a service-account-* uc_uid, or the machine created
    workspaces before this fix). Sending X-Workspace-Id for that workspace
    used to skip the old `workspace_id == derived` gate and mint an
    AuthContext with `taxplan:advisor` for the machine — the scope the
    create-workspace writers need. The whole flow is now user-only."""

    async def _member(uc_uid: str, workspace_id: UUID) -> bool:
        assert uc_uid == "service-account-fictional-m2m-client"
        return True

    monkeypatch.setattr(authmod, "is_workspace_member", _member)
    resp, reached = _dispatch(
        _machine_claims(),
        enabled=False,
        headers={WORKSPACE_HEADER: str(FIRM_WS)},
    )
    assert resp.status_code == 403
    assert reached == {}
    body = json.loads(resp.body.decode())
    assert body["detail"] == authmod.NO_USER_PRINCIPAL_DETAIL


def test_human_token_header_plus_membership_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same header+membership path for a HUMAN (uc_uid, login-client azp)
    is unchanged: 200, the selected workspace, self-serve scopes."""

    async def _member(uc_uid: str, workspace_id: UUID) -> bool:
        return True

    monkeypatch.setattr(authmod, "is_workspace_member", _member)
    resp, reached = _dispatch(
        _human_claims("fictional-signup-003"),
        enabled=False,
        headers={WORKSPACE_HEADER: str(FIRM_WS)},
    )
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == FIRM_WS
    assert "taxplan:advisor" in reached["ctx"].scopes


# --- F1: the create-workspace writers refuse a machine principal ---------------


def _no_db(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    """Any DB session opened by `module` fails the test: a refused caller
    must not get anywhere near a workspace/membership write."""

    def _boom() -> Any:
        raise AssertionError("a refused principal must not open a DB session")

    monkeypatch.setattr(module, "async_session_maker", _boom)


def test_create_workspace_refuses_machine_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import workspaces as workspaces_mod
    from app.services.workspaces import create_workspace

    _no_db(monkeypatch, workspaces_mod)
    with pytest.raises(PermissionError):
        asyncio.run(
            create_workspace(
                uc_uid="service-account-fictional-m2m-client",
                name="Machine Tenant",
                claims=_machine_claims(),
            )
        )


def test_load_demo_workspace_refuses_machine_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import demo_seed as demo_seed_mod
    from app.services.demo_seed import load_demo_workspace

    _no_db(monkeypatch, demo_seed_mod)
    with pytest.raises(PermissionError):
        asyncio.run(
            load_demo_workspace(
                uc_uid="service-account-fictional-m2m-client",
                claims=_machine_claims(),
            )
        )


# --- F2: BRIGADE_CLIENT_ID must never equal the login client -------------------


def test_brigade_client_id_equal_to_login_client_refused_at_startup() -> None:
    """F2: BRIGADE_CLIENT_ID joins the service-principal azp denylist that
    caller_is_user_principal checks before self-serve. Users log in through
    KEYCLOAK_CLIENT_ID, so an operator setting the exchange client to that
    same id would 403 every real human self-serve login. The app must refuse
    to start that way instead of breaking login at runtime."""
    with pytest.raises(ValidationError, match="BRIGADE_CLIENT_ID"):
        Settings(
            KEYCLOAK_CLIENT_ID="tax-planning-ops",
            BRIGADE_CLIENT_ID="tax-planning-ops",
        )


def test_brigade_client_id_distinct_or_unset_allowed() -> None:
    """A distinct exchange client, and the unset default (the exchange falls
    back to TPO's KC client), both start fine."""
    assert Settings(BRIGADE_CLIENT_ID="brigade-exchange").BRIGADE_CLIENT_ID == (
        "brigade-exchange"
    )
    assert Settings().BRIGADE_CLIENT_ID == ""
