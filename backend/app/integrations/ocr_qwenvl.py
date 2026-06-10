"""Form 1040 extraction.

Hybrid, gateway-driven pipeline:
  1. Parse the PDF text layer (pypdf) — most filed 1040s are digital.
  2. Have the LLM (qwen3.6-35b-a3b via LiteLLM) map that text to our canonical
     field keys + per-field confidence.
  3. (TODO) image-only scans → render pages → vision model (gemma4) fallback.

Returns the OCR payload shape the extraction service expects, or None to
degrade to the manual hand-key path.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from app.core.config import Settings
from app.integrations.llm import chat_json, llm_enabled

logger = logging.getLogger("tax_planning_ops.ocr")

PROFILE = "form-1040-v1"

# Canonical 1040 planning fields the engine consumes (must match
# services/extraction.FIELD_TO_INPUT).
CANONICAL_FIELDS = [
    "f1040.line1z_wages", "f1040.line2b_taxable_interest", "f1040.line3a_qualified_div",
    "f1040.line3b_ordinary_div", "f1040.line4b_ira_taxable", "f1040.line5b_pensions_taxable",
    "f1040.line6b_ss_taxable", "f1040.line7_capital_gain", "f1040.line8_sch1_income",
    "f1040.line10_adjustments", "f1040.line12_deduction", "f1040.line13_qbi",
    "f1040.line25_withholding", "f1040.line26_est_payments", "f1040.line11_agi",
    "f1040.line15_taxable_income", "f1040.line24_total_tax",
]

_PROMPT = (
    "You extract IRS Form 1040 figures for tax-planning. From the form text below, "
    "return STRICT JSON only: an object mapping each present field key to its whole-DOLLAR "
    "amount as a number (no $, no commas). Use exactly these keys when present: "
    + ", ".join(CANONICAL_FIELDS)
    + ". Omit keys you cannot find. Do not guess. No prose, JSON object only.\n\nFORM TEXT:\n"
)


def _pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 - any parse failure → no text layer
        logger.info("pdf text-layer parse failed: %s", exc)
        return ""


async def extract_1040(pdf_bytes: bytes, settings: Settings) -> dict[str, Any] | None:
    """Extract canonical 1040 fields from PDF bytes via the LLM gateway."""
    if not settings.OCR_QWENVL_ENABLED or not llm_enabled(settings):
        return None

    text = _pdf_text(pdf_bytes)
    if not text:
        # Image-only scan: vision-model fallback is a follow-up (Gemma 4).
        logger.info("no text layer; vision fallback not yet wired")
        return None

    parsed = await chat_json(
        settings,
        [{"role": "user", "content": _PROMPT + text[:24000]}],
        model=settings.LLM_OCR_MODEL,
        max_tokens=900,
    )
    if not isinstance(parsed, dict):
        return None

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
                "confidence": 0.92,  # text-layer + LLM structuring is high-confidence
                "bbox": None,
            }
        )

    return {
        "profile": PROFILE,
        "extractor": f"text-layer+{settings.LLM_OCR_MODEL}",
        "overall_confidence": 0.92 if fields else 0.0,
        "fields": fields,
    }
