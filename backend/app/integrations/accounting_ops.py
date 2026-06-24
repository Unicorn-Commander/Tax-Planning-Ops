"""Accounting-Ops federation read.

Pulls a business's Profit & Loss net income from Accounting-Ops (live on
centerdeep, `GET /api/workspaces/{workspace_id}/reports/pl`) so a linked TPO
business entity's `amount_cents` can be sourced from the real books instead of
hand entry.

Auth = the suite-canonical brokered token. TPO mints its own Keycloak service
token (client-credentials), then exchanges it at Brigade's RFC-8693 endpoint for
a Brigade-issued token carrying the Accounting-Ops audience — AO trusts Brigade
(its issuer/JWKS/audience), not TPO's Keycloak directly. (TPO and AO sit behind
different Keycloaks — auth.magicunicorn.dev vs auth.unicorncommander.ai — so a
raw KC token 401s with "unknown signing key"; Brigade is the shared anchor.)
Set BRIGADE_TOKEN_URL to enable the exchange; without it the adapter sends the
raw KC token (legacy/testing). Until the AO/Brigade trust is wired, calls return
401/403 → `AccountingOpsAuthError`, which the API turns into a clear "not yet
authorized" message rather than a 500.

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


class AccountingOpsWorkspaceNotFoundError(AccountingOpsError):
    """AO has no such workspace (or it's inactive) — usually a bad link."""


class PLSummary(BaseModel):
    accounting_ops_workspace_id: str
    net_income_cents: int
    period: str | None = None
    available_keys: list[str] = []


# Cached federation tokens keyed by AO workspace id (the Brigade-exchanged token
# is workspace-scoped): {workspace_id: {"value": str, "expires_at": float}}.
_token_cache: dict[str, dict[str, Any]] = {}


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


async def _mint_kc_token(settings: Settings) -> str:
    """Client-credentials grant for TPO's own KC service account (the subject
    token for the Brigade exchange)."""
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
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.post(token_url, data=form)
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(
            f"could not reach the KC token endpoint: {exc}"
        ) from exc
    if resp.status_code in (400, 401, 403):
        raise AccountingOpsAuthError(f"client-credentials grant rejected ({resp.status_code})")
    if resp.status_code >= 400:
        raise AccountingOpsUnavailableError(f"KC token endpoint error ({resp.status_code})")
    token = resp.json().get("access_token")
    if not token:
        raise AccountingOpsUnavailableError("KC token response had no access_token")
    return str(token)


async def _exchange_at_brigade(
    subject_token: str, workspace_id: str, settings: Settings
) -> tuple[str, int]:
    """RFC-8693 token exchange at Brigade: swap TPO's KC token for a Brigade-
    issued token carrying the Accounting-Ops audience (the suite-canonical broker
    pattern AO trusts). The broker derives the actor from subject_token.azp, so
    no actor_token is sent; the AO workspace UUID is passed explicitly because
    the client-credentials token carries no workspace claim. Returns
    (token, expires_in)."""
    form: dict[str, str] = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "workspace_id": workspace_id,
    }
    if settings.ACCOUNTING_OPS_AUDIENCE:
        form["audience"] = settings.ACCOUNTING_OPS_AUDIENCE
    # Client auth is only sent if explicitly configured for the broker — the
    # broker reads the actor from the subject token, so by default we send none.
    if settings.BRIGADE_CLIENT_ID:
        form["client_id"] = settings.BRIGADE_CLIENT_ID
    if settings.BRIGADE_CLIENT_SECRET:
        form["client_secret"] = settings.BRIGADE_CLIENT_SECRET
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.post(settings.BRIGADE_TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(f"could not reach Brigade exchange: {exc}") from exc
    if resp.status_code in (400, 401, 403):
        raise AccountingOpsAuthError(
            f"Brigade token exchange rejected ({resp.status_code}) — the "
            "tax-planning-ops → accounting-ops exchange contract may not be registered yet."
        )
    if resp.status_code >= 400:
        raise AccountingOpsUnavailableError(f"Brigade exchange error ({resp.status_code})")
    body = resp.json()
    token = body.get("access_token") or body.get("token")
    if not token:
        raise AccountingOpsUnavailableError("Brigade exchange returned no access_token")
    return str(token), int(body.get("expires_in", 60))


async def _get_federation_token(settings: Settings, workspace_id: str) -> str:
    """The token TPO presents to Accounting-Ops, for a specific AO workspace.

    Canonical path: mint TPO's KC token, then exchange it at Brigade for an
    AO-audience token scoped to `workspace_id` (set BRIGADE_TOKEN_URL). Without a
    Brigade URL it falls back to the raw KC token (legacy/testing). A static
    override short-circuits both. The Brigade token is workspace-scoped, so the
    cache is keyed by workspace."""
    if settings.ACCOUNTING_OPS_SERVICE_TOKEN:
        return settings.ACCOUNTING_OPS_SERVICE_TOKEN
    entry = _token_cache.get(workspace_id)
    if entry and time.time() < entry.get("expires_at", 0.0):
        return str(entry["value"])

    kc_token = await _mint_kc_token(settings)
    if settings.BRIGADE_TOKEN_URL:
        token, expires_in = await _exchange_at_brigade(kc_token, workspace_id, settings)
    else:
        token, expires_in = kc_token, 60
    _token_cache[workspace_id] = {
        "value": token,
        "expires_at": time.time() + max(0, expires_in - 15),
    }
    return token


async def fetch_pl(
    accounting_ops_workspace_id: str,
    settings: Settings,
    *,
    entity_id: str | None = None,
    period: str | None = None,
) -> PLSummary:
    """Read the linked AO workspace's P&L and return its net income in cents.

    ``entity_id`` scopes the report to a single entity within the workspace
    (otherwise AO returns the workspace's consolidated P&L — which would mix
    several books). ``period`` selects the reporting period AO computes over
    (e.g. a tax year ``"2025"``); unset → AO's own default (currently YTD)."""
    if not settings.ACCOUNTING_OPS_ENABLED or not settings.ACCOUNTING_OPS_URL:
        raise AccountingOpsDisabledError("Accounting-Ops integration is not enabled")

    token = await _get_federation_token(settings, accounting_ops_workspace_id)
    url = (
        f"{settings.ACCOUNTING_OPS_URL.rstrip('/')}"
        f"/api/workspaces/{accounting_ops_workspace_id}/reports/pl"
    )
    params: dict[str, str] = {}
    if entity_id:
        params["entity_id"] = entity_id
    if period:
        params["period"] = period
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url, params=params or None, headers={"Authorization": f"Bearer {token}"}
            )
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(f"could not reach Accounting-Ops: {exc}") from exc

    if resp.status_code in (401, 403):
        raise AccountingOpsAuthError(
            "Accounting-Ops rejected the service token — the federation trust for "
            "Tax-Planning-Ops is not yet authorized on the Accounting-Ops side."
        )
    if resp.status_code == 404:
        raise AccountingOpsWorkspaceNotFoundError(
            f"Accounting-Ops workspace '{accounting_ops_workspace_id}' not found or not active"
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


# ---------------------------------------------------------------------------
# Tax-document extractions (the OCR consumer side)
# ---------------------------------------------------------------------------
#
# AO owns the document vault + OCR; TPO reads the structured results over the
# SAME federation rail as the P&L pull (GET /api/workspaces/{ws}/tax-documents).
# These are the income/source forms a 1040 is built from (1099-R, SSA-1099,
# 1095, W-2, K-1, IRS/state notices) — overwhelmingly scanned PDFs that AO
# classified + transcribed. TPO never re-runs the vision model; it consumes.


class TaxDocumentExtraction(BaseModel):
    """One structured tax document AO extracted (classification + verbatim fields).

    Mirrors a row of the AO federation payload. ``fields`` is the model's
    verbatim transcription of the form's labeled boxes — AO never computes or
    sums, so e.g. an OPM CSA-1099-R "2a Taxable amount" may be the literal string
    "UNKNOWN". Consumers (the strategist, the intake UI) must treat values as
    printed, never as math.
    """

    id: str
    entity_id: str | None = None
    receipt_id: str | None = None
    doc_type: str = "other"
    tax_year: int | None = None
    payer_name: str | None = None
    recipient_name: str | None = None
    fields: dict[str, Any] = {}
    confidence: float | None = None
    status: str = "extracted"
    model: str | None = None
    extracted_at: str | None = None


class TaxDocumentSet(BaseModel):
    accounting_ops_workspace_id: str
    entity_id: str | None = None
    tax_year: int | None = None
    documents: list[TaxDocumentExtraction] = []


async def fetch_tax_documents(
    accounting_ops_workspace_id: str,
    settings: Settings,
    *,
    entity_id: str | None = None,
    tax_year: int | None = None,
) -> TaxDocumentSet:
    """Read an AO entity's structured tax-document extractions over federation.

    The consumer side of AO's OCR: TPO reads ``document_extraction`` rows by
    (entity_id, tax_year) instead of re-running the vision model. Same token rail
    as ``fetch_pl`` (``_get_federation_token``: mint TPO's KC service token →
    raw-KC by default, or Brigade-exchange when ``BRIGADE_TOKEN_URL`` is set).
    The AO endpoint floors the caller to viewer and refuses HIPAA workspaces.

    ``entity_id`` scopes to a single AO entity (personal income docs live under
    the personal entity); ``tax_year`` filters to one year. Both optional. Raises
    the same AccountingOps* hierarchy as ``fetch_pl`` so the API maps them to the
    same status codes.
    """
    if not settings.ACCOUNTING_OPS_ENABLED or not settings.ACCOUNTING_OPS_URL:
        raise AccountingOpsDisabledError("Accounting-Ops integration is not enabled")

    token = await _get_federation_token(settings, accounting_ops_workspace_id)
    url = (
        f"{settings.ACCOUNTING_OPS_URL.rstrip('/')}"
        f"/api/workspaces/{accounting_ops_workspace_id}/tax-documents"
    )
    params: dict[str, str] = {}
    if entity_id:
        params["entity_id"] = entity_id
    if tax_year is not None:
        params["tax_year"] = str(tax_year)
    try:
        async with httpx.AsyncClient(timeout=settings.ACCOUNTING_OPS_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url, params=params or None, headers={"Authorization": f"Bearer {token}"}
            )
    except httpx.HTTPError as exc:
        raise AccountingOpsUnavailableError(f"could not reach Accounting-Ops: {exc}") from exc

    if resp.status_code in (401, 403):
        raise AccountingOpsAuthError(
            "Accounting-Ops rejected the service token — the federation trust for "
            "Tax-Planning-Ops is not yet authorized on the Accounting-Ops side."
        )
    if resp.status_code == 404:
        raise AccountingOpsWorkspaceNotFoundError(
            f"Accounting-Ops workspace '{accounting_ops_workspace_id}' not found or not active"
        )
    if resp.status_code >= 400:
        raise AccountingOpsUnavailableError(f"Accounting-Ops returned {resp.status_code}")

    try:
        payload = dict(resp.json())
    except ValueError as exc:
        raise AccountingOpsUnavailableError(
            "Accounting-Ops tax-documents response was not valid JSON"
        ) from exc

    raw = payload.get("extractions")
    if not isinstance(raw, list):
        raise AccountingOpsUnavailableError(
            "Accounting-Ops tax-documents response had no 'extractions' list"
        )
    documents = [
        TaxDocumentExtraction.model_validate(d) for d in raw if isinstance(d, dict)
    ]
    return TaxDocumentSet(
        accounting_ops_workspace_id=accounting_ops_workspace_id,
        entity_id=entity_id,
        tax_year=tax_year,
        documents=documents,
    )
