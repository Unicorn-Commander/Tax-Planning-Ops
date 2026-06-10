from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from app.core.config import Settings


async def render(payload: dict[str, Any], settings: Settings) -> bytes:
    if not getattr(settings, "PDF_SERVICE_URL", ""):
        return json.dumps(payload, sort_keys=True, default=str).encode()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.PDF_SERVICE_URL.rstrip('/')}/render",
            json=payload,
        )
    response.raise_for_status()
    return response.content


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
