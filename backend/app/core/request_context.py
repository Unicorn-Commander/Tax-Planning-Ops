from __future__ import annotations

from contextvars import ContextVar

# Which "door" the current request came through — the no-wrappers triad. The
# auth middleware sets it from the X-UC-Door header (the GUI sends "gui", the
# MCP server "mcp", the Console "console"); anything else defaults to "api".
# It is task-local (one value per in-flight request) and is stamped into audit
# events as action provenance, which the door-usage stats then count.
KNOWN_DOORS = ("gui", "console", "mcp", "api")

current_door: ContextVar[str] = ContextVar("current_door", default="api")


def normalize_door(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    return value if value in KNOWN_DOORS else "api"
