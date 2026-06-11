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
    base_url: str | None = None,
    no_think: bool = False,
) -> str | None:
    """Single chat completion → assistant text, or None on any failure.

    `base_url` overrides the default gateway (e.g. for the vision tier on a
    different LiteLLM instance). `messages` content may be a string OR a list of
    OpenAI content parts (text + image_url) for vision calls.
    """
    gateway = (base_url or settings.LLM_GATEWAY_URL).rstrip("/")
    if not gateway:
        return None
    url = gateway + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    payload: dict[str, Any] = {
        "model": model or settings.LLM_TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if no_think:
        # Qwen3 thinking off (llama.cpp --jinja honors this) → faster, clean
        # output. ~0.8s vs 1.4s for gemma4 on 1040 structuring, equally exact.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
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


def image_part(png_bytes: bytes) -> dict[str, Any]:
    """OpenAI vision content part from raw PNG bytes."""
    import base64

    b64 = base64.b64encode(png_bytes).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
