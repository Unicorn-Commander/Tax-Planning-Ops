"""TPO-CLIENT-1: a PAT reaches only the workspaces its row declares.

Drives JWTAuthMiddleware.dispatch directly with a stubbed PAT lookup, a
stubbed membership lookup and the entitlement flag OFF (the default; a PAT has
no user bearer for Ops-Center to verify, so with the flag on it is refused
before this fence is ever reached). No network, no database: the PAT row and
the membership answer are in-memory. All subjects, orgs and hosts are
fictional.

Red on base d04fedce (that base's app/core/auth.py): the PAT branch claims only
workspace_scope[0] (auth.py:252-255) and the 403 fallback authorizes the
X-Workspace-Id header against the OWNER's membership, never against the PAT's
declared scope (auth.py:286-299). A PAT minted for one client workspace reads
every other workspace its owner belongs to.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core import auth as authmod
from app.core.config import Settings
from app.security.pat import PATRow, generate_secret

OWNER = "fictional-pat-owner"
WS_A = UUID("00000000-0000-4000-8000-0000000000aa")
WS_B = UUID("00000000-0000-4000-8000-0000000000ab")
WS_C = UUID("00000000-0000-4000-8000-0000000000ac")


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _settings() -> Settings:
    return Settings(ENTITLEMENT_CHECK_ENABLED=False, STANDALONE_MODE=False)


def _pat(
    workspace_scope: tuple[UUID, ...] | None = None,
    scopes: tuple[str, ...] = ("taxplan:advisor",),  # noqa: B006
) -> PATRow:
    return PATRow(
        id=uuid4(),
        owner_uc_uid=OWNER,
        name="fictional-laptop",
        secret_prefix="tpo_pat_f1c0",  # noqa: S106
        scopes=scopes,
        workspace_scope=workspace_scope,
        expires_at=None,
        created_at=datetime.now(UTC),
        last_used_at=None,
        revoked_at=None,
    )


@pytest.fixture
def pat_dispatch(monkeypatch: pytest.MonkeyPatch):
    def install(
        pat: PATRow, member_of: frozenset[UUID] = frozenset({WS_A, WS_B})
    ) -> tuple[Request, Any]:
        """Patch the PAT lookup and the membership answer; return a ready
        (request, call_next) pair for a request authenticated with this PAT."""

        async def _find(session: Any, token: str) -> PATRow | None:
            return pat if token == _token else None

        async def _touch(pat_id: UUID) -> None:
            return None

        async def _member(uc_uid: str, workspace_id: UUID) -> bool:
            return uc_uid == OWNER and workspace_id in member_of

        monkeypatch.setattr(authmod, "find_active_pat_by_token", _find)
        monkeypatch.setattr(authmod, "_touch_pat_last_used", _touch)
        monkeypatch.setattr(authmod, "async_session_maker", lambda: _Session())
        monkeypatch.setattr(authmod, "is_workspace_member", _member)
        headers = {
            "X-Workspace-Id": str(WS_B),
        }
        return _request(headers), _settings()

    return install


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(b"authorization", f"Bearer {_token}".encode())]
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


_token = generate_secret()


def _dispatch(mw_settings: Settings, headers: dict[str, str] | None) -> tuple[Response, dict[str, Any]]:
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=mw_settings)
    reached: dict[str, Any] = {}

    async def call_next(req: Request) -> Response:
        reached["ctx"] = req.state.auth_context
        return Response(status_code=200)

    return asyncio.run(
        mw.dispatch(_request(headers), call_next)
    ), reached


def test_pat_scoped_to_a_selecting_b_is_403(pat_dispatch) -> None:
    """A PAT whose declared scope is [A] must not read B, even though its
    owner is a member of B (the base authorizes the header against the
    owner's membership, not the PAT's scope)."""
    req, settings = pat_dispatch(_pat((WS_A,)))
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(req, call_next))
    assert resp.status_code == 403
    assert reached == {}


def test_pat_scoped_to_a_selecting_a_is_200(pat_dispatch) -> None:
    req, settings = pat_dispatch(_pat((WS_A,)))
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    # Re-point the header at the PAT's own workspace A.
    async def patched(req: Request, call_next: Any) -> Response:
        return await call_next(req)

    resp = asyncio.run(mw.dispatch(_request({"X-Workspace-Id": str(WS_A)}), call_next))
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == WS_A


def test_pat_scoped_a_b_selecting_b_is_200(pat_dispatch) -> None:
    req, settings = pat_dispatch(_pat((WS_A, WS_B)))
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(req, call_next))
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == WS_B


def test_pat_scoped_to_a_after_owner_removed_from_a_is_403(pat_dispatch) -> None:
    req, settings = pat_dispatch(_pat((WS_A,)), member_of=frozenset({WS_B}))
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(_request({"X-Workspace-Id": str(WS_A)}), call_next))
    assert resp.status_code == 403
    assert reached == {}


def test_pat_with_empty_scope_is_refused(pat_dispatch) -> None:
    """Fail closed: a PAT row without a declared workspace_scope cannot enter
    any workspace."""
    req, settings = pat_dispatch(_pat(None))
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(req, call_next))
    assert resp.status_code == 403
    assert reached == {}


def test_pat_scoped_to_a_selecting_c_is_403_even_if_scoped_entry(
    pat_dispatch,
) -> None:
    """The fence checks the PAT's declared entries, not just [0]: C is outside
    [A, B] even though the owner is a member of C."""
    req, settings = pat_dispatch(
        _pat((WS_A, WS_B)), member_of=frozenset({WS_A, WS_B, WS_C})
    )
    mw = authmod.JWTAuthMiddleware(app=lambda *a, **k: None, settings=settings)
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    resp = asyncio.run(mw.dispatch(_request({"X-Workspace-Id": str(WS_C)}), call_next))
    assert resp.status_code == 403
    assert reached == {}


class _HumanVerifier:
    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims

    async def verify(self, token: str) -> dict[str, Any]:
        del token
        return dict(self.claims)


def test_human_session_selecting_b_is_unchanged(
    pat_dispatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The membership fallback still authorizes a real Keycloak session's
    header selection against the owner's membership (PAT behaviour only)."""
    claims = {
        "sub": OWNER,
        "uc_uid": OWNER,
        "workspace_id": str(WS_A),
        "scope": "taxplan:advisor",
    }
    req, _ = pat_dispatch(_pat((WS_A,)))
    mw = authmod.JWTAuthMiddleware(
        app=lambda *a, **k: None, settings=_settings(), verifier=_HumanVerifier(claims)
    )
    reached: dict[str, Any] = {}

    async def call_next(request: Request) -> Response:
        reached["ctx"] = request.state.auth_context
        return Response(status_code=200)

    human = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "raw_path": b"/api/v1/me",
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer fictional.keycloak.jwt"),
                (b"x-workspace-id", str(WS_B).encode()),
            ],
            "server": ("localhost", 8000),
            "scheme": "http",
            "state": {},
            "client": ("127.0.0.1", 1234),
        }
    )
    resp = asyncio.run(mw.dispatch(human, call_next))
    assert resp.status_code == 200
    assert reached["ctx"].workspace_id == WS_B
