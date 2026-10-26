"""Opt-in demo data — a dedicated "Sample Firm (demo)" workspace.

Instead of seeding sample clients into a user's REAL workspace (which mixes
demo and real data), the demo is something a user loads on demand into a
separate, recognizable workspace and can reset at will. Real workspaces are
never auto-seeded.

This module owns the single source of truth for the demo dataset (a small,
lifelike book of clients with filed 1040 figures, a strategy library, plan
years, recommended strategies, and quarterly estimates) AND the server-side
seeding routine. It writes through the existing domain services — not raw SQL —
so the tax engine math runs for real (snapshots, ROI, safe-harbor) and every
RLS ``WITH CHECK`` is satisfied. The figures shown in the demo are therefore
engine-computed, not hand-faked.

Both entry points open a session bound to the demo workspace + the caller's
uc_uid (the same pattern ``create_workspace`` uses) so RLS scopes the writes to
the demo tenant.
"""

from __future__ import annotations

import io
from typing import Any, TypedDict
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.core.config import get_settings
from app.db.session import async_session_maker, bind_session_context
from app.models.client import Client
from app.models.membership import WorkspaceMembership
from app.models.strategy import StrategyLibrary
from app.schemas.client import ClientCreate
from app.schemas.extraction import ClientTaxYearCreate, CorrectFieldRequest
from app.schemas.quarterly import ComputeQuarterlyRequest
from app.schemas.strategy import AddClientStrategyRequest, StrategyLibraryIn
from app.services.clients import create_client
from app.services.extraction import (
    confirm_return,
    correct_field,
    create_tax_year,
    upload_return_document,
)
from app.services.plans import create_plan_from_base
from app.services.quarterly import compute_quarterly_for_plan
from app.services.strategies import add_client_strategy, upsert_strategy_library
from app.services.workspaces import create_workspace

# The recognizable name the demo workspace carries; detection of an existing
# demo workspace (idempotency) and the frontend label both key off this string.
DEMO_WORKSPACE_NAME = "Sample Firm (demo)"

# Smallest valid PDF — the demo seeds 1040 figures by hand-keying corrected
# field values (the same path the review screen uses), so the source document
# only needs to satisfy the "%PDF" header check; OCR is irrelevant here.
_DEMO_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

# Tax years the demo plans across: a filed/base year and the year we plan into.
DEMO_BASE_TAX_YEAR = 2025
DEMO_PLAN_TAX_YEAR = 2026


# --- Demo dataset --------------------------------------------------------------
#
# The catalog is plain data so it can be unit-tested without a DB. Every
# strategy ``category`` is drawn from STRATEGY_CATEGORIES; every figure key on a
# client is a canonical 1040 field key the extraction service understands
# (validated by tests against app.services.extraction.CANONICAL_1040_FIELD_KEYS).

STRATEGY_CATEGORIES = frozenset(
    {"retirement", "charitable", "entity", "health", "investment"}
)

STRATEGIES: tuple[dict[str, str], ...] = (
    {
        "name": "Solo 401(k) employer contribution",
        "category": "retirement",
        "description": "Employer profit-sharing into a Solo 401(k) for self-employment income.",
        "client_facing_copy": "Reduce taxable income by contributing to a Solo 401(k).",
    },
    {
        "name": "Backdoor Roth IRA",
        "category": "retirement",
        "description": "Non-deductible IRA + conversion for high earners over the Roth limit.",
        "client_facing_copy": "Build tax-free retirement growth via a Backdoor Roth.",
    },
    {
        "name": "Donor-Advised Fund (bunching)",
        "category": "charitable",
        "description": (
            "Bunch multiple years of giving into one DAF contribution to clear "
            "the standard deduction."
        ),
        "client_facing_copy": "Bunch charitable gifts to maximize the deduction this year.",
    },
    {
        "name": "S-Corp reasonable-compensation split",
        "category": "entity",
        "description": (
            "Elect S-Corp; split owner pay between W-2 and distributions to reduce SE tax."
        ),
        "client_facing_copy": "Lower self-employment tax with an S-Corp election.",
    },
    {
        "name": "HSA maximization",
        "category": "health",
        "description": "Max the family HSA — triple tax advantage.",
        "client_facing_copy": "Contribute the family max to your HSA.",
    },
    {
        "name": "Tax-loss harvesting",
        "category": "investment",
        "description": "Realize losses to offset gains and up to $3,000 ordinary income.",
        "client_facing_copy": "Harvest investment losses to offset gains.",
    },
)


class DemoClientSpec(TypedDict):
    name: str
    filing_status: str
    state: str
    fields: dict[str, int]
    make_plan: bool


# Each client: a display name, default filing status, home state, the filed
# 1040 figures (canonical field key -> whole-cents), and whether to build a
# forward plan (plan year + recommended strategies + quarterly estimates).
CLIENTS: tuple[DemoClientSpec, ...] = (
    {
        "name": "Marcus Webb",
        "filing_status": "single",
        "state": "CA",
        "fields": {
            "f1040.line1z_wages": 18_500_000,
            "f1040.line2b_taxable_interest": 120_000,
            "f1040.line3a_qualified_div": 350_000,
            "f1040.line3b_ordinary_div": 350_000,
            "f1040.line7_capital_gain": 1_200_000,
            "f1040.line25_withholding": 3_600_000,
        },
        "make_plan": True,
    },
    {
        "name": "Priya & Raj Nair",
        "filing_status": "mfj",
        "state": "NY",
        "fields": {
            "f1040.line1z_wages": 42_000_000,
            "f1040.line2b_taxable_interest": 400_000,
            "f1040.line3a_qualified_div": 1_800_000,
            "f1040.line3b_ordinary_div": 1_800_000,
            "f1040.line7_capital_gain": 6_000_000,
            "f1040.line25_withholding": 9_000_000,
        },
        "make_plan": True,
    },
    {
        "name": "Dolores Hartman",
        "filing_status": "hoh",
        "state": "TX",
        "fields": {
            "f1040.line1z_wages": 9_500_000,
            "f1040.line5b_pensions_taxable": 1_200_000,
            "f1040.line25_withholding": 1_500_000,
        },
        "make_plan": False,
    },
    {
        "name": "Tom & Lisa Becker",
        "filing_status": "mfj",
        "state": "IL",
        "fields": {
            "f1040.line1z_wages": 16_000_000,
            "f1040.line8_sch1_income": 9_000_000,
            "f1040.line13_qbi": 1_800_000,
            "f1040.line25_withholding": 2_800_000,
        },
        "make_plan": True,
    },
    {
        "name": "Evelyn Cho",
        "filing_status": "mfj",
        "state": "WA",
        "fields": {
            "f1040.line1z_wages": 31_000_000,
            "f1040.line4b_ira_taxable": 2_000_000,
            "f1040.line6b_ss_taxable": 1_800_000,
            "f1040.line2b_taxable_interest": 600_000,
            "f1040.line25_withholding": 5_200_000,
        },
        "make_plan": True,
    },
    {
        "name": "Jordan Alvarez",
        "filing_status": "single",
        "state": "FL",
        "fields": {
            "f1040.line1z_wages": 12_400_000,
            "f1040.line3a_qualified_div": 220_000,
            "f1040.line3b_ordinary_div": 220_000,
            "f1040.line25_withholding": 1_900_000,
        },
        "make_plan": False,
    },
)


def _demo_pdf_upload() -> UploadFile:
    """A fresh in-memory PDF upload per call (the stream is read once)."""
    return UploadFile(
        file=io.BytesIO(_DEMO_PDF),
        filename="1040.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


async def _find_demo_workspace_id(*, uc_uid: str) -> UUID | None:
    """The id of this user's existing demo workspace, or None.

    Detected by the recognizable membership name under the membership RLS
    (scoped to the caller's uc_uid), so it never sees another user's workspace.
    """
    async with async_session_maker() as session:
        await _bind_uc_uid(session, uc_uid)
        return await session.scalar(
            select(WorkspaceMembership.workspace_id).where(
                WorkspaceMembership.workspace_name == DEMO_WORKSPACE_NAME,
                WorkspaceMembership.deleted_at.is_(None),
            )
        )


async def _bind_uc_uid(session: AsyncSession, uc_uid: str) -> None:
    """Bind only the uc_uid GUC so the membership RLS scopes reads to this user."""
    settings = get_settings()
    await session.execute(
        text("SELECT set_config(:k, :v, true)"),
        {"k": settings.UC_UID_GUC_NAME, "v": uc_uid},
    )


async def _seed_into(session: AsyncSession, *, workspace_id: UUID, uc_uid: str) -> int:
    """Seed the full demo catalog into an (already bound) demo-workspace session.

    Writes through the domain services so the engine computes every snapshot,
    ROI and safe-harbor figure. Returns the number of clients created.
    """
    # 1) Strategy library — workspace-scoped; client strategies reference these.
    strategy_ids: list[UUID] = []
    for order, strategy_spec in enumerate(STRATEGIES):
        strategy = await upsert_strategy_library(
            session,
            workspace_id=workspace_id,
            actor_uc_uid=uc_uid,
            payload=StrategyLibraryIn(
                name=strategy_spec["name"],
                category=strategy_spec["category"],
                description=strategy_spec["description"],
                client_facing_copy=strategy_spec["client_facing_copy"],
                savings_method="amount_x_effective_rate",
                is_active=True,
                sort_order=order,
            ),
        )
        strategy_ids.append(strategy.id)

    # 2) Clients → filed base year → hand-keyed figures → confirm (engine snapshot)
    #    → optional forward plan (plan year + strategies + quarterly).
    for idx, spec in enumerate(CLIENTS):
        client = await create_client(
            session,
            workspace_id,
            ClientCreate(
                display_name=spec["name"],
                filing_status_default=spec["filing_status"],
                primary_state=spec["state"],
            ),
        )
        tax_year = await create_tax_year(
            session,
            workspace_id,
            ClientTaxYearCreate(
                client_id=client.id,
                tax_year=DEMO_BASE_TAX_YEAR,
                role="base",
                filing_status=spec["filing_status"],
            ),
        )
        extracted = await upload_return_document(
            session,
            workspace_id=workspace_id,
            actor_uc_uid=uc_uid,
            client_tax_year_id=tax_year.id,
            upload=_demo_pdf_upload(),
            settings=get_settings(),
        )
        # Hand-key the filed figures onto the pre-created canonical field rows
        # (same path the advisor review screen drives).
        field_by_key = {field.field_key: field for field in extracted.fields}
        for key, cents in spec["fields"].items():
            field = field_by_key.get(key)
            if field is not None:
                await correct_field(
                    session,
                    field_id=field.id,
                    payload=CorrectFieldRequest(corrected_value_cents=cents),
                )
        # Confirm → locks the base year and writes the engine-computed snapshot.
        await confirm_return(
            session,
            workspace_id=workspace_id,
            actor_uc_uid=uc_uid,
            extracted_return_id=extracted.id,
        )

        if not spec["make_plan"]:
            continue

        plan_year, _ = await create_plan_from_base(
            session,
            workspace_id=workspace_id,
            actor_uc_uid=uc_uid,
            base_tax_year_id=tax_year.id,
            target_tax_year=DEMO_PLAN_TAX_YEAR,
        )
        # Two recommended strategies per planned client (rotating through the
        # library so different demo clients showcase different levers).
        for sid in strategy_ids[idx % 2 : idx % 2 + 2]:
            await add_client_strategy(
                session,
                workspace_id=workspace_id,
                actor_uc_uid=uc_uid,
                client_tax_year_id=plan_year.id,
                payload=AddClientStrategyRequest(
                    strategy_id=sid,
                    disposition="recommended",
                    amount_cents=2_000_000 + idx * 500_000,
                    status_flag="use_next_year",
                ),
            )
        # Quarterly estimates for the plan year (engine-computed safe harbor).
        base_tax = max(spec["fields"].get("f1040.line25_withholding", 0) + 500_000, 1_000_000)
        prior_year_agi = sum(
            value for key, value in spec["fields"].items() if "withholding" not in key
        )
        await compute_quarterly_for_plan(
            session,
            workspace_id=workspace_id,
            actor_uc_uid=uc_uid,
            plan_tax_year_id=plan_year.id,
            payload=ComputeQuarterlyRequest(
                projected_current_year_tax_cents=base_tax,
                prior_year_tax_cents=base_tax - 200_000,
                prior_year_agi_cents=prior_year_agi,
                annual_withholding_cents=spec["fields"].get("f1040.line25_withholding", 0),
                method="even",
            ),
        )

    return len(CLIENTS)


async def _clear_demo_data(session: AsyncSession) -> None:
    """Delete the demo workspace's seeded data (bound to the demo workspace).

    Deleting the clients cascades to their tax years, documents, extracted
    returns/fields, snapshots, quarterly records and client strategies (all FK
    ``ON DELETE CASCADE``). The strategy library is not client-referenced once
    client strategies are gone, so it is cleared after, ready for a fresh seed.
    RLS scopes every statement to the bound demo workspace.
    """
    await session.execute(delete(Client))
    await session.execute(delete(StrategyLibrary))
    await session.flush()


async def load_demo_workspace(*, uc_uid: str) -> dict[str, Any]:
    """Create (or reuse) the user's "Sample Firm (demo)" workspace and seed it.

    Idempotent-ish: if the user already has a demo workspace (detected by the
    recognizable membership name), it is returned as-is WITHOUT creating a
    duplicate or re-seeding — use :func:`reset_demo_workspace` to refresh it.
    """
    existing_id = await _find_demo_workspace_id(uc_uid=uc_uid)
    if existing_id is not None:
        client_count = await _count_clients(workspace_id=existing_id, uc_uid=uc_uid)
        return {
            "workspace_id": existing_id,
            "name": DEMO_WORKSPACE_NAME,
            "client_count": client_count,
        }

    created = await create_workspace(uc_uid=uc_uid, name=DEMO_WORKSPACE_NAME)
    workspace_id = created["workspace_id"]
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), uc_uid)
        client_count = await _seed_into(session, workspace_id=workspace_id, uc_uid=uc_uid)
        await session.commit()
    return {
        "workspace_id": workspace_id,
        "name": DEMO_WORKSPACE_NAME,
        "client_count": client_count,
    }


async def reset_demo_workspace(*, uc_uid: str) -> dict[str, Any]:
    """Clear the user's demo workspace and re-seed it fresh.

    Raises ``LookupError`` if the user has no demo workspace to reset (the
    caller maps this to a 404). The workspace itself is kept; only its seeded
    data is replaced, so its id and membership are stable.
    """
    workspace_id = await _find_demo_workspace_id(uc_uid=uc_uid)
    if workspace_id is None:
        raise LookupError("no demo workspace to reset")
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), uc_uid)
        await _clear_demo_data(session)
        client_count = await _seed_into(session, workspace_id=workspace_id, uc_uid=uc_uid)
        await session.commit()
    return {
        "workspace_id": workspace_id,
        "name": DEMO_WORKSPACE_NAME,
        "client_count": client_count,
    }


async def _count_clients(*, workspace_id: UUID, uc_uid: str) -> int:
    """Count clients in the (already provisioned) demo workspace, RLS-bound."""
    async with async_session_maker() as session:
        await bind_session_context(session, str(workspace_id), uc_uid)
        rows = await session.scalars(select(Client.id))
        return len(list(rows.all()))
