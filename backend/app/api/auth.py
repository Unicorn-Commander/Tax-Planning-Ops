from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import async_session_maker
from app.models.oauth_state import OAuthState

router = APIRouter(prefix="/auth", tags=["auth"])

# A login round trip (authorize + callback) must close inside this window, or
# the stored state is dead weight an attacker could replay. 1800 s matches the
# ticket spec; the TTL is enforced server-side, not by the client.
STATE_TTL_SECONDS = 1800

# __Host- prefix: the browser enforces Secure + Path=/ + no Domain on a
# __Host- prefixed cookie, so the state cookie cannot be planted cross-site or
# exfiltrated over plaintext. On plain http://localhost dev rings the Secure
# requirement would make the cookie unsendable, so that one gets the plain name.
STATE_COOKIE_HOST = "__Host-tpo_oauth_state"
STATE_COOKIE_PLAIN = "tpo_oauth_state"


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


def _oidc_base(settings: Settings) -> str:
    return f"{settings.KEYCLOAK_ISSUER.rstrip('/')}/protocol/openid-connect"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _state_cookie_name(settings: Settings) -> str:
    return (
        STATE_COOKIE_PLAIN
        if settings.FRONTEND_URL.startswith("http://localhost")
        else STATE_COOKIE_HOST
    )


async def create_oauth_state(session: AsyncSession) -> tuple[str, str]:
    """Mint a state + PKCE verifier pair and store it for the callback.

    Returns (state, code_verifier). The state becomes both the cookie value
    and the authorize `state` parameter, so the callback can pair the two.
    """
    now = datetime.now(UTC)
    record = OAuthState(
        state=secrets.token_urlsafe(48),
        code_verifier=secrets.token_urlsafe(48),
        expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
    )
    session.add(record)
    await session.flush()
    return record.state, record.code_verifier


async def pop_oauth_state(state: str) -> str | None:
    """Consume the stored state, single-use, BEFORE any token exchange.

    Returns the code_verifier to send in the exchange, or None when the state
    is missing, already consumed (replay) or expired. A row consumed here is
    marked, so a later replay of the same state still finds the consumed mark.
    """
    async with async_session_maker() as session:
        now = datetime.now(UTC)
        result = await session.execute(
            select(OAuthState).where(
                OAuthState.state == state,
                OAuthState.consumed_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            # Either never minted, already consumed (replay), or expired. All
            # three must refuse identically, and a replay of a consumed state
            # still finds the consumed mark on re-lookup.
            return None
        if record.expires_at <= now:
            return None
        record.consumed_at = now
        await session.flush()
        return record.code_verifier


def _state_error_redirect(settings: Settings) -> RedirectResponse:
    """Missing/mismatched/expired/replayed state: land the user on the frontend
    with a visible error. Never a token exchange, never an automatic bounce
    back to /auth/login (that loop is exactly what an attacker would drive),
    never raw JSON in a browser tab."""
    # Clear the state cookie (Max-Age=0, not a fresh value: no state material
    # ever leaves the server on the error path).
    cookie_name = _state_cookie_name(settings)
    headers = {
        "Set-Cookie": (
            f"{cookie_name}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax; "
            f"{'Secure; ' if cookie_name == STATE_COOKIE_HOST else ''}"
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        )
    }
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/?auth_error=state",
        status_code=status.HTTP_302_FOUND,
        headers=headers,
    )


@router.get("/keycloak")
async def keycloak_login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    async with async_session_maker() as session:
        state, code_verifier = await create_oauth_state(session)
        await session.commit()
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
            # state + PKCE: the callback pairs the cookie state with the query
            # state, then consumes the stored pair before touching Keycloak.
            "state": state,
            "code_challenge": _s256(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"{_oidc_base(settings)}/auth?{params}")
    response.set_cookie(
        _state_cookie_name(settings),
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=_state_cookie_name(settings) == STATE_COOKIE_HOST,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/keycloak/callback")
async def keycloak_callback(
    request: Request,
    code: str,
    state: str | None = None,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    cookie_state = request.cookies.get(_state_cookie_name(settings))
    if not state or not cookie_state or state != cookie_state:
        # Login CSRF: no matching pair means this callback belongs to someone
        # else's (or no one's) login. Refuse before the token exchange.
        return _state_error_redirect(settings)
    code_verifier = await pop_oauth_state(state)
    if code_verifier is None:
        # Expired or replayed: the stored record is gone. Same safe landing.
        return _state_error_redirect(settings)
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "redirect_uri": settings.KEYCLOAK_REDIRECT_URI,
        "code": code,
        "code_verifier": code_verifier,
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
    # The tokens go in the URL FRAGMENT, never the query: fragments are not sent
    # to any server, so they cannot reach reverse-proxy (Traefik/nginx) access
    # logs, browser history, or Referer headers on third-party assets the
    # callback page loads. A leaked refresh token = a long-lived session.
    # history.replaceState on the callback page strips the fragment immediately.
    params = {"token": token}
    refresh = payload.get("refresh_token")
    if refresh:
        params["refresh_token"] = refresh
    # no-store: the Location header carries the access token; Referrer-Policy:
    # no-referrer keeps a stale callback URL out of third-party asset headers.
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Set-Cookie": (
            f"{_state_cookie_name(settings)}=; Max-Age=0; Path=/; "
            f"HttpOnly; SameSite=Lax; "
            f"{'Secure; ' if _state_cookie_name(settings) == STATE_COOKIE_HOST else ''}"
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        ),
    }
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/auth/sso-callback#{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
        headers=headers,
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
