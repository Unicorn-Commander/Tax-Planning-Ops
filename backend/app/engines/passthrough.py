"""Multi-entity pass-through aggregation — Phase-3 plumbing, tax year 2025.

A business owner often holds income across several entities at once: a sole
proprietorship (Schedule C), partnership interests (1065 K-1), S-corporation
interests (1120-S K-1) and rental property (Schedule E). Each entity routes its
income to Form 1040 differently and carries different self-employment-tax and
§199A treatment. This engine is PURE ROUTING + AGGREGATION: it sums each
entity's figures into the three buckets a Form 1040 needs, and builds the
per-business QBI input list, so the existing single-business engines
(`se_tax.py`, `qbi.py`, `form1040.py`) can be driven from a real multi-entity
owner. It intentionally holds NO tax-rate or threshold constants.

Routing rules implemented:
  * Schedule C net profit: SE-taxable, QBI-eligible (non-SSTB unless flagged),
    flows to Schedule 1.
  * Partnership K-1 box 1 ordinary income: SE-taxable for a GENERAL partner
    only (a limited partner's share is not SE income); QBI-eligible; flows to
    Schedule 1. Guaranteed payments to a general partner are SE income and flow
    to Schedule 1 but are NOT QBI.
  * S-corp K-1 box 1 ordinary income: NOT SE-taxable (the S-corp advantage),
    QBI-eligible; flows to Schedule 1. The shareholder's S-corp W-2 wages feed
    the QBI wage limit but are payroll, not pass-through income.
  * Schedule E rental: flows to Schedule 1; NOT SE income; QBI only if it rises
    to a trade/business (default off).

Scope / simplifications (always surfaced in `assumptions`, never silent):
  * Passive-loss and at-risk limitations (§469 / §465) are NOT applied; rental
    and K-1 losses pass through at face value.
  * Basis limitations on K-1 losses are NOT applied.
  * Rental QBI defaults off unless an entity is flagged as a trade/business.
  * Guaranteed payments are assumed to be made to a general partner (SE income).

All money is integer cents.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScheduleCEntity(BaseModel):
    name: str = ""
    net_profit_cents: int  # may be negative (a loss)
    is_sstb: bool = False
    w2_wages_paid_cents: int = 0  # W-2 wages the business paid (QBI wage limit)
    ubia_cents: int = 0  # unadjusted basis of qualified property


class PartnershipK1Entity(BaseModel):
    name: str = ""
    ordinary_income_cents: int  # 1065 K-1 box 1; may be negative
    is_general_partner: bool = True  # general → SE income; limited → not
    is_sstb: bool = False
    w2_wages_paid_cents: int = 0
    ubia_cents: int = 0
    guaranteed_payments_cents: int = 0  # SE income, NOT QBI


class SCorpK1Entity(BaseModel):
    name: str = ""
    ordinary_income_cents: int  # 1120-S K-1 box 1; never SE income
    is_sstb: bool = False
    w2_wages_paid_cents: int = 0  # business-level W-2 wages (QBI wage limit)
    ubia_cents: int = 0
    shareholder_w2_wages_cents: int = 0  # the owner's own S-corp salary


class ScheduleERental(BaseModel):
    name: str = ""
    net_rental_cents: int  # may be negative (a loss)
    is_qbi: bool = False  # only if it rises to a trade/business (§199A)


class PassthroughInput(BaseModel):
    schedule_c: list[ScheduleCEntity] = Field(default_factory=list)
    partnerships: list[PartnershipK1Entity] = Field(default_factory=list)
    s_corps: list[SCorpK1Entity] = Field(default_factory=list)
    rentals: list[ScheduleERental] = Field(default_factory=list)


class QBIComponent(BaseModel):
    """One QBI-eligible business, shaped to feed `qbi.py` QBIInput."""

    source: str  # entity kind, e.g. "schedule_c", for advisor traceability
    name: str
    qbi_cents: int
    w2_wages_cents: int
    ubia_cents: int
    is_sstb: bool


class PassthroughResult(BaseModel):
    total_se_earnings_base_cents: int  # → se_tax SETaxInput.net_self_employment_profit_cents
    total_schedule_1_income_cents: int  # → Form1040Inputs.schedule_1_income_cents
    qbi_components: list[QBIComponent]  # one per QBI-eligible entity, → qbi.py
    total_qualified_business_income_cents: int  # convenience sum across entities
    assumptions: list[str] = Field(default_factory=list)


def aggregate_passthrough(inputs: PassthroughInput) -> PassthroughResult:
    se_base = 0
    schedule_1 = 0
    qbi_components: list[QBIComponent] = []
    assumptions: list[str] = []

    for entity in inputs.schedule_c:
        # Schedule C: SE-taxable, QBI-eligible, flows to Schedule 1.
        se_base += entity.net_profit_cents
        schedule_1 += entity.net_profit_cents
        qbi_components.append(
            QBIComponent(
                source="schedule_c",
                name=entity.name,
                qbi_cents=entity.net_profit_cents,
                w2_wages_cents=entity.w2_wages_paid_cents,
                ubia_cents=entity.ubia_cents,
                is_sstb=entity.is_sstb,
            )
        )

    for partner in inputs.partnerships:
        # K-1 box 1 always flows to Schedule 1 and is QBI; SE only if general.
        schedule_1 += partner.ordinary_income_cents
        if partner.is_general_partner:
            se_base += partner.ordinary_income_cents
        qbi_components.append(
            QBIComponent(
                source="partnership_k1",
                name=partner.name,
                qbi_cents=partner.ordinary_income_cents,
                w2_wages_cents=partner.w2_wages_paid_cents,
                ubia_cents=partner.ubia_cents,
                is_sstb=partner.is_sstb,
            )
        )
        if partner.guaranteed_payments_cents:
            # Guaranteed payments: SE income + Schedule 1, but NOT QBI.
            se_base += partner.guaranteed_payments_cents
            schedule_1 += partner.guaranteed_payments_cents
            assumptions.append(
                f"guaranteed_payments_treated_as_se_income: {partner.guaranteed_payments_cents}c "
                f"for '{partner.name or 'partnership'}' added to SE earnings and Schedule 1 but "
                "excluded from QBI (assumes payment to a general partner)."
            )

    for corp in inputs.s_corps:
        # S-corp K-1 box 1: never SE income, QBI-eligible, flows to Schedule 1.
        schedule_1 += corp.ordinary_income_cents
        qbi_components.append(
            QBIComponent(
                source="s_corp_k1",
                name=corp.name,
                qbi_cents=corp.ordinary_income_cents,
                w2_wages_cents=corp.w2_wages_paid_cents,
                ubia_cents=corp.ubia_cents,
                is_sstb=corp.is_sstb,
            )
        )

    for rental in inputs.rentals:
        # Schedule E rental: Schedule 1 only; never SE; QBI only if flagged.
        schedule_1 += rental.net_rental_cents
        assumptions.append(
            f"passive_loss_limits_ignored: rental '{rental.name or 'rental'}' net "
            f"{rental.net_rental_cents}c flowed to Schedule 1 at face value; §469 passive-activity "
            "and §465 at-risk limitations are out of scope."
        )
        if rental.is_qbi:
            qbi_components.append(
                QBIComponent(
                    source="schedule_e_rental",
                    name=rental.name,
                    qbi_cents=rental.net_rental_cents,
                    w2_wages_cents=0,
                    ubia_cents=0,
                    is_sstb=False,
                )
            )
        else:
            assumptions.append(
                f"rental_qbi_default_off: rental '{rental.name or 'rental'}' excluded from QBI; "
                "set is_qbi when the activity rises to a §199A trade/business."
            )

    total_qbi = sum(component.qbi_cents for component in qbi_components)

    return PassthroughResult(
        total_se_earnings_base_cents=se_base,
        total_schedule_1_income_cents=schedule_1,
        qbi_components=qbi_components,
        total_qualified_business_income_cents=total_qbi,
        assumptions=assumptions,
    )
