"""MCP OAuth discovery, bearer challenge, and Keycloak audience checks.

Fixtures are fictional. Tokens are signed with a test key generated in-process.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.integrations.keycloak import KeycloakVerifier, accepted_token_audiences
from app.main import create_app

ISSUER = "https://auth.example.com/realms/uchub"
PUBLIC = "https://api.taxplanningops.example"
KID = "fictional-test-kid"
RESOURCE_AUD = "https://api.taxplanningops.example/api/v1/mcp"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

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


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    body: dict[str, object] = {
        "iss": ISSUER,
        "sub": "fictional-advisor-001",
        "aud": "tax-planning-ops",
        "azp": "tax-planning-ops",
        "iat": now,
        "exp": now + 600,
        "scope": "openid profile taxplan:advisor",
    }
    body.update(overrides)
    return body


def _sign(claims: dict[str, object], *, kid: str = KID) -> str:
    encoded = jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": kid})
    assert isinstance(encoded, str)
    return encoded


def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("STANDALONE_MODE", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "tax-planning-ops")
    monkeypatch.setenv("KEYCLOAK_AUDIENCE", "tax-planning-ops")
    monkeypatch.setenv("KEYCLOAK_EXPECTED_AUDIENCES", "")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("ENTITLEMENT_CHECK_ENABLED", "false")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_settings_parse_audiences_and_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEYCLOAK_EXPECTED_AUDIENCES", "dynamic-client, another-client")
    monkeypatch.setenv(
        "MCP_ALLOWED_ORIGINS",
        "https://agent.example.com, https://other.example.com/",
    )
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.taxplanningops.example/")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.KEYCLOAK_EXPECTED_AUDIENCES == ["dynamic-client", "another-client"]
    assert settings.MCP_ALLOWED_ORIGINS == [
        "https://agent.example.com",
        "https://other.example.com",
    ]
    assert settings.PUBLIC_BASE_URL == PUBLIC
    assert accepted_token_audiences(settings) == {
        "tax-planning-ops",
        "dynamic-client",
        "another-client",
    }


def test_standalone_mode_is_refused_in_prod() -> None:
    with pytest.raises(ValidationError):
        Settings(ENV="prod", STANDALONE_MODE=True, _env_file=None)


def test_standalone_verifier_accepts_any_bearer_outside_prod() -> None:
    settings = Settings(
        ENV="dev",
        STANDALONE_MODE=True,
        KEYCLOAK_ISSUER=ISSUER,
        _env_file=None,
    )
    claims = asyncio.run(KeycloakVerifier(settings).verify("not-a-jwt"))
    assert claims["sub"] == settings.STANDALONE_USER_ID
    assert claims["aud"] == settings.KEYCLOAK_AUDIENCE


def test_prm_documents_are_public_and_ring_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch)
    paths = (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/api/v1/mcp",
    )
    for path in paths:
        response = client.get(path, headers={"Authorization": "Bearer fictional-rejected"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["access-control-allow-origin"] == "*"
        assert response.headers["cache-control"] == "public, max-age=3600"
        body = response.json()
        assert set(body) == {
            "resource",
            "authorization_servers",
            "bearer_methods_supported",
            "scopes_supported",
            "resource_name",
            "resource_documentation",
        }
        assert body["resource"] == f"{PUBLIC}/api/v1/mcp"
        assert body["authorization_servers"] == [ISSUER]
        # Clients request exactly these; Keycloak's DCR policy refuses any other scope, and `mcp` carries the audience.
        assert body["scopes_supported"] == ["openid", "profile", "email", "offline_access", "mcp"]
        assert "fictional-rejected" not in response.text

    dogfood = _app(
        monkeypatch,
        KEYCLOAK_ISSUER="https://auth.magicunicorn.dev/realms/uchub",
        PUBLIC_BASE_URL="https://api.taxplanningops.magicunicorn.dev",
    )
    dogfood_body = dogfood.get(paths[1]).json()
    assert dogfood_body["authorization_servers"] == [
        "https://auth.magicunicorn.dev/realms/uchub"
    ]
    assert dogfood_body["resource"] == (
        "https://api.taxplanningops.magicunicorn.dev/api/v1/mcp"
    )


def test_prm_options_and_slash_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch)
    options = client.options("/.well-known/oauth-protected-resource/api/v1/mcp")
    redirect = client.get(
        "/.well-known/oauth-protected-resource/api/v1/mcp/",
        follow_redirects=False,
    )
    root_redirect = client.get(
        "/.well-known/oauth-protected-resource/",
        follow_redirects=False,
    )

    assert options.status_code == 200
    assert options.headers["access-control-allow-origin"] == "*"
    assert set(options.json()) >= {"resource", "authorization_servers"}
    assert redirect.status_code == 308
    assert redirect.headers["location"].endswith(
        "/.well-known/oauth-protected-resource/api/v1/mcp"
    )
    assert root_redirect.status_code == 308
    assert root_redirect.headers["location"].endswith("/.well-known/oauth-protected-resource")


def test_prm_uses_forwarded_headers_when_public_base_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _app(monkeypatch, PUBLIC_BASE_URL="")
    response = client.get(
        "/.well-known/oauth-protected-resource",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "api.taxplanningops.unicorncommander.ai",
        },
    )
    assert response.status_code == 200
    assert response.json()["resource"] == (
        "https://api.taxplanningops.unicorncommander.ai/api/v1/mcp"
    )


def test_mcp_challenge_header_and_rest_stays_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch)
    missing = client.post("/api/v1/mcp", json=INIT)
    rejected = client.post(
        "/api/v1/mcp",
        headers={"Authorization": "Bearer fictional-invalid-token"},
        json=INIT,
    )
    cookie_only = client.post(
        "/api/v1/mcp",
        headers={"Cookie": "access_token=fictional-session"},
        json=INIT,
    )
    rest = client.get("/api/v1/healthz")

    metadata = f"{PUBLIC}/.well-known/oauth-protected-resource/api/v1/mcp"
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == (
        f'Bearer realm="tax-planning-ops-mcp", resource_metadata="{metadata}"'
    )
    assert 'error="invalid_token"' not in missing.headers["www-authenticate"]
    assert rejected.status_code == 401
    assert 'error="invalid_token"' in rejected.headers["www-authenticate"]
    assert "fictional-invalid-token" not in rejected.text
    assert "fictional-invalid-token" not in rejected.headers["www-authenticate"]
    assert cookie_only.status_code == 401
    assert 'error="invalid_token"' not in cookie_only.headers["www-authenticate"]
    assert rest.status_code == 401
    assert rest.headers["www-authenticate"] == "Bearer"


def test_unknown_pat_on_mcp_uses_the_same_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _missing_pat(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr("app.core.auth.find_active_pat_by_token", _missing_pat)
    client = _app(monkeypatch)
    presented = "tpo_pat_" + ("a" * 43)
    response = client.post(
        "/api/v1/mcp",
        headers={"Authorization": f"Bearer {presented}"},
        json=INIT,
    )
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert 'realm="tax-planning-ops-mcp"' in response.headers["www-authenticate"]
    assert presented not in response.text


def test_mcp_cors_preflight_origin_and_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch, MCP_ALLOWED_ORIGINS="https://agent.example.com")
    preflight = client.options(
        "/api/v1/mcp",
        headers={
            "Origin": "https://agent.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,mcp-session-id",
        },
    )
    blocked = client.post(
        "/api/v1/mcp",
        headers={"Origin": "https://blocked.example", "Authorization": "Bearer fictional"},
        json=INIT,
    )
    allowed = client.post(
        "/api/v1/mcp",
        headers={"Origin": "http://localhost:3000"},
        json=INIT,
    )
    slash = client.post("/api/v1/mcp/", json=INIT, follow_redirects=False)

    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "https://agent.example.com"
    allow_headers = preflight.headers["access-control-allow-headers"]
    assert "Authorization" in allow_headers
    assert "Mcp-Session-Id" in allow_headers
    assert "Mcp-Protocol-Version" in allow_headers
    assert "Last-Event-ID" in allow_headers
    assert preflight.headers["access-control-expose-headers"] == "Mcp-Session-Id"
    assert blocked.status_code == 403
    assert "www-authenticate" not in blocked.headers
    assert "fictional" not in blocked.text
    assert allowed.status_code == 401
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-expose-headers"] == "Mcp-Session-Id"
    assert slash.status_code == 308
    assert slash.headers["location"].endswith("/api/v1/mcp")
    assert not slash.headers["location"].rstrip("/").endswith("/api/v1/mcp/")


def test_get_is_405_only_after_auth_and_standalone_still_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anonymous = _app(monkeypatch)
    assert anonymous.get("/api/v1/mcp").status_code == 401

    client = _app(monkeypatch, ENV="dev", STANDALONE_MODE="true")
    posted = client.post(
        "/api/v1/mcp",
        headers={"Authorization": "Bearer any-fictional-bearer"},
        json=INIT,
    )
    fetched = client.get(
        "/api/v1/mcp",
        headers={"Authorization": "Bearer any-fictional-bearer"},
    )
    cookie = client.post(
        "/api/v1/mcp",
        headers={"Cookie": "access_token=fictional-session"},
        json=INIT,
    )
    assert posted.status_code == 200
    assert posted.json()["result"]["protocolVersion"] == "2025-06-18"
    assert fetched.status_code == 405
    assert fetched.headers["allow"] == "POST"
    assert cookie.status_code == 401


def test_signed_keycloak_token_aud_or_azp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.keycloak.httpx.AsyncClient", _JWKSClient)
    client = _app(
        monkeypatch,
        KEYCLOAK_EXPECTED_AUDIENCES="https://dynamic.example/client",
    )

    def post(claims: dict[str, object]) -> Any:
        return client.post(
            "/api/v1/mcp",
            headers={"Authorization": f"Bearer {_sign(claims)}"},
            json=INIT,
        )

    accepted = post(_claims())
    assert accepted.status_code == 200
    assert post(_claims(aud="account", azp="tax-planning-ops")).status_code == 200
    assert (
        post(
            _claims(
                aud=["account", RESOURCE_AUD],
                azp="tax-planning-ops",
            )
        ).status_code
        == 200
    )
    dynamic = post(
        _claims(aud="account", azp="https://dynamic.example/client")
    )
    assert dynamic.status_code == 200
    rejected = post(_claims(aud="account", azp="some-other-client"))
    assert rejected.status_code == 401
    assert 'error="invalid_token"' in rejected.headers["www-authenticate"]
    resource_only = post(_claims(aud=RESOURCE_AUD, azp="not-configured"))
    assert resource_only.status_code == 401
    expired = post(_claims(iat=int(time.time()) - 120, exp=int(time.time()) - 60))
    assert expired.status_code == 401
    wrong_iss = post(_claims(iss="https://auth.example.com/realms/other"))
    assert wrong_iss.status_code == 401


def test_none_algorithm_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.keycloak.httpx.AsyncClient", _JWKSClient)
    client = _app(monkeypatch)

    def encode(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = f"{encode({'alg': 'none', 'kid': KID})}.{encode(_claims())}."
    response = client.post(
        "/api/v1/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json=INIT,
    )
    assert response.status_code == 401
    assert token not in response.text
