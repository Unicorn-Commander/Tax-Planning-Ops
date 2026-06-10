from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings

PROFILE = "form-1040-v1"


async def extract_1040(blob_key: str, settings: Settings) -> dict[str, Any] | None:
    if not settings.OCR_QWENVL_ENABLED or not settings.OCR_QWENVL_URL:
        return None
    payload = {
        "blob_key": blob_key,
        "profile": PROFILE,
        "prompt": (
            "Extract IRS Form 1040 planning fields. Return canonical field keys, "
            "money values in cents, confidence, and page-relative bounding boxes."
        ),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{settings.OCR_QWENVL_URL.rstrip('/')}/extract", json=payload)
    response.raise_for_status()
    return dict(response.json())
