"""Memo persistence + sign/seal logic.

The hashing and the version-bump policy are pure enough to test without a live
DB: ``compute_payload_hash`` / content-hash are pure functions, and the draft
policy in ``persist_strategist_run`` / ``save_memo_draft`` is exercised against a
tiny in-memory fake session that answers only the queries those functions make
(``generate_strategist_memo`` is monkeypatched, so no engine/LLM/DB is touched).
A real-Postgres seal path lives in tests/test_rls_integration.py's style and is
gated the same way (skipped without TPO_TEST_DATABASE_URL).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.models.memo import Memo, StrategistRun
from app.services import memo as memo_svc
from app.services.memo import compute_payload_hash, persist_strategist_run, save_memo_draft

WS = uuid4()
TY = uuid4()

_FINDINGS = [
    {"title": "Roth fill", "impact_kind": "savings", "estimated_impact_cents": 120_000},
    {"title": "IRMAA cliff", "impact_kind": "cost", "estimated_impact_cents": 90_000},
]


# --------------------------------------------------------------------------- #
# Pure hashing
# --------------------------------------------------------------------------- #
def test_payload_hash_is_deterministic() -> None:
    assert compute_payload_hash(_FINDINGS, "memo body") == compute_payload_hash(
        _FINDINGS, "memo body"
    )


def test_payload_hash_matches_audit_canonicalization() -> None:
    # Same canonical form audit.compute_audit_hash uses, so storage re-hashes 1:1.
    expected = hashlib.sha256(
        json.dumps(
            {"findings": _FINDINGS, "memo": "memo body"},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    assert compute_payload_hash(_FINDINGS, "memo body") == expected


def test_payload_hash_changes_when_findings_change() -> None:
    other = [*_FINDINGS, {"title": "QSBS", "impact_kind": "savings", "estimated_impact_cents": 1}]
    assert compute_payload_hash(_FINDINGS, "m") != compute_payload_hash(other, "m")


def test_payload_hash_changes_when_memo_changes() -> None:
    assert compute_payload_hash(_FINDINGS, "v1") != compute_payload_hash(_FINDINGS, "v2")


def test_payload_hash_distinguishes_none_from_empty_memo() -> None:
    assert compute_payload_hash(_FINDINGS, None) != compute_payload_hash(_FINDINGS, "")


def test_content_hash_is_sha256_of_body() -> None:
    body = "## Memo\nConvert $1,200 to Roth."
    assert memo_svc._content_hash(body) == hashlib.sha256(body.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# A minimal async fake session for the version-bump policy (no DB).
# --------------------------------------------------------------------------- #
class _FakeSession:
    """Answers ``scalar`` from a FIFO queue, records ``add``; ``get``/``flush``
    are no-ops. Just enough surface for the memo service's draft policy."""

    def __init__(self, scalar_results: list[Any]) -> None:
        self._scalars = list(scalar_results)
        self.added: list[Any] = []

    async def scalar(self, *_a: Any, **_k: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None

    async def get(self, *_a: Any, **_k: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


def _run_result(memo_text: str | None) -> dict[str, Any]:
    return {
        "client_tax_year_id": str(TY),
        "client_name": "Jordan Alvarez",
        "tax_year": 2026,
        "current_total_tax_cents": 5_000_000,
        "marginal_rate": Decimal("0.32"),
        "findings": _FINDINGS,
        "total_savings_identified_cents": 120_000,
        "memo": memo_text,
        "memo_available": memo_text is not None,
        "has_profile": True,
        "objectives_summary": "minimize current-year tax",
        "trajectory": {"available": False},
        "disclaimer": "Advisor working memo.",
    }


def _signed(version: int) -> Memo:
    return Memo(
        workspace_id=WS, client_tax_year_id=TY, version=version,
        body_md="signed body", status="signed",
    )


def _draft(version: int, run_id: Any = None) -> Memo:
    return Memo(
        workspace_id=WS, client_tax_year_id=TY, version=version,
        body_md="draft body", status="draft", strategist_run_id=run_id,
    )


def _patch_strategist(monkeypatch: pytest.MonkeyPatch, memo_text: str | None) -> None:
    async def _fake(*_a: Any, **_k: Any) -> dict[str, Any]:
        return _run_result(memo_text)

    monkeypatch.setattr(memo_svc, "generate_strategist_memo", _fake)


@pytest.mark.asyncio
async def test_first_run_creates_version_1_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_strategist(monkeypatch, "engine narrative")
    db = _FakeSession([None, None])  # snapshot-id, latest-memo (none yet)
    run = await persist_strategist_run(
        db, workspace_id=WS, actor_uc_uid="advisor-1", tax_year_id=TY, settings=object()
    )
    assert isinstance(run, StrategistRun)
    assert run.payload_hash == compute_payload_hash(_FINDINGS, "engine narrative")
    memos = [o for o in db.added if isinstance(o, Memo)]
    assert len(memos) == 1
    assert memos[0].version == 1
    assert memos[0].status == "draft"
    assert memos[0].body_md == "engine narrative"  # seeded from run
    assert memos[0].strategist_run_id == run.id


@pytest.mark.asyncio
async def test_run_after_signed_opens_superseding_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_strategist(monkeypatch, "fresh narrative")
    db = _FakeSession([None, _signed(3)])  # snapshot-id, latest=signed v3
    run = await persist_strategist_run(
        db, workspace_id=WS, actor_uc_uid="advisor-1", tax_year_id=TY, settings=object()
    )
    new = [o for o in db.added if isinstance(o, Memo)]
    assert len(new) == 1
    assert new[0].version == 4
    assert new[0].status == "draft"
    assert new[0].supersedes_version == 3
    assert new[0].body_md == "fresh narrative"
    assert new[0].strategist_run_id == run.id


@pytest.mark.asyncio
async def test_run_with_open_draft_preserves_body_repoints_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_strategist(monkeypatch, "would-overwrite")
    existing = _draft(2, run_id=uuid4())
    db = _FakeSession([None, existing])  # snapshot-id, latest=draft v2
    run = await persist_strategist_run(
        db, workspace_id=WS, actor_uc_uid="advisor-1", tax_year_id=TY, settings=object()
    )
    # No NEW memo row; the advisor's in-progress body is untouched...
    assert [o for o in db.added if isinstance(o, Memo)] == []
    assert existing.body_md == "draft body"
    # ...but provenance is refreshed to the latest run.
    assert existing.strategist_run_id == run.id


@pytest.mark.asyncio
async def test_save_draft_edits_open_draft_in_place() -> None:
    existing = _draft(1)
    db = _FakeSession([existing])  # latest = open draft
    out = await save_memo_draft(db, workspace_id=WS, tax_year_id=TY, body_md="advisor edit")
    assert out is existing
    assert existing.body_md == "advisor edit"
    assert [o for o in db.added if isinstance(o, Memo)] == []  # no new version


@pytest.mark.asyncio
async def test_save_draft_after_signed_opens_new_superseding_version() -> None:
    db = _FakeSession([_signed(2)])  # latest = signed v2
    out = await save_memo_draft(db, workspace_id=WS, tax_year_id=TY, body_md="new draft")
    assert out.version == 3
    assert out.status == "draft"
    assert out.supersedes_version == 2
    assert out.body_md == "new draft"


@pytest.mark.asyncio
async def test_save_draft_with_no_memo_creates_version_1() -> None:
    db = _FakeSession([None])  # no memo yet
    out = await save_memo_draft(db, workspace_id=WS, tax_year_id=TY, body_md="first")
    assert out.version == 1
    assert out.supersedes_version is None
    assert out.status == "draft"
