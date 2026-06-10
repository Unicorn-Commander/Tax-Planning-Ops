from __future__ import annotations

from uuid import UUID

import httpx

from app.core.config import Settings


async def check_entitlement(workspace_id: UUID, settings: Settings) -> bool:
    if not settings.ENTITLEMENT_CHECK_ENABLED:
        return True
    if not settings.CONTROL_PLANE_BASE_URL or not settings.CONTROL_PLANE_TOKEN:
        return False
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{settings.CONTROL_PLANE_BASE_URL.rstrip('/')}/workspaces/{workspace_id}/entitlements/tax-planning-ops",
            headers={"Authorization": f"Bearer {settings.CONTROL_PLANE_TOKEN}"},
        )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return bool(response.json().get("enabled"))
