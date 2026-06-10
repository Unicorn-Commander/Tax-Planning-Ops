from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _oidc_base(settings: Settings) -> str:
    return f"{settings.KEYCLOAK_ISSUER.rstrip('/')}/protocol/openid-connect"


@router.get("/keycloak")
async def keycloak_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    params = urlencode(
        {
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "redirect_uri": settings.KEYCLOAK_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid profile email taxplan:advisor taxplan:admin",
        }
    )
    return RedirectResponse(f"{_oidc_base(settings)}/auth?{params}")


@router.get("/keycloak/callback")
async def keycloak_callback(
    code: str,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "redirect_uri": settings.KEYCLOAK_REDIRECT_URI,
        "code": code,
    }
    if settings.KEYCLOAK_CLIENT_SECRET:
        data["client_secret"] = settings.KEYCLOAK_CLIENT_SECRET
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{_oidc_base(settings)}/token", data=data)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="keycloak code exchange failed",
        )
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="keycloak token response missing access_token",
        )
    return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/auth/sso-callback?token={token}")
