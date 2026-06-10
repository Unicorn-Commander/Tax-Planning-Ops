from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


async def get_tax_figures(
    client_external_ref: str | None, settings: Settings
) -> dict[str, Any] | None:
    if not client_external_ref or not settings.ACCOUNTING_OPS_URL:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{settings.ACCOUNTING_OPS_URL.rstrip('/')}/api/v1/tax-figures/{client_external_ref}"
        )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return dict(response.json())
