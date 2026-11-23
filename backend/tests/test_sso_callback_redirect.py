"""SSO callback redirect: tokens must travel in the URL fragment, not the query.

Fixtures are fictional. The Keycloak token endpoint is stubbed in-process, so no
network call is made. The route handler is exercised directly: it is the
RedirectResponse location that proxies, history and Referer headers would leak.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.auth import keycloak_callback
from app.core.config import Settings

ACCESS_TOKEN = "fictional-access-token"  # noqa: S105
REFRESH_TOKEN = "fictional-refresh-token"  # noqa: S105
FRONTEND = "http://frontend.example.com"
TOKEN_ENDPOINT = (
    "https://auth.example.com/realms/uchub/protocol/openid-connect/token"  # noqa: S105
)


class _TokenResponse:
    status_code = 200

    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    def json(self) -> dict[str, object]:
        return self._body


class _StubHttpClient:
    """Replaces httpx.AsyncClient for the token exchange only."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.body: dict[str, object] = {
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "expires_in": 300,
            "token_type": "Bearer",
        }

    async def __aenter__(self) -> _StubHttpClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        del exc
        return False

    async def post(self, url: str, *, data: dict[str, str]) -> _TokenResponse:
        assert url == TOKEN_ENDPOINT
        assert data["grant_type"] == "authorization_code"
        return _TokenResponse(self.body)


def _settings() -> Settings:
    return Settings(
        ENV="test",
        KEYCLOAK_ISSUER="https://auth.example.com/realms/uchub",
        KEYCLOAK_CLIENT_ID="tax-planning-ops",
        FRONTEND_URL=FRONTEND,
    )


def test_callback_redirect_carries_tokens_in_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubHttpClient()
    monkeypatch.setattr("app.api.auth.httpx.AsyncClient", lambda **kw: stub)
    location = asyncio.run(
        keycloak_callback(code="fictional-code", settings=_settings())
    ).headers["location"]
    # Fragments never leave the browser, so they cannot be logged by any proxy.
    assert location.startswith(f"{FRONTEND}/auth/sso-callback#")
    query_part, fragment = location.split("#", 1)
    assert "?" not in query_part
    assert f"token={ACCESS_TOKEN}" in fragment
    assert f"refresh_token={REFRESH_TOKEN}" in fragment


def test_callback_redirect_without_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubHttpClient()
    stub.body = {"access_token": ACCESS_TOKEN, "expires_in": 300, "token_type": "Bearer"}
    monkeypatch.setattr("app.api.auth.httpx.AsyncClient", lambda **kw: stub)
    location = asyncio.run(
        keycloak_callback(code="fictional-code", settings=_settings())
    ).headers["location"]
    assert location == f"{FRONTEND}/auth/sso-callback#token={ACCESS_TOKEN}"
    assert "refresh_token" not in location
    assert "?" not in location


def test_callback_token_endpoint_failure_is_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient(_StubHttpClient):
        async def post(self, url: str, *, data: dict[str, str]) -> _TokenResponse:
            return _TokenResponse({"error": "invalid_grant"})  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.api.auth.httpx.AsyncClient", lambda **kw: _FailingClient()
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(keycloak_callback(code="fictional-code", settings=_settings()))
    assert exc.value.status_code == 401
