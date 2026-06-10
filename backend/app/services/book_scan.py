from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.tax_year import ClientTaxYear, TaxSituationSnapshot


async def scan_book(db: AsyncSession, workspace_id: UUID, limit: int = 25) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Client, ClientTaxYear, TaxSituationSnapshot)
        .join(ClientTaxYear, ClientTaxYear.client_id == Client.id)
        .join(TaxSituationSnapshot, TaxSituationSnapshot.client_tax_year_id == ClientTaxYear.id)
        .where(Client.workspace_id == workspace_id)
        .order_by(TaxSituationSnapshot.total_tax_cents.desc())
        .limit(limit)
    )
    rows = []
    for client, tax_year, snapshot in result.all():
        rows.append(
            {
                "client_id": str(client.id),
                "client_name": client.display_name,
                "client_tax_year_id": str(tax_year.id),
                "tax_year": tax_year.tax_year,
                "total_tax_cents": snapshot.total_tax_cents,
                "effective_rate": str(snapshot.effective_rate),
                "opportunity_score_cents": snapshot.total_tax_cents,
            }
        )
    return rows
