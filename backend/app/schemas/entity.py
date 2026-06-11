from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

EntityKind = Literal["schedule_c", "partnership_k1", "s_corp_k1", "schedule_e"]


class BusinessEntityIn(BaseModel):
    kind: EntityKind
    name: str = ""
    amount_cents: int = 0  # net profit / K-1 box-1 ordinary income / net rental
    w2_wages_paid_cents: int = 0  # business W-2 wages (QBI wage limit)
    ubia_cents: int = 0
    guaranteed_payments_cents: int = 0  # partnership only
    shareholder_w2_wages_cents: int = 0  # S-corp owner salary
    is_general_partner: bool = True  # partnership only
    is_sstb: bool = False
    is_qbi: bool = False  # rental only — whether it rises to a §199A trade/business


class BusinessEntityOut(BusinessEntityIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    client_tax_year_id: UUID
