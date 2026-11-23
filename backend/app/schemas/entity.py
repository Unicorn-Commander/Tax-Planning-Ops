from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

EntityKind = Literal["schedule_c", "partnership_k1", "s_corp_k1", "schedule_e", "c_corp"]


class BusinessEntityFields(BaseModel):
    """Stored business-entity fields shared by input and output schemas."""

    kind: EntityKind
    name: str = ""
    # net profit / K-1 box-1 ordinary income / net rental / C-corp pre-NOL taxable income
    amount_cents: int = 0
    w2_wages_paid_cents: int = 0  # business W-2 wages (QBI wage limit)
    ubia_cents: int = 0
    guaranteed_payments_cents: int = 0  # partnership only
    shareholder_w2_wages_cents: int = 0  # S-corp / C-corp owner salary
    is_general_partner: bool = True  # partnership only
    is_sstb: bool = False
    is_qbi: bool = False  # rental only — whether it rises to a §199A trade/business
    dividends_cents: int = 0  # C-corp only — distributed to owner (qualified dividends)
    nol_available_cents: int = 0  # C-corp only — NOL carryforward available
    # Net Schedule M-1 book-to-tax adjustment applied to a (book) synced figure
    # to reach corporate taxable income. 0 → book used as-is (flagged estimate).
    book_to_tax_adjustment_cents: int = 0


class BusinessEntityIn(BusinessEntityFields):
    # AO ids are UUIDs: typed so a traversal fragment or foreign slug is a 422
    # before it can be stored or interpolated into an AO URL.
    accounting_ops_workspace_id: UUID | None = None  # link to AO workspace P&L
    accounting_ops_entity_id: UUID | None = None  # scope the pull to one AO entity


class BusinessEntityOut(BusinessEntityFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_tax_year_id: UUID
    accounting_ops_synced_at: datetime | None = None  # set by the AO sync
    # Provenance of the link: set only when AO confirmed the linker's own
    # membership at set-time. None on a legacy/unverified link (the UI shows a
    # re-link prompt instead of "linked", and the pulls refuse it).
    accounting_ops_linked_at: datetime | None = None
    # Output stays lenient (str): legacy rows may hold a pre-fix free-form id;
    # they are treated as unverified (never synced) rather than rejected here.
    accounting_ops_workspace_id: str | None = None
    accounting_ops_entity_id: str | None = None


class BookToTaxAdjustmentIn(BaseModel):
    """Set the net Schedule M-1 book-to-tax adjustment (cents) on a C-corp entity."""

    book_to_tax_adjustment_cents: int = 0
