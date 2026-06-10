from __future__ import annotations

from app.services.audit import compute_audit_hash


def test_audit_hash_chain_detects_payload_change() -> None:
    first_payload = {"event": "uploaded", "blob": "a"}
    first_hash = compute_audit_hash(None, first_payload)
    second_payload = {"event": "confirmed", "tax": 123}
    second_hash = compute_audit_hash(first_hash, second_payload)

    assert first_hash != second_hash
    assert compute_audit_hash(first_hash, second_payload) == second_hash
    assert compute_audit_hash(first_hash, {"event": "confirmed", "tax": 124}) != second_hash
