"""Schemas for the agent registry + door-usage stats (spec §9.6).

These power the firm shell's Desk "duty band" (the roster of agent-backed
capabilities and whether each has recent activity) and the Staff "door usage"
panel (how mutating actions split across gui/console/mcp/api). Both read REAL
state — the roster enumerates the app's actual capabilities and derives activity
from the audit journal; door-stats counts real journal rows. Nothing is faked.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AgentCard(BaseModel):
    """One agent-backed capability of the app and its latest journal activity.

    ``kind`` separates a true LLM-backed ``agent`` (Strategist, Plan Proposer)
    from a deterministic ``engine`` capability (Book Scanner, Quarterly) and a
    ``service`` (Intake/OCR). ``status`` is ``available`` when the journal shows
    a mapped event, else ``idle`` — it never claims activity the journal lacks.
    """

    key: str
    name: str
    role: str
    kind: Literal["engine", "agent", "service"]
    status: Literal["available", "idle"]
    last_event_at: datetime | None
    last_event_type: str | None
    capabilities: list[str]


class RegistryOut(BaseModel):
    """The agent roster. ``generated_at`` is intentionally omitted here — the
    caller stamps the response time so the service stays clock-free and testable.
    """

    agents: list[AgentCard]


class DoorCount(BaseModel):
    """How many mutating journal events came through one door in the window."""

    door: str
    count: int


class DoorStatsOut(BaseModel):
    """Door-usage rollup over the window: total mutating events and the per-door
    split. Counts only what the journal records (signs, reconciles, confirms,
    plan writes) — it is provenance of mutating actions, not all traffic.
    """

    total: int
    by_door: list[DoorCount]
    window_days: int
