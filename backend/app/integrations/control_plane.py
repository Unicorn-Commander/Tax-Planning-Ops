from __future__ import annotations

import logging
import time
from uuid import UUID

import httpx

from app.core.config import Settings

logger = logging.getLogger("tax_planning_ops.entitlement")

# Short-TTL per-workspace cache so we don't hit the control plane on every
# request, and so a transient blip doesn't 500 the whole API.
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, bool]] = {}


async def check_entitlement(workspace_id: UUID, settings: Settings) -> bool:
    if not settings.ENTITLEMENT_CHECK_ENABLED:
        return True
    if not settings.CONTROL_PLANE_BASE_URL or not settings.CONTROL_PLANE_TOKEN:
        return False
    key = str(workspace_id)
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.CONTROL_PLANE_BASE_URL.rstrip('/')}"
                f"/workspaces/{workspace_id}/entitlements/tax-planning-ops",
                headers={"Authorization": f"Bearer {settings.CONTROL_PLANE_TOKEN}"},
            )
        if response.status_code == 404:
            entitled = False
        else:
            response.raise_for_status()
            entitled = bool(response.json().get("enabled"))
    except (httpx.HTTPError, ValueError) as exc:
        # Transient control-plane error: serve the last known answer if we have
        # one (fail-open within the cache window), else fail closed. Never 500.
        if cached:
            logger.warning("entitlement check failed (%s); serving cached value", exc)
            return cached[1]
        logger.warning("entitlement check failed (%s) and no cache; failing closed", exc)
        return False
    _cache[key] = (now, entitled)
    return entitled


# --- Ops-Center tax_ops_access (the door) -----------------------------------
# Ops-Center owns plan entitlements. It answers
#   GET {OPS_CENTER_URL}/api/v1/entitlements?feature_key=tax_ops_access
# for the caller's OWN Keycloak bearer with
#   {"org_id", "org_name", "display_name", "slug", "tier", "role",
#    "entitlements": [...], "authorized": bool}
# Allowed ONLY on 200 with authorized is True. Anything else (401/403/404/5xx,
# timeout, connection error, malformed JSON, missing or non-bool "authorized")
# is a refusal: fail closed. Only a positive answer is cached, per (sub, org),
# for at most _TAX_OPS_CACHE_TTL_SECONDS; a refusal is never cached.
TAX_OPS_FEATURE_KEY = "tax_ops_access"
_TAX_OPS_TIMEOUT_SECONDS = 3.0
_TAX_OPS_CACHE_TTL_SECONDS = 60.0
_tax_ops_allowed: dict[tuple[str, str], float] = {}


def clear_entitlement_cache() -> None:
    _cache.clear()
    _tax_ops_allowed.clear()


def _refuse(reason: str) -> bool:
    # One line per refused request, the status/reason only: never the token,
    # never the response body.
    logger.warning("tax_ops_access refused: %s", reason)
    return False


async def check_tax_ops_access(
    *,
    bearer: str,
    sub: str,
    settings: Settings,
    org_id: str | None = None,
) -> bool:
    """Is the caller's Ops-Center org entitled to Tax-Planning-Ops?

    ``bearer`` is the caller's own Keycloak access token; ``org_id`` (optional)
    is forwarded as ``?org_id=`` and must be an org the caller belongs to."""
    if not settings.ENTITLEMENT_CHECK_ENABLED:
        return True
    base = settings.OPS_CENTER_URL.strip().rstrip("/")
    if not base:
        return _refuse("OPS_CENTER_URL is not set")
    if not bearer or not sub:
        return _refuse("no user bearer to present")
    key = (sub, org_id or "")
    now = time.monotonic()
    allowed_at = _tax_ops_allowed.get(key)
    if allowed_at is not None and now - allowed_at < _TAX_OPS_CACHE_TTL_SECONDS:
        return True
    _tax_ops_allowed.pop(key, None)
    params = {"feature_key": TAX_OPS_FEATURE_KEY}
    if org_id:
        params["org_id"] = org_id
    try:
        async with httpx.AsyncClient(timeout=_TAX_OPS_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}/api/v1/entitlements",
                params=params,
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except httpx.TimeoutException:
        return _refuse("timeout")
    except httpx.HTTPError as exc:
        return _refuse(f"connection error ({type(exc).__name__})")
    if response.status_code != 200:
        return _refuse(f"status {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        return _refuse("status 200, malformed JSON")
    if not isinstance(body, dict) or not isinstance(body.get("authorized"), bool):
        return _refuse("status 200, no boolean 'authorized'")
    if body["authorized"] is not True:
        return _refuse("status 200, authorized false")
    _tax_ops_allowed[key] = now
    return True


def log_entitlement_config(settings: Settings) -> None:
    """One startup error line when the check is on but has nowhere to ask."""
    if settings.ENTITLEMENT_CHECK_ENABLED and not settings.OPS_CENTER_URL.strip():
        logger.error(
            "ENTITLEMENT_CHECK_ENABLED=true but OPS_CENTER_URL is empty: "
            "every caller will be refused"
        )
