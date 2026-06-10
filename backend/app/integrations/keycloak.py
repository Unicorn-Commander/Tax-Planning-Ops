from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import jwt

from app.core.config import Settings


class KeycloakVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks: dict[str, Any] | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> dict[str, Any]:
        if self.settings.STANDALONE_MODE:
            return {
                "sub": self.settings.STANDALONE_USER_ID,
                "workspace_id": self.settings.STANDALONE_WORKSPACE_ID,
                "scope": "taxplan:advisor taxplan:admin",
                "iss": "standalone",
                "aud": self.settings.KEYCLOAK_AUDIENCE,
            }
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:  # noqa: BLE001 - malformed token must read as 401
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            ) from exc
        key = await self._resolve_key(header.get("kid"))
        if key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown jwt key")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=self.settings.JWT_ALLOWED_ALGORITHMS,
                audience=self.settings.KEYCLOAK_AUDIENCE,
                issuer=self.settings.KEYCLOAK_ISSUER,
                options={
                    # python-jose verifies claim VALUES but does not require the
                    # claims to exist — force presence so a token missing aud/exp
                    # (e.g. a never-expiring token) is rejected.
                    "require_aud": True,
                    "require_exp": True,
                    "require_iat": True,
                    "require_iss": True,
                },
            )
            return dict(claims)
        except Exception as exc:  # noqa: BLE001 - jose raises several auth exceptions
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            ) from exc

    async def _resolve_key(self, kid: str | None) -> dict[str, Any] | None:
        if self._jwks is None or time.time() >= self._expires_at:
            await self._refresh_jwks()
        for key in (self._jwks or {}).get("keys", []):
            if key.get("kid") == kid:
                return dict(key)
        await self._refresh_jwks(force=True)
        for key in (self._jwks or {}).get("keys", []):
            if key.get("kid") == kid:
                return dict(key)
        return None

    async def _refresh_jwks(self, force: bool = False) -> None:
        async with self._lock:
            now = time.time()
            if not force and self._jwks is not None and now < self._expires_at:
                return
            if not self.settings.KEYCLOAK_JWKS_URL:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="jwks url is not configured",
                )
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.settings.KEYCLOAK_JWKS_URL)
                response.raise_for_status()
                self._jwks = response.json()
                self._expires_at = now + self.settings.JWKS_CACHE_TTL_SECONDS
