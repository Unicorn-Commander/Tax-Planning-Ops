from __future__ import annotations

import pytest

from app.core.config import Settings
from app.integrations.accounting_ops import get_tax_figures


@pytest.mark.asyncio
async def test_accounting_ops_degrades_to_none_without_endpoint() -> None:
    settings = Settings(ACCOUNTING_OPS_URL="", STANDALONE_MODE=True)
    assert await get_tax_figures("client-1", settings) is None
