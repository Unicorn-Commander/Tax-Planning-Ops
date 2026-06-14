"""Agent registry + door-stats service logic (spec §9.6).

The roster is a static catalog whose activity is derived from a single grouped
journal query, and door-stats is a single grouped/count query — both are
exercised against a tiny in-memory fake session (the same approach as
tests/test_memo.py / tests/test_tasks.py) that answers ``execute`` from a FIFO of
canned result rows. No live DB is touched; the RLS-scoped read path lives in
tests/test_rls_integration.py's style.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.services.registry import _KNOWN_DOORS, _ROSTER, agent_registry, door_stats

WS = uuid4()


# --------------------------------------------------------------------------- #
# A minimal async fake session: ``execute`` returns the next canned result whose
# ``.all()`` yields the rows it was given. Just enough for the two grouped reads.
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, results: list[list[tuple[Any, ...]]]) -> None:
        self._results = list(results)

    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult(self._results.pop(0) if self._results else [])


# --------------------------------------------------------------------------- #
# Roster catalog — the honest, expected shape (independent of any DB).
# --------------------------------------------------------------------------- #
def test_roster_has_the_expected_capability_keys() -> None:
    keys = {entry["key"] for entry in _ROSTER}
    assert keys == {
        "strategist",
        "book_scanner",
        "plan_proposer",
        "intake_ocr",
        "quarterly",
    }


def test_strategist_capabilities_are_the_spec_set() -> None:
    strategist = next(e for e in _ROSTER if e["key"] == "strategist")
    assert strategist["capabilities"] == [
        "draft-memo",
        "optimize-roth",
        "optimize-scorp",
        "emr-sweep",
    ]
    assert strategist["kind"] == "agent"


def test_each_core_capability_is_present() -> None:
    by_key = {e["key"]: e for e in _ROSTER}
    assert "scan-book" in by_key["book_scanner"]["capabilities"]
    assert "propose-plan" in by_key["plan_proposer"]["capabilities"]
    assert "extract-1040" in by_key["intake_ocr"]["capabilities"]
    assert "compute-quarterly" in by_key["quarterly"]["capabilities"]


# --------------------------------------------------------------------------- #
# agent_registry — activity is derived honestly from the grouped journal query.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_registry_all_idle_when_no_events() -> None:
    db = _FakeSession([[]])  # grouped query returns no rows
    roster = await agent_registry(db, workspace_id=WS)
    assert len(roster) == len(_ROSTER)
    assert all(a["status"] == "idle" for a in roster)
    assert all(a["last_event_at"] is None for a in roster)
    assert all(a["last_event_type"] is None for a in roster)
    # Shape is complete for every card.
    for card in roster:
        assert set(card) == {
            "key",
            "name",
            "role",
            "kind",
            "status",
            "last_event_at",
            "last_event_type",
            "capabilities",
        }


@pytest.mark.asyncio
async def test_registry_marks_mapped_agent_available() -> None:
    signed_at = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    # Strategist maps memo.signed; only that row is returned.
    db = _FakeSession([[("memo.signed", signed_at)]])
    roster = {a["key"]: a for a in await agent_registry(db, workspace_id=WS)}

    strategist = roster["strategist"]
    assert strategist["status"] == "available"
    assert strategist["last_event_at"] == signed_at
    assert strategist["last_event_type"] == "memo.signed"

    # Everything else stays idle — no fabricated activity.
    for key, card in roster.items():
        if key != "strategist":
            assert card["status"] == "idle"
            assert card["last_event_at"] is None


@pytest.mark.asyncio
async def test_registry_picks_newest_event_for_a_capability() -> None:
    older = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    newer = datetime(2026, 6, 9, 9, 0, tzinfo=UTC)
    # Intake/OCR maps both upload + confirm; newest must win.
    db = _FakeSession(
        [
            [
                ("return_document_uploaded", older),
                ("return_confirmed", newer),
            ]
        ]
    )
    roster = {a["key"]: a for a in await agent_registry(db, workspace_id=WS)}
    intake = roster["intake_ocr"]
    assert intake["status"] == "available"
    assert intake["last_event_at"] == newer
    assert intake["last_event_type"] == "return_confirmed"


@pytest.mark.asyncio
async def test_read_only_book_scanner_is_always_idle() -> None:
    # Even if (somehow) a row for another agent's event comes back, the book
    # scanner has no mapped events, so it can never flip to available.
    db = _FakeSession([[("memo.signed", datetime.now(UTC))]])
    roster = {a["key"]: a for a in await agent_registry(db, workspace_id=WS)}
    assert roster["book_scanner"]["status"] == "idle"
    assert roster["book_scanner"]["last_event_type"] is None


# --------------------------------------------------------------------------- #
# door_stats — grouping + summing over the journal.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_door_stats_groups_and_sums() -> None:
    db = _FakeSession([[("gui", 7), ("mcp", 3), ("api", 2)]])
    out = await door_stats(db, workspace_id=WS, window_days=30)

    assert out["window_days"] == 30
    assert out["total"] == 12
    by_door = {d["door"]: d["count"] for d in out["by_door"]}
    assert by_door["gui"] == 7
    assert by_door["mcp"] == 3
    assert by_door["api"] == 2
    # All known doors surface, including a zero-count one.
    assert by_door["console"] == 0
    assert set(_KNOWN_DOORS).issubset(by_door)


@pytest.mark.asyncio
async def test_door_stats_zero_when_empty() -> None:
    db = _FakeSession([[]])
    out = await door_stats(db, workspace_id=WS, window_days=7)
    assert out["total"] == 0
    assert out["window_days"] == 7
    # Every known door present at zero, nothing invented.
    assert {d["door"] for d in out["by_door"]} == set(_KNOWN_DOORS)
    assert all(d["count"] == 0 for d in out["by_door"])


@pytest.mark.asyncio
async def test_door_stats_surfaces_unknown_door_value() -> None:
    # A door value outside the known set (or a NULL) is surfaced, not dropped.
    db = _FakeSession([[("gui", 4), ("weird", 1), (None, 2)]])
    out = await door_stats(db, workspace_id=WS)
    by_door = {d["door"]: d["count"] for d in out["by_door"]}
    assert by_door["gui"] == 4
    assert by_door["weird"] == 1
    assert by_door["unknown"] == 2  # NULL door labeled
    assert out["total"] == 7


@pytest.mark.asyncio
async def test_door_stats_clamps_window_to_at_least_one() -> None:
    db = _FakeSession([[]])
    out = await door_stats(db, workspace_id=WS, window_days=0)
    assert out["window_days"] == 1


@pytest.mark.asyncio
async def test_door_stats_default_window_is_30() -> None:
    db = _FakeSession([[]])
    out = await door_stats(db, workspace_id=WS)
    assert out["window_days"] == 30
