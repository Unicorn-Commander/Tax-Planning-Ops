from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


def _oidc_base(settings: Settings) -> str:
    return f"{settings.KEYCLOAK_ISSUER.rstrip('/')}/protocol/openid-connect"


@router.get("/keycloak")
async def keycloak_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    params = urlencode(
        {
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "redirect_uri": settings.KEYCLOAK_REDIRECT_URI,
            "response_type": "code",
            # taxplan:advisor/admin are realm ROLES, not OAuth scopes — they
            # arrive in the token via realm_access.roles (the default `roles`
            # scope) and are read in core/auth.py. Requesting them as scopes
            # makes Keycloak reject the authorize with invalid_scope. The
            # uc_uid + workspace_id claims come from the default `unicorn-identity`
            # scope, so the basic OIDC scopes are all we request.
            "scope": "openid profile email",
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
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="keycloak token response missing access_token",
        )
    # Forward the refresh token too so the SPA can silently renew the (short-lived)
    # access token instead of bouncing the user to /auth/login every few minutes.
    # router.replace() on the callback page strips this URL from history immediately.
    params = {"token": token}
    refresh = payload.get("refresh_token")
    if refresh:
        params["refresh_token"] = refresh
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/auth/sso-callback?{urlencode(params)}"
    )


@router.post("/refresh", response_model=RefreshResponse)
async def keycloak_refresh(
    body: RefreshRequest,
    settings: Settings = Depends(get_settings),
) -> RefreshResponse:
    """Exchange a Keycloak refresh token for a fresh access token (and rotated
    refresh token). Unauthenticated by design — the refresh token IS the
    credential — so this path is skipped by the JWT middleware. A 401 here means
    the SSO session has genuinely ended and the SPA should send the user to log
    in again."""
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "refresh_token": body.refresh_token,
    }
    if settings.KEYCLOAK_CLIENT_SECRET:
        data["client_secret"] = settings.KEYCLOAK_CLIENT_SECRET
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{_oidc_base(settings)}/token", data=data)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token expired or invalid",
        )
    payload = response.json()
    access = payload.get("access_token")
    if not access:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="keycloak refresh response missing access_token",
        )
    return RefreshResponse(
        access_token=access,
        # KC rotates the refresh token; fall back to the presented one if a
        # deployment has rotation disabled so the client always has a usable token.
        refresh_token=payload.get("refresh_token") or body.refresh_token,
        expires_in=int(payload.get("expires_in") or 0),
    )
