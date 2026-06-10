"""LiteLLM gateway client (OpenAI-compatible).

Drives the OCR field-structuring step and the planning agents. Reaches the
suite gateway (unicorn-litellm) over the shared docker network. Degrades to
None when unconfigured so every caller can fall back gracefully.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger("tax_planning_ops.llm")


def llm_enabled(settings: Settings) -> bool:
    return bool(settings.LLM_GATEWAY_URL)


async def chat(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1500,
) -> str | None:
    """Single chat completion → assistant text, or None on any failure."""
    if not llm_enabled(settings):
        return None
    url = settings.LLM_GATEWAY_URL.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    payload = {
        "model": model or settings.LLM_TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("llm chat failed (%s): %s", model, exc)
        return None


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """Pull the first JSON value out of a model reply (handles <think> blocks,
    code fences, and leading prose)."""
    if not text:
        return None
    cleaned = _THINK.sub("", text).strip()
    fence = _FENCE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    # find the first balanced { } or [ ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == opener:
                depth += 1
            elif cleaned[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except ValueError:
                        break
    return None


async def chat_json(settings: Settings, messages: list[dict[str, Any]], **kw: Any) -> Any | None:
    reply = await chat(settings, messages, **kw)
    return extract_json(reply) if reply else None
