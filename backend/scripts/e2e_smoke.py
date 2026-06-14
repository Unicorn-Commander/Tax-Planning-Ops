"""End-to-end smoke of the full advisor loop against a running backend.

create client -> base tax year -> upload 1040 (OCR may be disabled) ->
review/correct -> confirm (Engine 1) -> create plan (Engine 2 snapshots) ->
edit assumptions -> strategy library + attach (Engine 3) -> quarterly
(Engine 4) -> plan PDF payload (Engine 5) -> audit-chain verify -> book scan.

Usage:
  python scripts/e2e_smoke.py --base-url http://127.0.0.1:8400 --token <jwt>

Exits non-zero on the first failed step. Safe to run repeatedly (creates new
client each run).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

import httpx

CHECK = "[ok]"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8400")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    api = httpx.Client(
        base_url=f"{args.base_url}/api/v1",
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=30.0,
    )

    def step(name: str, resp: httpx.Response, expect: int = 200) -> dict:
        body: dict | list | None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        if resp.status_code != expect:
            print(f"[FAIL] {name}: HTTP {resp.status_code} (expected {expect})")
            print(json.dumps(body, indent=2, default=str)[:2000])
            sys.exit(1)
        print(f"{CHECK} {name}")
        return body if isinstance(body, dict) else {"items": body}

    run_tag = int(time.time())

    # 1. Client
    client = step(
        "create client",
        api.post(
            "/clients",
            json={
                "display_name": f"E2E Janet Planner {run_tag}",
                "filing_status_default": "single",
                "notes": "e2e smoke",
            },
        ),
        201,
    )
    client_id = client["id"]

    # 2. Base tax year 2025
    base_year = step(
        "create base tax year 2025",
        api.post(
            "/client-tax-years",
            json={
                "client_id": client_id,
                "tax_year": 2025,
                "role": "base",
                "filing_status": "single",
            },
        ),
        201,
    )
    base_year_id = base_year["id"]

    # 3. Upload a 1040 PDF (tiny valid-enough PDF bytes)
    pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
    upload = step(
        "upload form-1040 document",
        api.post(
            f"/client-tax-years/{base_year_id}/documents/form-1040",
            files={"file": ("janet-2025-1040.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        ),
        201,
    )
    extracted_return_id = upload.get("extracted_return_id") or upload.get("id")

    # 4. Read the extraction, correct core fields
    extraction = step(
        "get extracted return",
        api.get(f"/extracted-returns/{extracted_return_id}"),
    )
    fields = {f["field_key"]: f for f in extraction.get("fields", [])}
    print(f"     extraction status={extraction.get('extraction_status')} fields={len(fields)}")

    corrections = {
        "f1040.line1z_wages": 18500000,  # $185,000
        "f1040.line2b_taxable_interest": 120000,  # $1,200
        "f1040.line3a_qualified_div": 350000,  # $3,500
        "f1040.line3b_ordinary_div": 350000,
        "f1040.line7_capital_gain": 1200000,  # $12,000 LTCG
        "f1040.line11_agi": 20170000,
        "f1040.line24_total_tax": 4000000,
    }
    patched = 0
    for key, cents in corrections.items():
        field = fields.get(key)
        if not field:
            continue
        step(
            f"correct field {key}",
            api.patch(
                f"/extracted-fields/{field['id']}",
                json={"corrected_value_cents": cents},
            ),
        )
        patched += 1
    if patched == 0:
        print("     note: no canonical field rows present to correct (OCR disabled path)")

    # 5. Confirm baseline (runs Engine 1, locks year, audit row)
    confirm = step(
        "confirm return (Engine 1 baseline)",
        api.post(f"/extracted-returns/{extracted_return_id}/confirm", json={}),
    )
    baseline = confirm.get("snapshot") or confirm
    print(
        "     baseline total_tax_cents=%s effective_rate=%s"
        % (baseline.get("total_tax_cents"), baseline.get("effective_rate"))
    )

    # 6. Create the 2026 plan
    plan = step(
        "create 2026 plan (Engine 2 snapshots)",
        api.post(
            "/plans",
            json={"base_tax_year_id": base_year_id, "target_tax_year": 2026},
        ),
        201,
    )
    plan_year_id = plan.get("client_tax_year_id") or plan.get("plan_tax_year_id") or plan.get("id")

    # 7. Edit next-year assumptions: +$50k wages
    assumptions = step(
        "update assumptions (+$50k wages)",
        api.patch(
            f"/plans/{plan_year_id}/assumptions",
            json={"assumptions": {"wages_delta_cents": 5000000}},
        ),
    )
    print(f"     projection keys: {sorted(assumptions.keys())[:8]}")

    # 8. Strategy library entry + attach to plan
    library = step(
        "admin upsert strategy library entry",
        api.put(
            "/admin/strategy-library",
            json={
                "name": f"Solo 401(k) employee deferral {run_tag}",
                "category": "retirement",
                "description": "Max employee deferral against SE/W-2 income.",
                "client_facing_copy": "Contribute to a Solo 401(k) to reduce taxable income.",
                "savings_method": "amount_x_effective_rate",
                "is_active": True,
            },
        ),
    )
    strategy_id = library.get("id")
    attach = step(
        "attach strategy to plan (Engine 3)",
        api.post(
            f"/plans/{plan_year_id}/strategies",
            json={
                "strategy_id": strategy_id,
                "disposition": "recommended",
                "amount_cents": 2000000,
                "status_flag": "use_next_year",
            },
        ),
        201,
    )
    print(
        "     estimated_savings_cents=%s rate=%s"
        % (attach.get("estimated_savings_cents"), attach.get("effective_rate_used"))
    )

    # 9. Quarterly (Engine 4)
    quarterly = step(
        "compute quarterly (Engine 4)",
        api.post(
            f"/quarterly/{plan_year_id}/compute",
            json={
                "projected_current_year_tax_cents": 4400000,
                "prior_year_tax_cents": 4000000,
                "prior_year_agi_cents": 20170000,
                "annual_withholding_cents": 3000000,
                "method": "even",
            },
        ),
    )
    quarters = quarterly.get("quarters", [])
    print(
        "     basis=%s required=%s"
        % (
            quarterly.get("safe_harbor_basis"),
            [q.get("required_payment_cents") for q in quarters],
        )
    )

    # 10. Plan PDF payload (Engine 5)
    pdf_resp = api.post(f"/plans/{plan_year_id}/pdf", json={})
    pdf = step("generate plan PDF (Engine 5)", pdf_resp, pdf_resp.status_code if pdf_resp.status_code in (200, 201) else 201)
    print(
        "     plan_document version=%s key=%s"
        % (pdf.get("version"), (pdf.get("garage_key") or "")[:60])
    )

    # ===== Phase 9 — the additive transaction path (memo/sign, scenario, tasks,
    # realized, journal) + the honest-notes read endpoints, all under real auth. =====

    # 11. Strategist run (persists a run + seeds a draft memo)
    run = step(
        "strategist run (persist)",
        api.post(f"/clients/tax-years/{plan_year_id}/strategist/run", json={}),
    )
    memo_state = run.get("memo_state") or {}
    memo = memo_state.get("latest_memo") or {}
    memo_id = memo.get("id")
    print(
        "     run findings=%s memo v%s status=%s"
        % (len((run.get("run") or {}).get("findings") or []), memo.get("version"), memo.get("status"))
    )

    # 12. Edit the draft body
    step(
        "save memo draft",
        api.put(
            f"/clients/tax-years/{plan_year_id}/memo",
            json={"body_md": f"## Working memo (e2e {run_tag})\nEdited by the smoke."},
        ),
    )

    # 13. Sign & seal -> a real content_hash + a hash-chained audit event
    signed = step("sign memo", api.post(f"/memos/{memo_id}/sign", json={}))
    if not (signed.get("status") == "signed" and signed.get("content_hash") and signed.get("audit_event_id")):
        print(f"[FAIL] sign did not seal: {signed}")
        sys.exit(1)
    print(
        "     signed v%s hash=%s audit=%s"
        % (signed.get("version"), (signed.get("content_hash") or "")[:12], str(signed.get("audit_event_id"))[:8])
    )

    # 14. The signed memo must have left the pending queue
    pending = step("memos pending", api.get("/memos/pending"))
    pend_items = pending.get("items") if isinstance(pending, dict) else pending
    if memo_id in {p.get("memo_id") for p in (pend_items or [])}:
        print("[FAIL] signed memo still in the pending queue")
        sys.exit(1)

    # 15. Scenario recompute — a real engine before/after delta
    scen = step(
        "scenario recompute (-$20k Sch-1 income)",
        api.post(
            f"/agents/clients/tax-years/{plan_year_id}/scenario",
            json={"delta_fields": {"schedule_1_income_cents": -2000000}},
        ),
    )
    print(
        "     tax_delta_cents=%s marginal %s->%s"
        % (scen.get("tax_delta_cents"), scen.get("marginal_rate_base"), scen.get("marginal_rate_scenario"))
    )

    # 16. EMR sweep + Roth optimizer (real engine traces)
    emr = step("EMR sweep", api.post(f"/agents/clients/tax-years/{plan_year_id}/emr-sweep", json={}))
    print(
        "     emr points=%s true_next_dollar=%s"
        % (len(emr.get("points") or []), emr.get("true_next_dollar_rate"))
    )
    step("optimize roth", api.post(f"/agents/clients/tax-years/{plan_year_id}/optimize/roth", json={}))

    # 17. Statutory deadlines + a 5-field implementation contract
    step("statutory deadlines", api.get("/statutory-deadlines", params={"tax_year": 2026}))
    task = step(
        "create task (5-field contract)",
        api.post(
            f"/plans/{plan_year_id}/tasks",
            json={
                "title": "Fund Solo 401(k) employee deferral",
                "owner": "client",
                "amount_cents": 2000000,
                "statutory_key": "solo_401k_employee",
                "client_strategy_id": attach.get("id"),
            },
        ),
        201,
    )
    step("advance task -> in_progress", api.patch(f"/tasks/{task.get('id')}", json={"status": "in_progress"}))
    tasks = step("list tasks", api.get(f"/plans/{plan_year_id}/tasks"))
    print(f"     tasks={len(tasks.get('items') or [])} (with statutory due dates)")

    # 18. Realized reconciliation (planned locked from the strategy) + book rollup
    step(
        "reconcile realized outcome",
        api.post(
            f"/plans/{plan_year_id}/realized",
            json={
                "client_strategy_id": attach.get("id"),
                "realized_tax_year": 2027,
                "realized_savings_cents": 1800000,
                "basis": "next_year_return",
            },
        ),
        201,
    )
    rollup = step("realized rollup", api.get("/agents/realized-rollup"))
    print(
        "     rollup planned=%s realized=%s"
        % (rollup.get("total_planned_cents"), rollup.get("total_realized_cents"))
    )

    # 19. Journal read — the signed + reconciled events, each with a door stamp
    journal = step("journal tail", api.get("/lifecycle/journal", params={"tail": 20}))
    events = journal.get("events") or []
    types = {e.get("event_type") for e in events}
    if "memo.signed" not in types:
        print(f"[FAIL] memo.signed missing from journal tail: {sorted(t for t in types if t)}")
        sys.exit(1)
    doors = {(e.get("payload") or {}).get("door") for e in events}
    print(
        "     journal events=%s doors=%s chain_intact=%s"
        % (len(events), doors, (journal.get("status") or {}).get("chain_intact"))
    )

    # 20. The honest-notes read endpoints
    reg = step("agent registry", api.get("/agents/registry"))
    print(f"     registry agents={len(reg.get('agents') or [])}")
    step("door stats", api.get("/agents/door-stats"))
    mtx = step("clients x strategies matrix", api.get("/agents/matrix"))
    print(f"     matrix rows={len(mtx.get('rows') or [])} grand_total={mtx.get('grand_total_cents')}")
    step("read branding (200 + null ok when unset)", api.get("/admin/branding"))
    step("set advisory fee", api.put(f"/admin/engagements/{client_id}/fee", json={"fee_cents": 350000, "fee_basis": "flat"}))
    step("read advisory fee", api.get(f"/admin/engagements/{client_id}/fee"))

    # 21. Streaming strategist (door 2) — read the SSE event stream to completion
    seen: list[str] = []
    with api.stream(
        "POST", f"/agents/clients/tax-years/{plan_year_id}/strategist/stream", json={}
    ) as sresp:
        if sresp.status_code != 200:
            print(f"[FAIL] strategist stream: HTTP {sresp.status_code}")
            sys.exit(1)
        for line in sresp.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]).get("type"))
                if seen[-1] == "done" or len(seen) > 60:
                    break
    if not ("plan" in seen and "done" in seen):
        print(f"[FAIL] stream missing plan/done: {seen[:12]}")
        sys.exit(1)
    print(f"{CHECK} strategist stream (SSE)\n     event types: {seen[:8]}")

    # 22. Audit chain verify (now also covers memo.signed + outcome.reconciled)
    audit = step("verify audit chain", api.get("/lifecycle/audit/verify"))
    if not (audit.get("valid") or audit.get("ok")):
        print(f"[FAIL] audit chain reported invalid: {audit}")
        sys.exit(1)
    print(f"     audit entries={audit.get('entries') or audit.get('count')}")

    # 12. Book scan
    scan = step("agents scan-book", api.get("/agents/scan-book"))
    ranked = scan.get("clients") or scan.get("items") or []
    print(f"     book scan returned {len(ranked)} ranked clients")

    print("\nE2E SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
