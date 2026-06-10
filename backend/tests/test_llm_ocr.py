from __future__ import annotations

import pytest

from app.core.config import Settings
from app.integrations import ocr_qwenvl
from app.integrations.llm import extract_json


def test_extract_json_strips_think_and_fences() -> None:
    assert extract_json('<think>reasoning…</think>```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prose before {"x": 2, "y": {"z": 3}} after') == {"x": 2, "y": {"z": 3}}
    assert extract_json("no json here") is None


@pytest.mark.asyncio
async def test_extract_1040_maps_dollars_to_cents(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(OCR_QWENVL_ENABLED=True, LLM_GATEWAY_URL="http://gw/v1", LLM_API_KEY="k")

    monkeypatch.setattr(ocr_qwenvl, "_pdf_text", lambda _b: "Form 1040 ... line 1z 185000 ... line 11 201700")

    async def fake_chat_json(*_a: object, **_k: object) -> dict[str, object]:
        return {"f1040.line1z_wages": 185000, "f1040.line11_agi": "201,700", "bogus": 5}

    monkeypatch.setattr(ocr_qwenvl, "chat_json", fake_chat_json)

    payload = await ocr_qwenvl.extract_1040(b"%PDF-fake", settings)
    assert payload is not None
    by_key = {f["field_key"]: f for f in payload["fields"]}
    assert by_key["f1040.line1z_wages"]["value_cents"] == 18_500_000
    assert by_key["f1040.line11_agi"]["value_cents"] == 20_170_000  # comma-tolerant
    assert "bogus" not in by_key  # non-canonical keys dropped
    assert payload["overall_confidence"] > 0


@pytest.mark.asyncio
async def test_extract_1040_degrades_when_disabled() -> None:
    settings = Settings(OCR_QWENVL_ENABLED=False)
    assert await ocr_qwenvl.extract_1040(b"%PDF", settings) is None
