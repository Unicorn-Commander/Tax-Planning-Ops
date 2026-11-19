"""GET /me must never write a membership for a claimed workspace.

``ensure_home_membership`` (called from GET /me for the active workspace) may
only INSERT for the caller's OWN self-serve workspace (uuid5 of sub); for any
claimed workspace — the token's workspace_id claim, a PAT's workspace_scope, or
a header-selected workspace — it must write nothing and change no role.
Skips unless TPO_TEST_DATABASE_URL points at a migrated DB whose DSN
authenticates as the NOBYPASSRLS tax_planning_ops_app role (like
test_rls_integration.py). All subjects and workspace names are fictional.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

ISSUER = "https://auth.example.com/realms/uchub"
KID = "fictional-test-kid"
FIRM_NAME = "Fictional Cedar Tax Group"

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_NUMBERS = _PRIVATE.public_key().public_numbers()


def _b64_int(value: int) -> str:
    length = max(1, (value.bit_length() + 7) // 8)
    raw = value.to_bytes(length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


PUBLIC_JWK = {
    "kty": "RSA",
    "kid": KID,
    "use": "sig",
    "alg": "RS256",
    "n": _b64_int(_NUMBERS.n),
    "e": _b64_int(_NUMBERS.e),
}


def _owner_dsn() -> str:
    dsn = os.environ.get("TPO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TPO_TEST_DATABASE_URL not set")
    return dsn.replace("tax_planning_ops_app:dev", "tax_planning_ops_owner:dev")


class _JWKSResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"keys": [PUBLIC_JWK]}


class _JWKSClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _JWKSClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        del exc
        return False

    async def get(self, url: str) -> _JWKSResponse:
        del url
        return _JWKSResponse()


def _sign(claims: dict[str, Any]) -> str:
    encoded = jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})
    assert isinstance(encoded, str)
    return encoded


def _claims(*, sub: str, **extra: Any) -> dict[str, Any]:
    now = int(time.time())
    body: dict[str, Any] = {
        "iss": ISSUER,
        "sub": sub,
        "uc_uid": sub,
        "aud": "tax-planning-ops",
        "azp": "tax-planning-ops",
        "iat": now,
        "exp": now + 600,
        "scope": "openid profile taxplan:advisor",
    }
    body.update(extra)
    return body


async def _seed_workspace(admin_conn: Any, workspace_id: UUID) -> None:
    await admin_conn.execute(
        "INSERT INTO workspaces (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
        str(workspace_id),
        FIRM_NAME,
    )


async def _seed_membership(
    admin_conn: Any, uc_uid: str, workspace_id: UUID, role: str
) -> None:
    await admin_conn.execute(
        "INSERT INTO workspace_membership "
        "(id, user_uc_uid, workspace_id, workspace_name, role) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4)",
        uc_uid,
        str(workspace_id),
        FIRM_NAME,
        role,
    )


async def _get_me(
    client: Any,
    *,
    sub: str,
    workspace_id: UUID | None = None,
    workspaces: list[dict[str, str]] | None = None,
    header_workspace: UUID | None = None,
) -> dict[str, Any]:
    """GET /me for a token for `sub`; returns the response payload."""
    extra: dict[str, Any] = {}
    if workspace_id is not None:
        extra["workspace_id"] = str(workspace_id)
    if workspaces:
        extra["workspaces"] = workspaces
    token = _sign(_claims(sub=sub, **extra))
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if header_workspace is not None:
        headers["X-Workspace-Id"] = str(header_workspace)
    response = client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _membership_for(admin_conn: Any, uc_uid: str, workspace_id: UUID) -> list[dict[str, Any]]:
    rows = await admin_conn.fetch(
        "SELECT user_uc_uid, workspace_id, workspace_name, role "
        "FROM workspace_membership WHERE deleted_at IS NULL"
    )
    return [
        {
            "role": r["role"],
            "workspace_id": r["workspace_id"],
            "workspace_name": r["workspace_name"],
        }
        for r in rows
        if r["user_uc_uid"] == uc_uid and r["workspace_id"] == workspace_id
    ]


@pytest.fixture
async def admin_conn():
    owner_dsn = _owner_dsn()
    conn = await asyncpg.connect(owner_dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("STANDALONE_MODE", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.taxplanningops.example")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "https://auth.example.com/jwks")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "tax-planning-ops")
    monkeypatch.setenv("KEYCLOAK_AUDIENCE", "tax-planning-ops")
    monkeypatch.setenv("KEYCLOAK_EXPECTED_AUDIENCES", "")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("ENTITLEMENT_CHECK_ENABLED", "false")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    import app.integrations.keycloak as kc
    from app.core.config import get_settings
    from app.db.session import close_db
    from app.main import create_app

    monkeypatch.setattr(kc.httpx, "AsyncClient", _JWKSClient)
    get_settings.cache_clear()
    try:
        from starlette.testclient import TestClient

        with TestClient(create_app()) as c:
            yield c
    finally:
        import asyncio

        asyncio.run(close_db())
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_me_claimed_workspace_creates_no_membership(
    client: Any, admin_conn: Any
) -> None:
    """A token whose workspace_id claim names another firm's workspace must not
    turn the claim into an owner row on /me."""
    sub = "fictional-advisor-001"
    other_ws = uuid4()
    await _seed_workspace(admin_conn, other_ws)
    payload = await _get_me(client, sub=sub, workspace_id=other_ws)
    assert payload["workspace_id"] == str(other_ws)
    assert await _membership_for(admin_conn, sub, other_ws) == []


@pytest.mark.asyncio
async def test_me_header_selected_workspace_creates_no_membership(
    client: Any, admin_conn: Any
) -> None:
    """A header-selected workspace the caller merely belongs to (member, not
    owner) must not gain a role change or a second row on /me."""
    sub = "fictional-advisor-002"
    firm_ws = uuid4()
    await _seed_workspace(admin_conn, firm_ws)
    await _seed_membership(admin_conn, sub, firm_ws, "member")
    payload = await _get_me(
        client,
        sub=sub,
        workspaces=[{"workspaceId": str(firm_ws)}],
        header_workspace=firm_ws,
    )
    assert payload["workspace_id"] == str(firm_ws)
    assert await _membership_for(admin_conn, sub, firm_ws) == [
        {"role": "member", "workspace_id": firm_ws, "workspace_name": FIRM_NAME}
    ]


@pytest.mark.asyncio
async def test_me_self_serve_creates_own_workspace_owner_once(
    client: Any, admin_conn: Any
) -> None:
    """A self-serve user (no workspace claim) gets their derived uuid5(sub)
    workspace as owner exactly once — idempotent across /me calls."""
    from app.core.auth import derive_self_serve_workspace

    sub = "fictional-selfserve-003"
    derived = derive_self_serve_workspace({"sub": sub})
    assert derived is not None

    first = await _get_me(client, sub=sub)
    assert first["workspace_id"] == str(derived)
    assert {w["workspaceId"] for w in first["workspaces"]} == {str(derived)}
    assert [w["role"] for w in first["workspaces"] if w["workspaceId"] == str(derived)] == ["owner"]

    rows_after_first = await _membership_for(admin_conn, sub, derived)
    assert len(rows_after_first) == 1
    assert rows_after_first[0]["role"] == "owner"

    second = await _get_me(client, sub=sub)
    assert second["workspace_id"] == str(derived)
    assert await _membership_for(admin_conn, sub, derived) == rows_after_first


@pytest.mark.asyncio
async def test_me_existing_member_role_unchanged(client: Any, admin_conn: Any) -> None:
    """An existing member's role is never changed by /me, whatever workspace the
    token claims."""
    sub = "fictional-advisor-004"
    other_ws = uuid4()
    await _seed_workspace(admin_conn, other_ws)
    await _seed_membership(admin_conn, sub, other_ws, "member")
    await _get_me(client, sub=sub, workspace_id=other_ws)
    assert await _membership_for(admin_conn, sub, other_ws) == [
        {"role": "member", "workspace_id": other_ws, "workspace_name": FIRM_NAME}
    ]
