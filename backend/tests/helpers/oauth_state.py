from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.models.oauth_state import OAuthState


class StateRequest:
    """Stand-in for fastapi.Request: the callback only reads ``cookies``."""

    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


ISSUER = "https://auth.example.com/realms/uchub"
FRONTEND = "http://localhost:3000"
TOKEN_ENDPOINT = f"{ISSUER}/protocol/openid-connect/token"


class TokenResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class StubTokenClient:
    """Replaces httpx.AsyncClient for the token exchange only. Records each
    post so tests can assert whether (and with what data) the exchange ran."""

    status_code = 200

    def __init__(self, **kwargs: Any) -> None:
        del kwargs
        self.calls: list[dict[str, str]] = []
        self.body: dict[str, Any] = {
            "access_token": "fictional-access-token",
            "refresh_token": "fictional-refresh-token",
            "expires_in": 300,
            "token_type": "Bearer",
        }

    async def __aenter__(self) -> StubTokenClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        del exc
        return False

    async def post(self, url: str, *, data: dict[str, str]) -> TokenResponse:
        assert url == TOKEN_ENDPOINT
        self.calls.append({"url": url, **data})
        return TokenResponse(self.status_code, self.body)


class MemoryStateStore:
    """The oauth_state table as a dict, mirroring the DB lookup: an exact
    match on state whose consumed_at is NULL, returning the verifier."""

    def __init__(self) -> None:
        self.records: dict[str, OAuthState] = {}

    def add(self, state: str, code_verifier: str) -> None:
        self.records[state] = OAuthState(
            state=state, code_verifier=code_verifier, consumed_at=None
        )

    async def pop(self, state: str) -> str | None:
        record = self.records.get(state)
        if record is None or record.consumed_at is not None:
            return None
        record.consumed_at = "consumed"
        return record.code_verifier


def make_settings(**overrides: Any) -> Settings:
    kwargs: dict[str, Any] = {
        "ENV": "test",
        "KEYCLOAK_ISSUER": ISSUER,
        "KEYCLOAK_CLIENT_ID": "tax-planning-ops",
        "FRONTEND_URL": FRONTEND,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


