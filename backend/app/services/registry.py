"""Agent registry + door-usage stats (spec §9.6).

The "agents" here are this app's REAL agent-backed capabilities — the same ones
exposed under ``app/api/agents.py`` plus the intake/quarterly services that write
the journal. There is no separate agent table; the roster is the honest static
catalog of what the app can do, and each capability's *activity* (last event,
available vs idle) is derived from the append-only audit journal by mapping the
event types a capability actually emits.

Honesty notes on the mapping:

* **Strategist** authors the findings/memo and reconciles realized outcomes, so
  it owns the memo-sign and outcome-reconcile events (and the plan-write events
  that the strategist/scenario flow produces).
* **Book Scanner** is READ-ONLY (it ranks the book; it writes nothing), so it has
  no journal events of its own and reports ``idle`` until that changes. We do not
  invent activity for it.
* **Plan Proposer** is propose-only, but an advisor applying/finalizing a plan is
  the genuine downstream signal of a proposal acted on, so it maps to the plan
  lifecycle events. (Documented as downstream, not the propose call itself.)
* **Intake / OCR** owns document upload + return confirmation.
* **Quarterly** owns the quarterly-estimate computation event.

Door-stats counts journal rows grouped by ``payload->>'door'`` within a window —
the provenance of *mutating* actions (every journal write stamps its door), not
all read traffic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_year import AuditJournal

# The honest catalog. Order = duty-band order. Each entry lists the journal
# event types that genuinely reflect that capability's work; an empty tuple
# means the capability writes no journal event (read-only) and is always idle.
_ROSTER: tuple[dict[str, Any], ...] = (
    {
        "key": "strategist",
        "name": "Strategist",
        "role": "Findings + advisor memo",
        "kind": "agent",
        "capabilities": ["draft-memo", "optimize-roth", "optimize-scorp", "emr-sweep"],
        # Memo sign/seal, realized-outcome reconcile, and the plan/scenario
        # writes the strategist & scenario flow produce.
        "events": (
            "memo.signed",
            "outcome.reconciled",
            "tax_plan_created",
            "scenario_assumptions_updated",
        ),
    },
    {
        "key": "book_scanner",
        "name": "Book Scanner",
        "role": "Book-wide opportunity scan",
        "kind": "engine",
        "capabilities": ["scan-book"],
        # Read-only: ranks the firm's book, writes nothing → no events, idle.
        "events": (),
    },
    {
        "key": "plan_proposer",
        "name": "Plan Proposer",
        "role": "Propose-only prioritized plan",
        "kind": "agent",
        "capabilities": ["propose-plan"],
        # Propose-only itself writes nothing; an applied/finalized plan is the
        # genuine downstream evidence a proposal was acted on.
        "events": ("tax_plan_created", "plan_finalized", "plan_pdf_generated"),
    },
    {
        "key": "intake_ocr",
        "name": "Intake / OCR",
        "role": "1040 extraction + confirmation",
        "kind": "service",
        "capabilities": ["extract-1040", "confirm-return"],
        "events": ("return_document_uploaded", "return_confirmed"),
    },
    {
        "key": "quarterly",
        "name": "Quarterly",
        "role": "Estimated-payment schedule",
        "kind": "engine",
        "capabilities": ["compute-quarterly"],
        "events": ("quarterly_computed",),
    },
)

# Doors are a fixed, known set (the provenance stamp is one of these); surfacing
# all four — including zero-count doors — makes the Staff panel legible.
_KNOWN_DOORS: tuple[str, ...] = ("gui", "console", "mcp", "api")


async def agent_registry(db: AsyncSession, *, workspace_id: UUID) -> list[dict[str, Any]]:
    """Return the app's agent-backed capability roster with REAL, journal-derived
    activity per capability.

    Each capability's ``last_event_at`` / ``last_event_type`` / ``status`` is
    computed from the audit journal: for every event type a capability claims, we
    take the newest matching row in the workspace. A capability with at least one
    mapped event is ``available``; one with none (or a read-only capability that
    emits no events) is ``idle``. RLS scopes the journal to the workspace; the
    explicit ``workspace_id`` filter is defense-in-depth.
    """
    # All event types any capability cares about — one grouped query, newest row
    # per type, instead of N queries.
    wanted: set[str] = {ev for entry in _ROSTER for ev in entry["events"]}
    latest_by_type: dict[str, datetime] = {}
    if wanted:
        result = await db.execute(
            select(
                AuditJournal.event_type,
                func.max(AuditJournal.created_at),
            )
            .where(AuditJournal.workspace_id == workspace_id)
            .where(AuditJournal.event_type.in_(wanted))
            .group_by(AuditJournal.event_type)
        )
        for event_type, latest_at in result.all():
            if latest_at is not None:
                latest_by_type[event_type] = latest_at

    roster: list[dict[str, Any]] = []
    for entry in _ROSTER:
        last_at: datetime | None = None
        last_type: str | None = None
        for event_type in entry["events"]:
            seen = latest_by_type.get(event_type)
            if seen is not None and (last_at is None or seen > last_at):
                last_at = seen
                last_type = event_type
        roster.append(
            {
                "key": entry["key"],
                "name": entry["name"],
                "role": entry["role"],
                "kind": entry["kind"],
                "status": "available" if last_at is not None else "idle",
                "last_event_at": last_at,
                "last_event_type": last_type,
                "capabilities": list(entry["capabilities"]),
            }
        )
    return roster


async def door_stats(
    db: AsyncSession, *, workspace_id: UUID, window_days: int = 30
) -> dict[str, Any]:
    """Count audit-journal rows in the workspace within ``window_days``, grouped
    by the door (``payload->>'door'``) the action came through.

    This is the provenance of MUTATING actions only — every journal write (memo
    signs, outcome reconciles, return confirms, plan writes, etc.) stamps the
    door it came through. It is not a measure of all (read) traffic. ``window_days``
    is clamped to at least 1. All four known doors are returned (zero-count
    included) for a legible panel; any unexpected door value found is appended.
    """
    window_days = max(1, int(window_days))
    since = datetime.now(UTC) - timedelta(days=window_days)
    door_col = AuditJournal.payload["door"].astext

    result = await db.execute(
        select(door_col, func.count(AuditJournal.id))
        .where(AuditJournal.workspace_id == workspace_id)
        .where(AuditJournal.created_at >= since)
        .group_by(door_col)
    )

    counts: dict[str | None, int] = {}
    for door_value, count in result.all():
        counts[door_value] = int(count or 0)

    by_door: list[dict[str, Any]] = [
        {"door": door, "count": counts.get(door, 0)} for door in _KNOWN_DOORS
    ]
    # Surface any door value the journal holds that isn't in the known set
    # (including a NULL/missing door, labeled "unknown") rather than dropping it.
    for door_value, count in counts.items():
        if door_value not in _KNOWN_DOORS:
            by_door.append({"door": door_value or "unknown", "count": count})

    total = sum(item["count"] for item in by_door)
    return {"total": total, "by_door": by_door, "window_days": window_days}
