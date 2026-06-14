"""Implementation tasks — statutory-deadline catalog + service logic.

The catalog resolvers are pure (key + tax_year -> date), so they're tested
directly. The service's completion/soft-delete logic is exercised against a tiny
in-memory fake session (the same approach as tests/test_memo.py) so no DB is
touched; the RLS/WITH-CHECK path lives in tests/test_rls_integration.py's style.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.models.implementation import ImplementationTask
from app.schemas.tasks import TaskUpdateIn
from app.services.tasks import delete_task, update_task
from app.statutory_deadlines import (
    STATUTORY_DEADLINES,
    list_statutory_deadlines,
    resolve_deadline,
)

TAX_YEAR = 2026


# --------------------------------------------------------------------------- #
# resolve_deadline — the conventional statutory dates.
# --------------------------------------------------------------------------- #
def test_quarterly_estimate_dates() -> None:
    # Q1–Q3 fall within the tax year; Q4 rolls to Jan 15 of the next year.
    assert resolve_deadline("q1_estimate", TAX_YEAR) == date(2026, 4, 15)
    assert resolve_deadline("q2_estimate", TAX_YEAR) == date(2026, 6, 15)
    assert resolve_deadline("q3_estimate", TAX_YEAR) == date(2026, 9, 15)
    assert resolve_deadline("q4_estimate", TAX_YEAR) == date(2027, 1, 15)


def test_contribution_deadlines_are_apr15_next_year() -> None:
    for key in ("ira_contribution", "roth_contribution", "hsa_contribution"):
        assert resolve_deadline(key, TAX_YEAR) == date(2027, 4, 15), key


def test_form_8606_and_extension_track_unextended_return_date() -> None:
    assert resolve_deadline("form_8606", TAX_YEAR) == date(2027, 4, 15)
    assert resolve_deadline("extension_1040", TAX_YEAR) == date(2027, 4, 15)


def test_rmd_is_year_end_of_tax_year() -> None:
    assert resolve_deadline("rmd", TAX_YEAR) == date(2026, 12, 31)


def test_solo_401k_employee_is_year_end_of_tax_year() -> None:
    assert resolve_deadline("solo_401k_employee", TAX_YEAR) == date(2026, 12, 31)


def test_scorp_election_2553_is_mar15_of_tax_year() -> None:
    # IRC §1362(b): within 2 months + 15 days of the start of the tax year.
    assert resolve_deadline("scorp_election_2553", TAX_YEAR) == date(2026, 3, 15)


def test_fbar_is_oct15_automatic_extension() -> None:
    assert resolve_deadline("fbar", TAX_YEAR) == date(2027, 10, 15)


def test_unknown_key_returns_none() -> None:
    assert resolve_deadline("not_a_real_key", TAX_YEAR) is None


def test_resolvers_track_a_different_tax_year() -> None:
    # The resolver is a function of tax_year, not a hardcoded constant.
    assert resolve_deadline("q1_estimate", 2030) == date(2030, 4, 15)
    assert resolve_deadline("rmd", 2030) == date(2030, 12, 31)
    assert resolve_deadline("ira_contribution", 2030) == date(2031, 4, 15)


# --------------------------------------------------------------------------- #
# list_statutory_deadlines — shape + coverage.
# --------------------------------------------------------------------------- #
def test_list_shape_and_keys() -> None:
    rows = list_statutory_deadlines(TAX_YEAR)
    assert len(rows) == len(STATUTORY_DEADLINES)
    for row, entry in zip(rows, STATUTORY_DEADLINES, strict=True):
        assert set(row) == {"key", "label", "citation", "due_date"}
        assert row["key"] == entry.key  # preserves catalog (chase) order
        assert isinstance(row["due_date"], date)
        assert row["due_date"] == entry.resolver(TAX_YEAR)


def test_catalog_keys_are_unique_and_complete() -> None:
    keys = [entry.key for entry in STATUTORY_DEADLINES]
    assert len(keys) == len(set(keys))  # no dup keys
    expected = {
        "q1_estimate", "q2_estimate", "q3_estimate", "q4_estimate",
        "ira_contribution", "roth_contribution", "sep_ira", "solo_401k_employee",
        "hsa_contribution", "form_8606", "rmd", "scorp_election_2553",
        "backdoor_roth", "fbar", "extension_1040",
    }
    assert set(keys) == expected


def test_every_catalog_entry_has_a_citation() -> None:
    for entry in STATUTORY_DEADLINES:
        assert entry.citation and entry.label


# --------------------------------------------------------------------------- #
# Service logic against a minimal async fake session (no DB).
# --------------------------------------------------------------------------- #
class _FakeSession:
    """Returns a preset object from ``get`` and records flushes; ``refresh`` is a
    no-op. Just enough for the task service's update/delete paths."""

    def __init__(self, obj: Any) -> None:
        self._obj = obj
        self.flushed = 0

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._obj

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, _obj: Any) -> None:
        return None


def _task(**overrides: Any) -> ImplementationTask:
    base: dict[str, Any] = {
        "workspace_id": uuid4(),
        "client_tax_year_id": uuid4(),
        "title": "Send Q4 voucher",
        "owner": "advisor",
        "status": "open",
        "evidence_blob_key": None,
        "evidence_uploaded_at": None,
        "sort_order": 0,
        "deleted_at": None,
    }
    base.update(overrides)
    return ImplementationTask(**base)


@pytest.mark.asyncio
async def test_update_done_with_evidence_stamps_uploaded_at() -> None:
    task = _task(status="open", evidence_blob_key="ws/ty/evidence/x.pdf")
    db = _FakeSession(task)
    out = await update_task(
        db, task_id=uuid4(), payload=TaskUpdateIn(status="done")
    )
    assert out.status == "done"
    assert out.evidence_uploaded_at is not None
    assert out.evidence_uploaded_at.tzinfo is not None


@pytest.mark.asyncio
async def test_update_done_without_evidence_does_not_stamp() -> None:
    task = _task(status="open")
    db = _FakeSession(task)
    out = await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(status="done"))
    assert out.status == "done"
    assert out.evidence_uploaded_at is None


@pytest.mark.asyncio
async def test_update_evidence_stamp_is_idempotent() -> None:
    stamped = datetime(2026, 5, 1, tzinfo=UTC)
    task = _task(
        status="done",
        evidence_blob_key="ws/ty/evidence/x.pdf",
        evidence_uploaded_at=stamped,
    )
    db = _FakeSession(task)
    out = await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(note="touch"))
    assert out.evidence_uploaded_at == stamped  # not overwritten


@pytest.mark.asyncio
async def test_update_applies_only_set_fields() -> None:
    task = _task(title="orig", owner="advisor", amount_cents=5000)
    db = _FakeSession(task)
    out = await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(title="renamed"))
    assert out.title == "renamed"
    assert out.owner == "advisor"  # untouched
    assert out.amount_cents == 5000  # untouched


@pytest.mark.asyncio
async def test_update_can_clear_a_field_with_explicit_null() -> None:
    task = _task(amount_cents=5000)
    db = _FakeSession(task)
    out = await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(amount_cents=None))
    assert out.amount_cents is None


@pytest.mark.asyncio
async def test_update_missing_task_raises_lookup() -> None:
    db = _FakeSession(None)
    with pytest.raises(LookupError):
        await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(title="x"))


@pytest.mark.asyncio
async def test_update_soft_deleted_task_raises_lookup() -> None:
    task = _task(deleted_at=datetime.now(UTC))
    db = _FakeSession(task)
    with pytest.raises(LookupError):
        await update_task(db, task_id=uuid4(), payload=TaskUpdateIn(title="x"))


@pytest.mark.asyncio
async def test_delete_sets_deleted_at() -> None:
    task = _task()
    db = _FakeSession(task)
    await delete_task(db, task_id=uuid4())
    assert task.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_missing_task_raises_lookup() -> None:
    db = _FakeSession(None)
    with pytest.raises(LookupError):
        await delete_task(db, task_id=uuid4())
