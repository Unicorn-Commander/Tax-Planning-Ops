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
