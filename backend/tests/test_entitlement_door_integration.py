"""The entitlement door end to end: real app, real Postgres, fake Ops-Center.

An entitled self-serve caller gets 200 on /me and their uuid5(sub) workspace
row; every refused caller (authorized false / 401 / 403 / 503 / timeout /
malformed) gets 403 and NO workspaces or workspace_membership row. A member
whose workspace claim is fine but whose org lost tax_ops_access gets 403. With
the flag off, today's behaviour holds (ship dark first).

Skips unless TPO_TEST_OWNER_DATABASE_URL points at a migrated DB and the app's
DATABASE_URL points at the same DB as the NOBYPASSRLS app role (like
test_me_membership.py). Ops-Center and the Keycloak JWKS are an
httpx.MockTransport: no network. All subjects, orgs and hosts are fictional.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

ISSUER = "https://auth.example.com/realms/uchub"
JWKS_URL = "https://auth.example.com/jwks"
OPS_CENTER = "https://ops-center.example.com"
KID = "fictional-door-kid"
REFUSED = "Tax-Planning-Ops is not included in your plan"
FIRM_NAME = "Fictional Alder Tax Partners"

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_NUMBERS = _PRIVATE.public_key().public_numbers()


def _b64_int(value: int) -> str:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


PUBLIC_JWK = {
    "kty": "RSA",
    "kid": KID,
    "use": "sig",
    "alg": "RS256",
    "n": _b64_int(_NUMBERS.n),
    "e": _b64_int(_NUMBERS.e),
}


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


ENTITLED: Callable[[httpx.Request], httpx.Response] = lambda r: httpx.Response(  # noqa: E731
    200, json=_body(True)
)
REFUSALS: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "authorized-false": lambda r: httpx.Response(200, json=_body(False)),
    "401": lambda r: httpx.Response(401, json={"detail": "bad token"}),
    "403": lambda r: httpx.Response(403, json={"detail": "not a member"}),
    "503": lambda r: httpx.Response(
        503, json={"detail": "Organization entitlements are temporarily unavailable."}
    ),
    "timeout": _timeout,
    "malformed": lambda r: httpx.Response(200, content=b"<html>oops</html>"),
}


def _sign(sub: str, **extra: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": sub,
        "uc_uid": sub,
        "aud": "tax-planning-ops",
        "azp": "tax-planning-ops",
        "iat": now,
        "exp": now + 600,
        "scope": "openid profile",
    }
    claims.update(extra)
    encoded = jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})
    assert isinstance(encoded, str)
    return encoded


def _owner_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_OWNER_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_OWNER_DATABASE_URL not set")
    return dsn


@pytest.fixture
async def admin_conn():
    conn = await asyncpg.connect(_owner_dsn())
    try:
        yield conn
    finally:
        await conn.close()


async def _workspace_rows(admin_conn: Any, workspace_id: UUID) -> int:
    return int(
        await admin_conn.fetchval(
            "SELECT count(*) FROM workspaces WHERE id = $1", str(workspace_id)
        )
    )


async def _membership_rows(admin_conn: Any, uc_uid: str) -> int:
    return int(
        await admin_conn.fetchval(
            "SELECT count(*) FROM workspace_membership WHERE user_uc_uid = $1", uc_uid
        )
    )


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Any]]:
    """Build the real app with the door on/off and a scripted Ops-Center."""
    _owner_dsn()
    import asyncio

    from starlette.testclient import TestClient

    from app.core.config import get_settings
    from app.db.session import close_db
    from app.integrations import control_plane
    from app.main import create_app

    opened: list[TestClient] = []
    ops_calls: list[httpx.Request] = []
    real = httpx.AsyncClient

    def build(*, enabled: bool, ops_center: Callable[[httpx.Request], httpx.Response]) -> Any:
        def route(request: httpx.Request) -> httpx.Response:
            if str(request.url) == JWKS_URL:
                return httpx.Response(200, json={"keys": [PUBLIC_JWK]})
            assert str(request.url).startswith(f"{OPS_CENTER}/api/v1/entitlements")
            ops_calls.append(request)
            return ops_center(request)

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(route)
            return real(*args, **kwargs)

        for key, value in {
            "ENV": "test",
            "STANDALONE_MODE": "false",
            "KEYCLOAK_ISSUER": ISSUER,
            "KEYCLOAK_JWKS_URL": JWKS_URL,
            "KEYCLOAK_CLIENT_ID": "tax-planning-ops",
            "KEYCLOAK_AUDIENCE": "tax-planning-ops",
            "KEYCLOAK_EXPECTED_AUDIENCES": "",
            "MCP_ALLOWED_ORIGINS": "",
            "CORS_ORIGINS": '["http://localhost:3000"]',
            "ENTITLEMENT_CHECK_ENABLED": "true" if enabled else "false",
            "OPS_CENTER_URL": OPS_CENTER if enabled else "",
        }.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(httpx, "AsyncClient", factory)
        control_plane.clear_entitlement_cache()
        get_settings.cache_clear()
        client = TestClient(create_app())
        client.__enter__()
        opened.append(client)
        return client

    build.ops_calls = ops_calls  # type: ignore[attr-defined]
    try:
        yield build
    finally:
        for client in opened:
            client.__exit__(None, None, None)
        asyncio.run(close_db())
        get_settings.cache_clear()


def _me(client: Any, token: str) -> Any:
    return client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})


async def test_entitled_signup_gets_200_and_own_workspace(
    make_client: Any, admin_conn: Any
) -> None:
    from app.core.auth import derive_self_serve_workspace

    sub = f"fictional-entitled-{uuid4()}"
    derived = derive_self_serve_workspace({"sub": sub})
    assert derived is not None
    client = make_client(enabled=True, ops_center=ENTITLED)
    response = _me(client, _sign(sub))
    assert response.status_code == 200, response.text
    assert response.json()["workspace_id"] == str(derived)
    assert await _workspace_rows(admin_conn, derived) == 1
    assert await _membership_rows(admin_conn, sub) == 1
    assert len(make_client.ops_calls) == 1


@pytest.mark.parametrize("answer", sorted(REFUSALS))
async def test_refused_signup_gets_403_and_no_workspace_row(
    make_client: Any, admin_conn: Any, answer: str
) -> None:
    from app.core.auth import derive_self_serve_workspace

    sub = f"fictional-refused-{answer}-{uuid4()}"
    derived = derive_self_serve_workspace({"sub": sub})
    assert derived is not None
    client = make_client(enabled=True, ops_center=REFUSALS[answer])
    response = _me(client, _sign(sub))
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": REFUSED}
    assert await _workspace_rows(admin_conn, derived) == 0
    assert await _membership_rows(admin_conn, sub) == 0


async def test_member_with_workspace_claim_whose_org_lost_access_is_403(
    make_client: Any, admin_conn: Any
) -> None:
    sub = f"fictional-member-{uuid4()}"
    firm_ws = uuid4()
    await admin_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, $2)", str(firm_ws), FIRM_NAME
    )
    await admin_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, $3, 'member')",
        sub,
        str(firm_ws),
        FIRM_NAME,
    )
    token = _sign(sub, workspace_id=str(firm_ws), scope="openid taxplan:advisor")

    client = make_client(enabled=True, ops_center=ENTITLED)
    assert _me(client, token).status_code == 200

    client = make_client(enabled=True, ops_center=REFUSALS["authorized-false"])
    response = _me(client, token)
    assert response.status_code == 403
    assert response.json() == {"detail": REFUSED}
    # The firm's data is untouched; the caller just can't reach it.
    assert await _workspace_rows(admin_conn, firm_ws) == 1
    assert await _membership_rows(admin_conn, sub) == 1


async def test_flag_off_keeps_todays_self_serve_behaviour(
    make_client: Any, admin_conn: Any
) -> None:
    from app.core.auth import derive_self_serve_workspace

    sub = f"fictional-dark-{uuid4()}"
    derived = derive_self_serve_workspace({"sub": sub})
    assert derived is not None
    client = make_client(enabled=False, ops_center=REFUSALS["authorized-false"])
    response = _me(client, _sign(sub))
    assert response.status_code == 200, response.text
    assert response.json()["workspace_id"] == str(derived)
    assert await _workspace_rows(admin_conn, derived) == 1
    assert make_client.ops_calls == []
