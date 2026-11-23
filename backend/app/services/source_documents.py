"""Accounting-Ops tax-document sync — the OCR consumer service.

AO owns the document vault + OCR; this pulls the structured extractions for a
client's tax year over federation (the same rail as the P&L sync) and stores them
as a per-year manifest on the ``client_tax_year`` row (``source_documents`` JSONB
+ ``source_documents_synced_at``). The strategist + intake read that manifest; no
OCR runs here.

Link: the client carries ``accounting_ops_workspace_id`` +
``accounting_ops_entity_id`` (its personal entity in AO); the tax year supplies
the year filter. A sync replaces the whole manifest (idempotent).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.accounting_ops import fetch_tax_documents, verify_caller_workspace_access
from app.models.client import Client
from app.models.tax_year import ClientTaxYear
from app.services.audit import append_audit_event


async def _load_year_and_client(
    db: AsyncSession, tax_year_id: UUID
) -> tuple[ClientTaxYear, Client]:
    """Load the tax year + its client (RLS scopes both to the caller's workspace)."""
    cty = await db.get(ClientTaxYear, tax_year_id)
    if cty is None:
        raise LookupError("tax year not found")
    client = await db.get(Client, cty.client_id)
    if client is None:
        raise LookupError("client for tax year not found")
    return cty, client


def _summarize(docs: list[dict[str, Any]]) -> dict[str, int]:
    by_type: dict[str, int] = {}
    for d in docs:
        key = d.get("doc_type") or "other"
        by_type[key] = by_type.get(key, 0) + 1
    return by_type


async def sync_tax_documents_from_accounting_ops(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    tax_year_id: UUID,
    settings: Settings,
) -> dict[str, Any]:
    """Pull the linked client's Accounting-Ops source documents for this tax year
    and store them as the per-year manifest.

    Raises LookupError if the year/client is missing, ValueError if the client
    isn't linked, and the AccountingOps* hierarchy on the AO call (mapped to
    status codes by the route)."""
    cty, client = await _load_year_and_client(db, tax_year_id)
    # A link only counts when it was VERIFIED at set-time (the linker proved
    # membership of that AO workspace with their own bearer). A legacy row with
    # an id but no provenance is treated as NOT linked: never call AO with it.
    if not client.accounting_ops_workspace_id or not client.accounting_ops_linked_at:
        raise ValueError(
            "this client is not linked to an Accounting-Ops workspace "
            "(set accounting_ops_workspace_id / accounting_ops_entity_id first)"
        )

    result = await fetch_tax_documents(
        client.accounting_ops_workspace_id,
        settings,
        entity_id=client.accounting_ops_entity_id,
        tax_year=cty.tax_year,
    )
    docs = [d.model_dump() for d in result.documents]
    previous_count = len(cty.source_documents or [])
    cty.source_documents = docs
    cty.source_documents_synced_at = datetime.now(UTC)
    await db.flush()

    by_type = _summarize(docs)
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="client_tax_year_synced_source_documents",
        aggregate_type="client_tax_year",
        aggregate_id=cty.id,
        payload={
            "accounting_ops_workspace_id": client.accounting_ops_workspace_id,
            "accounting_ops_entity_id": client.accounting_ops_entity_id,
            "tax_year": cty.tax_year,
            "previous_count": previous_count,
            "document_count": len(docs),
            "by_doc_type": by_type,
        },
    )
    return {
        "tax_year_id": str(cty.id),
        "tax_year": cty.tax_year,
        "accounting_ops_workspace_id": client.accounting_ops_workspace_id,
        "accounting_ops_entity_id": client.accounting_ops_entity_id,
        "previous_count": previous_count,
        "document_count": len(docs),
        "by_doc_type": by_type,
        "synced_at": cty.source_documents_synced_at.isoformat(),
    }


async def get_tax_documents(db: AsyncSession, *, tax_year_id: UUID) -> dict[str, Any]:
    """Return the stored per-year source-document manifest (no AO call)."""
    cty, client = await _load_year_and_client(db, tax_year_id)
    synced = cty.source_documents_synced_at
    return {
        "tax_year_id": str(cty.id),
        "tax_year": cty.tax_year,
        "linked": bool(client.accounting_ops_workspace_id),
        "accounting_ops_workspace_id": client.accounting_ops_workspace_id,
        "accounting_ops_entity_id": client.accounting_ops_entity_id,
        "synced_at": synced.isoformat() if synced else None,
        "documents": cty.source_documents or [],
    }


async def set_accounting_ops_link(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_uc_uid: str,
    client_id: UUID,
    accounting_ops_workspace_id: UUID | None,
    accounting_ops_entity_id: UUID | None,
    caller_bearer: str | None,
    settings: Settings,
) -> dict[str, Any]:
    """Link (or, with empty values, unlink) a client to its Accounting-Ops
    document vault (the AO workspace + personal entity).

    A new link is stored ONLY after Accounting-Ops confirms — answering to the
    CALLER's own bearer, never TPO's service token — that the caller can see
    that AO workspace. Otherwise the link would let TPO's trusted M2M token
    (floored to viewer on any AO workspace) read another tenant's tax
    documents through this client (confused deputy). Raises PermissionError
    when the workspace cannot be verified; the caller's bearer is never
    stored."""
    client = await db.get(Client, client_id)
    if client is None:
        raise LookupError("client not found")
    if accounting_ops_workspace_id is not None:
        verified = await verify_caller_workspace_access(
            settings, str(accounting_ops_workspace_id), caller_bearer
        )
        if not verified:
            raise PermissionError("you are not a member of that Accounting-Ops workspace")
    client.accounting_ops_workspace_id = (
        str(accounting_ops_workspace_id) if accounting_ops_workspace_id else None
    )
    client.accounting_ops_entity_id = (
        str(accounting_ops_entity_id) if accounting_ops_entity_id else None
    )
    client.accounting_ops_linked_at = (
        datetime.now(UTC) if accounting_ops_workspace_id else None
    )
    client.accounting_ops_linked_by = actor_uc_uid if accounting_ops_workspace_id else None
    await db.flush()
    await append_audit_event(
        db,
        workspace_id=workspace_id,
        actor_uc_uid=actor_uc_uid,
        event_type="client_linked_accounting_ops",
        aggregate_type="client",
        aggregate_id=client.id,
        payload={
            "accounting_ops_workspace_id": client.accounting_ops_workspace_id,
            "accounting_ops_entity_id": client.accounting_ops_entity_id,
        },
    )
    return {
        "client_id": str(client.id),
        "accounting_ops_workspace_id": client.accounting_ops_workspace_id,
        "accounting_ops_entity_id": client.accounting_ops_entity_id,
    }
