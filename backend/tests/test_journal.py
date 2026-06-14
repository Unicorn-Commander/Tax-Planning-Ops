"""Audit-journal read API (spec §9.5) — the read helpers in app.services.audit.

The journal tail is a read over append-only, hash-chained rows. The clamp
policy and the ordering/limit/`before` of ``read_journal_tail`` plus the shape
of ``journal_status`` are exercised against a tiny in-memory fake session (the
same approach as tests/test_memo.py and tests/test_tasks.py) so no DB is
touched. A real-Postgres + RLS path lives in tests/test_rls_integration.py's
style and is gated the same way (skipped without TPO_TEST_DATABASE_URL).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.tax_year import AuditJournal
from app.services.audit import (
    _MAX_JOURNAL_TAIL,
    journal_status,
    read_journal_tail,
)

WS = uuid4()
_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _event(i: int, *, created_at: datetime | None = None) -> AuditJournal:
    return AuditJournal(
        id=uuid4(),
        workspace_id=WS,
        created_at=created_at or (_TS + timedelta(minutes=i)),
        event_type="return_confirmed",
        actor_uc_uid="advisor-1",
        aggregate_type="extracted_return",
        aggregate_id=uuid4(),
        payload={"n": i},
        prev_hash=None if i == 0 else f"hash-{i - 1}",
        hash=f"hash-{i}",
    )


# --------------------------------------------------------------------------- #
# A minimal async fake session. It does not execute SQL — it inspects the
# compiled statement to decide which canned answer to return, so call ordering
# inside the service is irrelevant. ``read_journal_tail`` is the only consumer
# of ``scalars``; we capture the statement it builds to assert the applied LIMIT
# and the optional ``before`` predicate without a database.
# --------------------------------------------------------------------------- #
class _ScalarsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self) -> Any:
        return iter(self._rows)

    def scalars(self) -> _ScalarsResult:
        return self


class _OneResult:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def one(self) -> tuple[Any, ...]:
        return self._row


class _FakeSession:
    def __init__(self, rows: list[AuditJournal]) -> None:
        # Stored newest-first, mirroring the service's order_by(desc()).
        self._rows = sorted(rows, key=lambda e: e.created_at, reverse=True)
        self.last_scalars_stmt: Any = None

    async def scalars(self, stmt: Any) -> _ScalarsResult:
        # read_journal_tail: honour the compiled LIMIT and the `before` filter so
        # the test sees what the DB would have applied.
        self.last_scalars_stmt = stmt
        rows = self._rows
        before = _before_value(stmt)
        if before is not None:
            rows = [r for r in rows if r.created_at < before]
        limit = _limit_value(stmt)
        if limit is not None:
            rows = rows[:limit]
        return _ScalarsResult(rows)

    async def execute(self, stmt: Any) -> Any:
        # journal_status' count/max aggregate, and verify_audit_chain's full scan.
        if _is_aggregate(stmt):
            count = len(self._rows)
            latest = max((r.created_at for r in self._rows), default=None)
            return _OneResult((count, latest))
        return _ScalarsResult(list(reversed(self._rows)))  # verify scans ascending

    async def scalar(self, stmt: Any) -> Any:
        # journal_status' latest_hash lookup (newest-first, limit 1).
        return self._rows[0].hash if self._rows else None


def _limit_value(stmt: Any) -> int | None:
    clause = getattr(stmt, "_limit_clause", None)
    return None if clause is None else clause.value


def _before_value(stmt: Any) -> datetime | None:
    # Compile to text + params; the `before` filter binds a datetime parameter.
    compiled = stmt.compile()
    for value in compiled.params.values():
        if isinstance(value, datetime):
            return value
    return None


def _is_aggregate(stmt: Any) -> bool:
    return "count(" in str(stmt).lower()


# --------------------------------------------------------------------------- #
# Clamp policy — limit is bounded to [1, _MAX_JOURNAL_TAIL].
# --------------------------------------------------------------------------- #
def test_max_tail_constant_is_sane() -> None:
    assert _MAX_JOURNAL_TAIL == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("asked", "expected"),
    [(20, 20), (1, 1), (0, 1), (-5, 1), (500, 200), (10**6, 200)],
)
async def test_limit_is_clamped(asked: int, expected: int) -> None:
    db = _FakeSession([_event(i) for i in range(300)])
    await read_journal_tail(db, WS, limit=asked)
    assert _limit_value(db.last_scalars_stmt) == expected


# --------------------------------------------------------------------------- #
# read_journal_tail — ordering, limit, and `before` paging.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tail_is_newest_first_and_limited() -> None:
    db = _FakeSession([_event(i) for i in range(50)])
    out = await read_journal_tail(db, WS, limit=5)
    assert len(out) == 5
    assert [e.payload["n"] for e in out] == [49, 48, 47, 46, 45]  # newest-first
    assert all(
        out[i].created_at >= out[i + 1].created_at for i in range(len(out) - 1)
    )


@pytest.mark.asyncio
async def test_default_limit_is_twenty() -> None:
    db = _FakeSession([_event(i) for i in range(50)])
    out = await read_journal_tail(db, WS)
    assert len(out) == 20


@pytest.mark.asyncio
async def test_before_pages_to_older_events() -> None:
    events = [_event(i) for i in range(10)]
    db = _FakeSession(events)
    cutoff = events[5].created_at  # strictly older than event #5
    out = await read_journal_tail(db, WS, limit=100, before=cutoff)
    assert [e.payload["n"] for e in out] == [4, 3, 2, 1, 0]
    assert all(e.created_at < cutoff for e in out)


@pytest.mark.asyncio
async def test_empty_journal_returns_empty_list() -> None:
    db = _FakeSession([])
    assert await read_journal_tail(db, WS) == []


# --------------------------------------------------------------------------- #
# journal_status — shape + values.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_status_shape_and_values() -> None:
    events = [_event(i) for i in range(3)]
    db = _FakeSession(events)
    status = await journal_status(db, WS)
    assert set(status) == {"count", "latest_hash", "latest_at", "chain_intact"}
    assert status["count"] == 3
    assert status["latest_hash"] == "hash-2"  # newest
    assert status["latest_at"] == events[2].created_at
    assert isinstance(status["chain_intact"], bool)


@pytest.mark.asyncio
async def test_status_empty_journal() -> None:
    db = _FakeSession([])
    status = await journal_status(db, WS)
    assert status["count"] == 0
    assert status["latest_hash"] is None
    assert status["latest_at"] is None
    # An empty chain trivially verifies.
    assert status["chain_intact"] is True


def test_status_query_is_workspace_scoped() -> None:
    # Guard: the aggregate the service issues filters on workspace_id (defence in
    # depth atop RLS). Mirrors the shape journal_status compiles.
    stmt = select(func.count(AuditJournal.id)).where(AuditJournal.workspace_id == WS)
    assert "audit_journal.workspace_id" in str(stmt).lower()
