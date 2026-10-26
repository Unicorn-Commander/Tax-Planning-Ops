from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import jwt

from app.core.config import Settings

logger = logging.getLogger("tax_planning_ops.auth")


def accepted_token_audiences(settings: Settings) -> set[str]:
    """Audiences this process accepts on ``aud`` or ``azp``.

    The set is the existing client audience (``KEYCLOAK_AUDIENCE``, default
    ``KEYCLOAK_CLIENT_ID``) plus ``KEYCLOAK_CLIENT_ID`` plus
    ``KEYCLOAK_EXPECTED_AUDIENCES``. Matching is fail-closed: an ``azp`` value
    is accepted only when it is in this set.
    """
    configured = (
        settings.KEYCLOAK_AUDIENCE,
        settings.KEYCLOAK_CLIENT_ID,
        *settings.KEYCLOAK_EXPECTED_AUDIENCES,
    )
    return {item.strip() for item in configured if isinstance(item, str) and item.strip()}


def _audience_values(claims: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return (aud-or-azp values, resource-style aud values)."""
    aud = claims.get("aud")
    if isinstance(aud, str):
        aud_list = [aud]
    elif isinstance(aud, list):
        aud_list = [item for item in aud if isinstance(item, str)]
    else:
        aud_list = []
    values = set(aud_list)
    azp = claims.get("azp")
    if isinstance(azp, str) and azp.strip():
        values.add(azp.strip())
    resource_style = {
        item
        for item in aud_list
        if item.startswith("https://") or item.startswith("http://")
    }
    return values, resource_style


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
            # Signature, issuer, exp, and iat stay strict. Audience is checked
            # below: python-jose's audience= argument looks only at ``aud`` and
            # rejects a token whose aud is ``account`` even when ``azp`` is this
            # app's client id (what Keycloak stamps for a dynamic OAuth client).
            claims = jwt.decode(
                token,
                key,
                algorithms=self.settings.JWT_ALLOWED_ALGORITHMS,
                issuer=self.settings.KEYCLOAK_ISSUER,
                options={
                    "verify_aud": False,
                    "require_exp": True,
                    "require_iat": True,
                    "require_iss": True,
                },
            )
        except Exception as exc:  # noqa: BLE001 - jose raises several auth exceptions
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            ) from exc
        return self._require_audience(dict(claims))

    def _require_audience(self, claims: dict[str, Any]) -> dict[str, Any]:
        expected = accepted_token_audiences(self.settings)
        presented, resource_style = _audience_values(claims)
        if resource_style:
            # A resource URL in ``aud`` (RFC 8707) must not by itself fail a
            # token that also carries a configured audience. It also must not
            # pass on its own until that URL is configured.
            logger.info(
                "resource-style audience present (not a rejection by itself): %s",
                sorted(resource_style),
            )
        if not expected.intersection(presented):
            logger.warning(
                "token audience rejected: aud/azp=%s accepted=%s",
                sorted(presented),
                sorted(expected),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            )
        return claims

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
