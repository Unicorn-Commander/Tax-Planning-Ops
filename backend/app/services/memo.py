"""Memo persistence + sign/seal (spec §9.1).

Persists each AI-strategist run as an immutable ``StrategistRun`` and maintains a
versioned advisor ``Memo`` on top of it. A run seeds (or refreshes) a working
draft; the advisor edits the draft body; signing seals that version via the
append-only audit hash-chain (``append_audit_event``) and snapshots the body's
``content_hash`` so the seal is independently verifiable. Re-running after a
signature opens a fresh draft that supersedes the last signed version, which is
what lets the UI redline new narrative + numbers against the sealed prior memo.

No dollar figure is ever computed here — every number originates in the engine
via ``generate_strategist_memo``; this module only stores and narrates.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.memo import Memo, StrategistRun
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot
from app.services.audit import append_audit_event
from app.services.strategist import generate_strategist_memo


def compute_payload_hash(findings: list[dict[str, Any]], memo: str | None) -> str:
    """sha256 over a canonical JSON of the engine's findings + the authored memo.

    Matches ``audit.compute_audit_hash``'s canonicalization (sorted keys, tight
    separators, ``default=str``) so the value is stable and the hash only moves
    when the engine output or the narration actually changes — that identity is
    the basis for the redline and for "did the re-run differ" checks."""
    canonical = json.dumps(
        {"findings": findings, "memo": memo},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _content_hash(body_md: str) -> str:
    return hashlib.sha256(body_md.encode()).hexdigest()


async def _latest_memo(db: AsyncSession, tax_year_id: UUID) -> Memo | None:
    memo: Memo | None = await db.scalar(
        select(Memo)
        .where(Memo.client_tax_year_id == tax_year_id)
        .order_by(Memo.version.desc())
    )
    return memo


async def _latest_snapshot_id(db: AsyncSession, tax_year_id: UUID) -> UUID | None:
    snapshot_id: UUID | None = await db.scalar(
        select(TaxSituationSnapshot.id)
        .where(TaxSituationSnapshot.client_tax_year_id == tax_year_id)
        .order_by(TaxSituationSnapshot.created_at.desc())
    )
    return snapshot_id


async def persist_strategist_run(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    tax_year_id: UUID,
    settings: Any,
) -> StrategistRun:
    """Run the strategist, persist the immutable run, and ensure a working draft.

    Draft policy:
      * no memo yet            -> create version 1 draft from the run's memo_text;
      * latest memo is signed  -> open a new draft (last_version + 1) seeded from
                                  the run, ``supersedes_version`` = that signed one;
      * latest memo is a draft -> leave its body untouched (the advisor may be
                                  mid-edit) but re-point it at this newer run.
    """
    result = await generate_strategist_memo(
        db, workspace_id=workspace_id, tax_year_id=tax_year_id, settings=settings
    )

    run = StrategistRun(
        workspace_id=workspace_id,
        client_tax_year_id=tax_year_id,
        snapshot_id=await _latest_snapshot_id(db, tax_year_id),
        findings=result["findings"],
        memo_text=result["memo"],
        current_total_tax_cents=result["current_total_tax_cents"],
        total_savings_identified_cents=result["total_savings_identified_cents"],
        marginal_rate=result["marginal_rate"],
        objectives_summary=result["objectives_summary"],
        trajectory=result["trajectory"],
        disclaimer=result["disclaimer"],
        payload_hash=compute_payload_hash(result["findings"], result["memo"]),
        actor_uc_uid=actor_uc_uid,
    )
    db.add(run)
    await db.flush()

    latest = await _latest_memo(db, tax_year_id)
    if latest is None:
        db.add(
            Memo(
                workspace_id=workspace_id,
                client_tax_year_id=tax_year_id,
                strategist_run_id=run.id,
                version=1,
                body_md=run.memo_text or "",
                status="draft",
            )
        )
    elif latest.status == "signed":
        db.add(
            Memo(
                workspace_id=workspace_id,
                client_tax_year_id=tax_year_id,
                strategist_run_id=run.id,
                version=latest.version + 1,
                body_md=run.memo_text or "",
                status="draft",
                supersedes_version=latest.version,
            )
        )
    else:
        # Mid-edit draft: keep the advisor's body, just refresh provenance.
        latest.strategist_run_id = run.id
    await db.flush()
    return run


async def get_memo_state(db: AsyncSession, *, tax_year_id: UUID) -> dict[str, Any]:
    latest = await _latest_memo(db, tax_year_id)
    versions = list(
        await db.scalars(
            select(Memo)
            .where(Memo.client_tax_year_id == tax_year_id)
            .order_by(Memo.version.desc())
        )
    )
    run: StrategistRun | None = None
    if latest is not None and latest.strategist_run_id is not None:
        run = await db.get(StrategistRun, latest.strategist_run_id)
    return {"latest_memo": latest, "versions": versions, "latest_run": run}


async def save_memo_draft(
    db: AsyncSession, *, workspace_id: UUID, tax_year_id: UUID, body_md: str
) -> Memo:
    """Persist an advisor edit. Edits the open draft in place; if the latest
    version is already signed (or none exists), opens a new draft seeded from the
    submitted body that supersedes the last signed version."""
    latest = await _latest_memo(db, tax_year_id)
    if latest is not None and latest.status == "draft":
        latest.body_md = body_md
        await db.flush()
        # Reload server-side onupdate columns (updated_at) before the row is
        # serialized — accessing an expired column during model_validate would
        # otherwise lazy-load outside the async greenlet.
        await db.refresh(latest)
        return latest

    memo = Memo(
        workspace_id=workspace_id,
        client_tax_year_id=tax_year_id,
        strategist_run_id=latest.strategist_run_id if latest else None,
        version=(latest.version + 1) if latest else 1,
        body_md=body_md,
        status="draft",
        supersedes_version=latest.version if latest else None,
    )
    db.add(memo)
    await db.flush()
    await db.refresh(memo)
    return memo


async def sign_memo(
    db: AsyncSession, *, workspace_id: UUID, actor_uc_uid: str, memo_id: UUID
) -> Memo:
    """Seal a draft: snapshot its content hash, append a ``memo.signed`` event to
    the audit hash-chain, and flip the row to 'signed' with the seal reference."""
    memo = await db.get(Memo, memo_id)
    if memo is None:
        raise LookupError("memo not found")
    if memo.status != "draft":
        raise ValueError("only a draft memo can be signed")

    content_hash = _content_hash(memo.body_md)
    event = await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="memo.signed",
        aggregate_type="memo",
        aggregate_id=memo.id,
        payload={
            "version": memo.version,
            "content_hash": content_hash,
            "client_tax_year_id": str(memo.client_tax_year_id),
        },
    )
    memo.status = "signed"
    memo.signed_by = actor_uc_uid
    memo.signed_at = datetime.now(UTC)
    memo.content_hash = content_hash
    memo.audit_event_id = event.id
    await db.flush()
    await db.refresh(memo)
    return memo


async def list_pending_memos(db: AsyncSession, *, workspace_id: UUID) -> list[dict[str, Any]]:
    """Every draft memo in the workspace, newest first, joined to its client for
    the sign-off queue. RLS already scopes to the workspace."""
    rows = await db.execute(
        select(
            Memo,
            Client.display_name,
            ClientTaxYear.tax_year,
            StrategistRun.total_savings_identified_cents,
        )
        .join(ClientTaxYear, Memo.client_tax_year_id == ClientTaxYear.id)
        .join(Client, ClientTaxYear.client_id == Client.id)
        .join(StrategistRun, Memo.strategist_run_id == StrategistRun.id, isouter=True)
        .where(Memo.status == "draft")
        .order_by(Memo.created_at.desc())
    )
    pending: list[dict[str, Any]] = []
    for memo, client_name, tax_year, savings_cents in rows.all():
        pending.append(
            {
                "memo_id": memo.id,
                "client_tax_year_id": memo.client_tax_year_id,
                "client_name": client_name,
                "tax_year": tax_year,
                "version": memo.version,
                "created_at": memo.created_at,
                "total_savings_identified_cents": savings_cents,
            }
        )
    return pending


async def redline(db: AsyncSession, *, memo_id: UUID) -> dict[str, Any]:
    """The given memo (new) vs the prior signed version it supersedes (base).

    Returns both bodies and both runs' findings; the base side is None when the
    memo supersedes nothing (e.g. the first-ever version)."""
    memo = await db.get(Memo, memo_id)
    if memo is None:
        raise LookupError("memo not found")

    new_findings: list[dict[str, Any]] = []
    if memo.strategist_run_id is not None:
        new_run = await db.get(StrategistRun, memo.strategist_run_id)
        if new_run is not None:
            new_findings = new_run.findings

    base: Memo | None = None
    if memo.supersedes_version is not None:
        base = await db.scalar(
            select(Memo).where(
                Memo.client_tax_year_id == memo.client_tax_year_id,
                Memo.version == memo.supersedes_version,
            )
        )

    base_body: str | None = None
    base_findings: list[dict[str, Any]] | None = None
    if base is not None:
        base_body = base.body_md
        if base.strategist_run_id is not None:
            base_run = await db.get(StrategistRun, base.strategist_run_id)
            base_findings = base_run.findings if base_run is not None else []
        else:
            base_findings = []

    return {
        "base_version": base.version if base is not None else None,
        "base_body": base_body,
        "new_version": memo.version,
        "new_body": memo.body_md,
        "new_findings": new_findings,
        "base_findings": base_findings,
    }
