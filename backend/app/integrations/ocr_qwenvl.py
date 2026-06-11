"""Form 1040 extraction — tiered, sovereign, all on-prem.

  Tier 1  digital PDF  → pypdf text layer + LLM_OCR_MODEL (qwen3.6 no-think)
                          structuring
  Tier 2  scanned PDF  → render pages (pymupdf) → traditional OCR microservice
                          (OCR_SERVICE_URL, e.g. PaddleOCR on a GTX 1070) → text
                          → LLM_OCR_MODEL structuring
  Tier 3  scanned PDF  → render pages → VLM (LLM_VISION_MODEL = `qwen3.6-vision`
                          on midboy1's RTX 6000, via the gateway) transcribes →
                          LLM_OCR_MODEL structures the transcription to JSON

Returns the OCR payload shape the extraction service expects, or None to fall
back to the manual hand-key path.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.integrations.llm import chat, chat_json, image_part, llm_enabled

logger = logging.getLogger("tax_planning_ops.ocr")

PROFILE = "form-1040-v1"

CANONICAL_FIELDS = [
    "f1040.line1z_wages", "f1040.line2b_taxable_interest", "f1040.line3a_qualified_div",
    "f1040.line3b_ordinary_div", "f1040.line4b_ira_taxable", "f1040.line5b_pensions_taxable",
    "f1040.line6b_ss_taxable", "f1040.line7_capital_gain", "f1040.line8_sch1_income",
    "f1040.line10_adjustments", "f1040.line12_deduction", "f1040.line13_qbi",
    "f1040.line25_withholding", "f1040.line26_est_payments", "f1040.line11_agi",
    "f1040.line15_taxable_income", "f1040.line24_total_tax",
]

_INSTRUCTION = (
    "You extract IRS Form 1040 figures for tax-planning. Return STRICT JSON only: an object "
    "mapping each present field key to its whole-DOLLAR amount as a number (no $, no commas). "
    "Use exactly these keys when present: " + ", ".join(CANONICAL_FIELDS) + ". "
    "Omit keys you cannot find. Do not guess. No prose, JSON object only."
)


def _pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("pdf text-layer parse failed: %s", exc)
        return ""


def _render_pages(pdf_bytes: bytes, dpi: int, max_pages: int = 3) -> list[bytes]:
    """Render PDF pages to PNG bytes (pymupdf). 1040 fits in 1-3 pages."""
    try:
        import fitz  # pymupdf

        out: list[bytes] = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in list(doc)[:max_pages]:
                pix = page.get_pixmap(dpi=dpi)
                out.append(pix.tobytes("png"))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("pdf render failed: %s", exc)
        return []


def _to_fields(parsed: object) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    fields: list[dict[str, Any]] = []
    for key in CANONICAL_FIELDS:
        if key not in parsed:
            continue
        try:
            dollars = float(str(parsed[key]).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        fields.append(
            {
                "field_key": key,
                "value_cents": int(round(dollars * 100)),
                "value_text": str(parsed[key]),
                "confidence": 0.9,
                "bbox": None,
            }
        )
    return fields


async def _structure_text(text: str, settings: Settings) -> dict[str, Any] | None:
    parsed = await chat_json(
        settings,
        [{"role": "user", "content": _INSTRUCTION + "\n\nFORM TEXT:\n" + text[:24000]}],
        model=settings.LLM_OCR_MODEL,
        max_tokens=900,
        no_think=True,
    )
    return parsed if isinstance(parsed, dict) else None


async def _ocr_service_text(images: list[bytes], settings: Settings) -> str:
    """POST page images to a traditional OCR microservice; concatenate text."""
    chunks: list[str] = []
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        for png in images:
            try:
                resp = await client.post(
                    settings.OCR_SERVICE_URL.rstrip("/") + "/ocr",
                    files={"file": ("page.png", png, "image/png")},
                )
                resp.raise_for_status()
                chunks.append(str(resp.json().get("text", "")))
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("ocr service page failed: %s", exc)
    return "\n".join(chunks).strip()


async def _vlm_text(images: list[bytes], settings: Settings) -> str:
    """VLM (qwen3.6-vision, mmproj) transcribes the rendered scan pages to text.
    Kept separate from structuring so the deterministic LLM_OCR_MODEL does the
    JSON — more robust than asking a reasoning VLM for JSON directly."""
    gateway = settings.LLM_VISION_GATEWAY_URL or settings.LLM_GATEWAY_URL
    if not (gateway and settings.LLM_VISION_MODEL):
        return ""
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "Transcribe every line of text in this IRS Form 1040 image exactly, "
            "including line numbers and dollar amounts. Plain text only.",
        }
    ]
    content += [image_part(png) for png in images]
    reply = await chat(
        settings,
        [{"role": "user", "content": content}],
        model=settings.LLM_VISION_MODEL,
        base_url=gateway,
        max_tokens=2000,
        # Thinking OFF: through the gateway the vision model honors this and
        # returns clean transcription in ~0.3s (verified). With thinking on,
        # reasoning_content eats the token budget and `content` comes back empty.
        no_think=True,
    )
    return reply or ""


async def extract_1040(pdf_bytes: bytes, settings: Settings) -> dict[str, Any] | None:
    if not settings.OCR_QWENVL_ENABLED or not llm_enabled(settings):
        return None

    # Tier 1 — text layer (most digital 1040s).
    text = _pdf_text(pdf_bytes)
    parsed: dict[str, Any] | None = None
    extractor = ""
    if text:
        parsed = await _structure_text(text, settings)
        extractor = f"text-layer+{settings.LLM_OCR_MODEL}"

    # Tiers 2/3 — scanned/image PDFs.
    if not parsed:
        images = _render_pages(pdf_bytes, settings.OCR_RENDER_DPI)
        if images and settings.OCR_SERVICE_URL:
            ocr_text = await _ocr_service_text(images, settings)
            if ocr_text:
                parsed = await _structure_text(ocr_text, settings)
                extractor = f"ocr-service+{settings.LLM_OCR_MODEL}"
        if not parsed and images:
            vision_text = await _vlm_text(images, settings)
            if vision_text:
                parsed = await _structure_text(vision_text, settings)
                extractor = f"vlm({settings.LLM_VISION_MODEL})+{settings.LLM_OCR_MODEL}"

    fields = _to_fields(parsed)
    if not fields:
        return None
    return {
        "profile": PROFILE,
        "extractor": extractor,
        "overall_confidence": 0.9,
        "fields": fields,
    }
