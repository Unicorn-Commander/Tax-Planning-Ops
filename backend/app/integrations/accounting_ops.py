"""Accounting-Ops federation read.

Pulls a business's Profit & Loss net income from Accounting-Ops (live on
centerdeep, `GET /api/workspaces/{workspace_id}/reports/pl`) so a linked TPO
business entity's `amount_cents` can be sourced from the real books instead of
hand entry.

Auth = a client-credentials token minted from TPO's own Keycloak confidential
client; AO must trust that service account as a federation actor (the canonical
brokered-token pattern — NOT a per-app credential). Until that trust is wired on
the AO side, calls return 401/403 and surface as `AccountingOpsAuthError`, which
the API turns into a clear "not yet authorized" message rather than a 500.

The P&L shape isn't contractually pinned yet, so `extract_net_income_cents` is
defensive across the likely key names and a dollars-vs-cents heuristic; it is
pure and unit-tested.
"""

from __future__ import annotations

import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings


class AccountingOpsError(RuntimeError):
    """Base for any Accounting-Ops federation failure."""


class AccountingOpsDisabledError(AccountingOpsError):
    """The integration is turned off (no URL / flag off)."""


class AccountingOpsAuthError(AccountingOpsError):
    """AO rejected the service token (trust not yet established)."""


class AccountingOpsUnavailableError(AccountingOpsError):
    """AO unreachable / returned a server error / malformed response."""


class PLSummary(BaseModel):
    accounting_ops_workspace_id: str
    net_income_cents: int
    period: str | None = None
    available_keys: list[str] = []


# Cached service token: {"value": str, "expires_at": float}.
_token_cache: dict[str, Any] = {}


def _cents_from(value: Any) -> int | None:
    """Coerce a P&L money value to integer cents.

    Integers are assumed to already be cents (suite convention). Floats and
    strings are dollar amounts and are scaled exactly via Decimal — AO returns
    net income as a dollar Decimal string (e.g. "1234.56"). Returns None if not
    numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        text = str(value).replace(",", "").replace("$", "").strip()
        try:
            return int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            return None
    return None


_NET_INCOME_KEYS = (
    "net_income_cents",
    "net_profit_cents",
    "net_income",
    "net_profit",
    "net_ordinary_income",
    "total_net_income",
    "net",
)
_NESTED_KEYS = ("summary", "totals", "data", "report", "result")


def extract_net_income_cents(payload: dict[str, Any]) -> int | None:
    """Find the P&L net income (in cents) across the likely response shapes.

    Prefers an explicit `*_cents` field (taken as-is); otherwise scales a dollar
    figure. Looks at the top level and one level into common wrapper keys."""
    scopes: list[dict[str, Any]] = [payload]
    for key in _NESTED_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            scopes.append(nested)
    for scope in scopes:
        for key in _NET_INCOME_KEYS:
            if key in scope:
                cents = _cents_from(scope[key])
                if cents is not None:
                    return cents
    return None


async def _get_service_token(settings: Settings) -> str:
    if settings.ACCOUNTING_OPS_SERVICE_TOKEN:
        return settings.ACCOUNTING_OPS_SERVICE_TOKEN
    cached = _token_cache.get("value")
    if cached and time.time() < _token_cache.get("expires_at", 0.0):
        return str(cached)
    if not settings.KEYCLOAK_CLIENT_SECRET:
        raise AccountingOpsAuthError(
            "no Accounting-Ops service credential configured "
            "(KEYCLOAK_CLIENT_SECRET / ACCOUNTING_OPS_SERVICE_TOKEN)"
        )
    token_url = f"{settings.KEYCLOAK_ISSUER.rstrip('/')}/protocol/openid-connect/token"
    form: dict[str, str] = {
        "grant_type": "client_credentials",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
    }
    if settings.ACCOUNTING_OPS_AUDIENCE:
        form["audience"] = settings.ACCOUNTING_OPS_AUDIENCE
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.post(token_url, data=form)
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(f"could not reach the token endpoint: {exc}") from exc
    if resp.status_code in (400, 401, 403):
        raise AccountingOpsAuthError(
            f"client-credentials grant rejected ({resp.status_code})"
        )
    if resp.status_code >= 400:
        raise AccountingOpsUnavailableError(f"token endpoint error ({resp.status_code})")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise AccountingOpsUnavailableError("token response had no access_token")
    _token_cache["value"] = token
    _token_cache["expires_at"] = time.time() + max(0, int(body.get("expires_in", 60)) - 15)
    return str(token)


async def fetch_pl(accounting_ops_workspace_id: str, settings: Settings) -> PLSummary:
    """Read the linked AO workspace's P&L and return its net income in cents."""
    if not settings.ACCOUNTING_OPS_ENABLED or not settings.ACCOUNTING_OPS_URL:
        raise AccountingOpsDisabledError("Accounting-Ops integration is not enabled")

    token = await _get_service_token(settings)
    url = (
        f"{settings.ACCOUNTING_OPS_URL.rstrip('/')}"
        f"/api/workspaces/{accounting_ops_workspace_id}/reports/pl"
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(f"could not reach Accounting-Ops: {exc}") from exc

    if resp.status_code in (401, 403):
        raise AccountingOpsAuthError(
            "Accounting-Ops rejected the service token — the federation trust for "
            "Tax-Planning-Ops is not yet authorized on the Accounting-Ops side."
        )
    if resp.status_code == 404:
        raise AccountingOpsUnavailableError(
            f"Accounting-Ops workspace '{accounting_ops_workspace_id}' or its P&L was not found"
        )
    if resp.status_code >= 400:
        raise AccountingOpsUnavailableError(f"Accounting-Ops returned {resp.status_code}")

    try:
        payload = dict(resp.json())
    except ValueError as exc:
        raise AccountingOpsUnavailableError("Accounting-Ops P&L was not valid JSON") from exc

    net_cents = extract_net_income_cents(payload)
    if net_cents is None:
        raise AccountingOpsUnavailableError(
            "could not find net income in the Accounting-Ops P&L "
            f"(keys: {sorted(payload.keys())})"
        )
    return PLSummary(
        accounting_ops_workspace_id=accounting_ops_workspace_id,
        net_income_cents=net_cents,
        period=str(payload.get("period")) if payload.get("period") is not None else None,
        available_keys=sorted(payload.keys()),
    )
