from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.audit import compute_audit_hash

_TS = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _h(prev: str | None, **overrides: object) -> str:
    base = {
        "event_type": "return_confirmed",
        "actor_uc_uid": "user-1",
        "aggregate_type": "extracted_return",
        "aggregate_id": "00000000-0000-0000-0000-0000000000aa",
        "created_at": _TS,
        "payload": {"total_tax_cents": 123},
    }
    base.update(overrides)
    return compute_audit_hash(prev, **base)  # type: ignore[arg-type]


def test_audit_hash_chain_links_and_detects_payload_change() -> None:
    first = _h(None, event_type="uploaded", payload={"blob": "a"})
    second = _h(first)
    assert first != second
    # deterministic
    assert _h(first) == second
    # payload tamper breaks the hash
    assert _h(first, payload={"total_tax_cents": 124}) != second


def test_audit_hash_covers_actor_and_event_metadata() -> None:
    base = _h(None)
    # Changing WHO or WHAT (not just payload) must change the hash — this is the
    # property that makes after-the-fact actor rewriting detectable.
    assert _h(None, actor_uc_uid="attacker") != base
    assert _h(None, event_type="something_else") != base
    assert _h(None, aggregate_id=str(uuid4())) != base
    assert _h(None, created_at=datetime(2026, 1, 1, tzinfo=UTC)) != base
