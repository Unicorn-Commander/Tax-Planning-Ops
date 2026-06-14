"""Streaming strategist run (SSE) — view-layer event stream.

Three slices, all runnable without a live Postgres or a live LLM:

  * ``sse_format`` produces a well-formed ``data: <json>\\n\\n`` frame.
  * ``build_plan_steps`` orders the plan card deterministically (and only lists
    the S-corp optimizer when the client has entities) — pure, no DB.
  * ``stream_strategist_run`` emits the event SEQUENCE in order — ``plan`` first,
    ``done`` last, with ``engine_call`` / ``finding`` / ``memo`` between — when
    driven against a tiny in-memory fake session with the engine/LLM/context
    collaborators monkeypatched to controlled stubs. The figures in the events
    are asserted to ECHO the stubbed engine output (never fabricated by the
    stream), mirroring how the real engines feed it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.services import strategist_stream as ss
from app.services.strategist_stream import (
    STEP_COMPREHENSIVE,
    STEP_GOALS,
    STEP_IRMAA,
    STEP_MEMO,
    STEP_OPPORTUNITY,
    STEP_ROTH,
    STEP_SCORP,
    build_plan_steps,
    sse_format,
    stream_strategist_run,
)

WS = uuid4()
TY = uuid4()
CLIENT_ID = uuid4()


# --------------------------------------------------------------------------- #
# sse_format
# --------------------------------------------------------------------------- #
def test_sse_format_is_a_well_formed_frame() -> None:
    frame = sse_format({"type": "plan", "steps": []})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    # exactly one event terminator, and the payload is valid JSON
    assert frame.count("\n\n") == 1
    payload = frame[len("data: ") : -2]
    assert json.loads(payload) == {"type": "plan", "steps": []}


def test_sse_format_roundtrips_nested_event() -> None:
    event = {"type": "finding", "finding": {"title": "Roth", "estimated_impact_cents": 120_000}}
    assert json.loads(sse_format(event)[len("data: ") : -2]) == event


# --------------------------------------------------------------------------- #
# build_plan_steps (pure ordering)
# --------------------------------------------------------------------------- #
def test_plan_steps_order_without_entities_omits_scorp() -> None:
    keys = [s["key"] for s in build_plan_steps(has_entities=False)]
    assert keys == [
        STEP_COMPREHENSIVE, STEP_ROTH, STEP_OPPORTUNITY, STEP_IRMAA, STEP_GOALS, STEP_MEMO,
    ]
    assert all(s["label"] for s in build_plan_steps(has_entities=False))


def test_plan_steps_order_with_entities_includes_scorp_after_roth() -> None:
    keys = [s["key"] for s in build_plan_steps(has_entities=True)]
    assert keys == [
        STEP_COMPREHENSIVE, STEP_ROTH, STEP_SCORP,
        STEP_OPPORTUNITY, STEP_IRMAA, STEP_GOALS, STEP_MEMO,
    ]
    # S-corp slots immediately after Roth and before the opportunity scan.
    assert keys.index(STEP_SCORP) == keys.index(STEP_ROTH) + 1
    assert keys.index(STEP_SCORP) < keys.index(STEP_OPPORTUNITY)


# --------------------------------------------------------------------------- #
# stream_strategist_run — driven with monkeypatched collaborators (no DB/LLM)
# --------------------------------------------------------------------------- #

# Controlled engine figures the stubs return; the stream must surface THESE.
ROTH_TAX_COST = 480_000
OPP_SAVINGS = 250_000
TOTAL_TAX = 5_000_000


class _FakeSession:
    """Minimal async session: ``get`` returns a tax-year then a client (FIFO);
    ``scalar`` (the latest-snapshot lookup) returns one snapshot. Only the calls
    ``stream_strategist_run`` makes before everything else is monkeypatched."""

    def __init__(self, get_results: list[Any], scalar_results: list[Any]) -> None:
        self._gets = list(get_results)
        self._scalars = list(scalar_results)

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    async def scalar(self, *_a: Any, **_k: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None


def _tax_year() -> SimpleNamespace:
    return SimpleNamespace(
        id=TY, client_id=CLIENT_ID, tax_year=2026, filing_status="mfj", role="planning",
    )


def _client() -> SimpleNamespace:
    return SimpleNamespace(display_name="Jordan Alvarez", primary_state="CA")


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        inputs={},  # Form1040Inputs needs only filing_status, supplied by the service
        total_income_cents=40_000_000, agi_cents=38_000_000,
        taxable_income_cents=35_000_000, total_tax_cents=TOTAL_TAX,
        marginal_rate=Decimal("0.32"),
    )


def _comp() -> SimpleNamespace:
    federal = SimpleNamespace(
        agi_cents=38_000_000, taxable_income_cents=35_000_000, marginal_rate=Decimal("0.32"),
    )
    return SimpleNamespace(
        total_tax_cents=TOTAL_TAX, federal=federal, se_tax_cents=0, qbi=None, amt=None,
        amt_cents=0,
    )


@pytest.fixture()
def _patch_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every engine/LLM/context call ``stream_strategist_run`` makes so the
    test exercises the EVENT FLOW with controlled, engine-shaped figures."""
    # context resolution
    monkeypatch.setattr(ss, "_latest_snapshot", _afake(_snapshot()))
    monkeypatch.setattr(ss, "get_profile", _afake(None))
    monkeypatch.setattr(ss, "resolve_bracket_set", _afake(object()))
    monkeypatch.setattr(ss, "to_engine_config", lambda _bs: SimpleNamespace(
        standard_deduction_cents=3_220_000,
    ))
    monkeypatch.setattr(ss, "Form1040Inputs", lambda **kw: SimpleNamespace(
        qualified_dividends_cents=0, capital_gain_loss_cents=0, schedule_1_income_cents=0,
        itemized_deduction_cents=1_000_000, ira_taxable_cents=0,
        model_copy=lambda update=None: SimpleNamespace(),
    ))
    # entities: a single S-corp so the S-corp branch runs
    scorp = SimpleNamespace(
        kind="s_corp_k1", amount_cents=20_000_000, shareholder_w2_wages_cents=8_000_000,
        name="Acme S-corp",
    )
    monkeypatch.setattr(ss, "list_entities", _afake([scorp]))
    monkeypatch.setattr(ss, "business_for_comprehensive", lambda _e: (0, 0, []))
    monkeypatch.setattr(ss, "aggregate_for_comprehensive", lambda _e: SimpleNamespace(
        corporate_tax_cents=0,
    ))
    # engines (ComprehensiveInput is stubbed too: the real model would validate
    # the fake Form1040Inputs; the service only passes the object straight to the
    # stubbed calculate_comprehensive, so a sentinel is fine)
    monkeypatch.setattr(ss, "ComprehensiveInput", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(ss, "calculate_comprehensive", lambda *a, **k: _comp())
    monkeypatch.setattr(ss, "optimize_roth_conversion", lambda *a, **k: SimpleNamespace(
        recommended_conversion_cents=1_500_000, tax_cost_cents=ROTH_TAX_COST,
        effective_rate_on_conversion=Decimal("0.32"), bracket_ceiling_cents=39_000_000,
        irmaa_warning=None,
    ))
    monkeypatch.setattr(ss, "optimize_scorp_salary", lambda *a, **k: SimpleNamespace(
        savings_vs_all_salary_cents=300_000, optimal_salary_cents=12_000_000,
        qbi_deduction_at_optimal_cents=4_000_000,
    ))
    monkeypatch.setattr(ss, "find_opportunities", lambda *a, **k: [SimpleNamespace(
        name="Max the 401(k)", category="retirement", illustrative_amount_cents=2_300_000,
        estimated_tax_savings_cents=OPP_SAVINGS, marginal_rate_used=Decimal("0.32"),
        citation="IRC §402(g)", eligibility_note="Subject to plan limits.",
    )])
    monkeypatch.setattr(ss, "calculate_irmaa", lambda *a, **k: SimpleNamespace(
        distance_to_next_cliff_cents=None, cliff_cost_annual_cents=0, irmaa_tier=0,
    ))
    monkeypatch.setattr(ss, "get_state_config", lambda *a, **k: None)
    monkeypatch.setattr(ss, "goal_aware_findings", lambda **k: [])
    monkeypatch.setattr(ss, "build_trajectory", _afake({"available": False}))
    # year-config getters return harmless sentinels (engines are stubbed anyway)
    for name in (
        "ss_config_for", "ctc_config_for", "amt_config_for", "se_config_for",
        "qbi_config_for", "scorp_config_for", "irmaa_config_for", "charitable_config_for",
        "corporate_config_for",
    ):
        monkeypatch.setattr(ss, name, lambda *_a, **_k: object())
    # the LLM author — return a fixed memo body (no network)
    monkeypatch.setattr(ss, "_author_memo", _afake("## Memo\nConvert to Roth."))


def _afake(value: Any):  # type: ignore[no-untyped-def]
    async def _f(*_a: Any, **_k: Any) -> Any:
        return value

    return _f


async def _collect(db: Any) -> list[dict[str, Any]]:
    return [
        e
        async for e in stream_strategist_run(
            db, workspace_id=WS, tax_year_id=TY, settings=SimpleNamespace(LLM_GATEWAY_URL="x")
        )
    ]


@pytest.mark.asyncio
async def test_stream_emits_plan_first_done_last(_patch_collaborators: None) -> None:
    db = _FakeSession(get_results=[_tax_year(), _client()], scalar_results=[])
    events = await _collect(db)
    assert events[0]["type"] == "plan"
    assert [s["key"] for s in events[0]["steps"]][0] == STEP_COMPREHENSIVE
    assert events[-1]["type"] == "done"
    types = [e["type"] for e in events]
    assert "engine_call" in types
    assert "finding" in types
    assert "memo" in types


@pytest.mark.asyncio
async def test_stream_engine_calls_are_running_then_done(_patch_collaborators: None) -> None:
    db = _FakeSession(get_results=[_tax_year(), _client()], scalar_results=[])
    events = await _collect(db)
    calls = [e for e in events if e["type"] == "engine_call"]
    # every engine name that starts running also finishes (paired running→done)
    for name in (STEP_COMPREHENSIVE, STEP_ROTH, STEP_SCORP, STEP_OPPORTUNITY, STEP_IRMAA,
                 STEP_GOALS, STEP_MEMO):
        statuses = [c["status"] for c in calls if c["name"] == name]
        assert statuses == ["running", "done"], name
    # done events carry a summary string
    assert all("summary" in c for c in calls if c["status"] == "done")


@pytest.mark.asyncio
async def test_stream_surfaces_real_engine_figures(_patch_collaborators: None) -> None:
    db = _FakeSession(get_results=[_tax_year(), _client()], scalar_results=[])
    events = await _collect(db)
    findings = [e["finding"] for e in events if e["type"] == "finding"]
    # the Roth (cost) + S-corp + opportunity findings each carry the stubbed
    # engine figure verbatim — the stream narrates, it doesn't compute.
    impacts = {f["title"]: f["estimated_impact_cents"] for f in findings}
    assert impacts["Fill the current bracket with a Roth conversion"] == ROTH_TAX_COST
    assert impacts["Max the 401(k)"] == OPP_SAVINGS
    done = events[-1]
    assert done["current_total_tax_cents"] == TOTAL_TAX
    # only `savings`-kind findings sum into total_savings_identified_cents
    assert done["total_savings_identified_cents"] == sum(
        f["estimated_impact_cents"] for f in findings if f["impact_kind"] == "savings"
    )


@pytest.mark.asyncio
async def test_stream_memo_arrives_whole_not_token_streamed(_patch_collaborators: None) -> None:
    # The LLM client is non-streaming, so the memo is one `memo` event (no
    # `memo_delta`/`memo_done` token frames). Lock that contract in.
    db = _FakeSession(get_results=[_tax_year(), _client()], scalar_results=[])
    events = await _collect(db)
    types = [e["type"] for e in events]
    assert types.count("memo") == 1
    assert "memo_delta" not in types and "memo_done" not in types
    memo = next(e for e in events if e["type"] == "memo")
    assert memo["text"] == "## Memo\nConvert to Roth."


@pytest.mark.asyncio
async def test_stream_raises_lookup_error_before_any_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No tax year → LookupError must fire on the FIRST pull, before a `plan`
    # event is produced (this is what lets the endpoint return a 404).
    db = _FakeSession(get_results=[None], scalar_results=[])
    agen = stream_strategist_run(
        db, workspace_id=WS, tax_year_id=TY, settings=SimpleNamespace(LLM_GATEWAY_URL="x")
    )
    with pytest.raises(LookupError):
        await agen.__anext__()
