from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

EntityKind = Literal["schedule_c", "partnership_k1", "s_corp_k1", "schedule_e", "c_corp"]


class BusinessEntityIn(BaseModel):
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
    accounting_ops_workspace_id: str | None = None  # link to AO workspace P&L
    accounting_ops_entity_id: str | None = None  # scope the pull to one AO entity
    # Net Schedule M-1 book-to-tax adjustment applied to a (book) synced figure
    # to reach corporate taxable income. 0 → book used as-is (flagged estimate).
    book_to_tax_adjustment_cents: int = 0


class BusinessEntityOut(BusinessEntityIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_tax_year_id: UUID
    accounting_ops_synced_at: datetime | None = None  # set by the AO sync


class BookToTaxAdjustmentIn(BaseModel):
    """Set the net Schedule M-1 book-to-tax adjustment (cents) on a C-corp entity."""

    book_to_tax_adjustment_cents: int = 0
