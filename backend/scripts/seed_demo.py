"""Seed lifelike demo data into a running (standalone) backend so every screen
looks alive. Idempotent-enough for a fresh DB. Usage:

  python scripts/seed_demo.py --base-url http://127.0.0.1:8010 --token dev

The demo dataset itself lives in ``app.services.demo_seed`` (the single source
of truth, also used by the in-app POST /demo/load). This script just drives the
same content over HTTP for standalone seeding of a running backend.
"""

from __future__ import annotations

import argparse
import io
import sys

import httpx

from app.services.demo_seed import (
    CLIENTS,
    DEMO_BASE_TAX_YEAR,
    DEMO_PLAN_TAX_YEAR,
    STRATEGIES,
)

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8010")
    p.add_argument("--token", default="dev")
    a = p.parse_args()
    api = httpx.Client(base_url=f"{a.base_url}/api/v1",
                       headers={"Authorization": f"Bearer {a.token}"}, timeout=30.0)

    def post(path, **kw):
        r = api.post(path, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    # branding
    api.put("/admin/branding", json={"firm_name": "Northstar Tax Advisory", "primary_color": "#4f46e5"})

    # strategy library
    strat_ids = []
    for spec in STRATEGIES:
        s = api.put("/admin/strategy-library", json={
            "name": spec["name"], "category": spec["category"],
            "description": spec["description"], "client_facing_copy": spec["client_facing_copy"],
            "savings_method": "amount_x_effective_rate", "is_active": True,
        }).json()
        strat_ids.append(s["id"])
    print(f"seeded {len(strat_ids)} strategies")

    for idx, spec in enumerate(CLIENTS):
        name, status, state = spec["name"], spec["filing_status"], spec["state"]
        fields, make_plan = spec["fields"], spec["make_plan"]
        client = post("/clients", json={"display_name": name, "filing_status_default": status,
                                        "primary_state": state})
        cid = client["id"]
        ty = post("/client-tax-years", json={"client_id": cid, "tax_year": DEMO_BASE_TAX_YEAR,
                                             "role": "base", "filing_status": status})
        up = post(f"/client-tax-years/{ty['id']}/documents/form-1040",
                  files={"file": ("1040.pdf", io.BytesIO(PDF), "application/pdf")})
        er = up.get("id")
        existing = {f["field_key"]: f["id"] for f in up.get("fields", [])}
        for key, cents in fields.items():
            if key in existing:
                api.patch(f"/extracted-fields/{existing[key]}", json={"corrected_value_cents": cents})
        post(f"/extracted-returns/{er}/confirm", json={})
        if make_plan:
            plan = post("/plans", json={"base_tax_year_id": ty["id"],
                                        "target_tax_year": DEMO_PLAN_TAX_YEAR})
            pid = plan["client_tax_year_id"]
            for sid in strat_ids[idx % 2: idx % 2 + 2]:
                api.post(f"/plans/{pid}/strategies", json={
                    "strategy_id": sid, "disposition": "recommended",
                    "amount_cents": 2_000_000 + idx * 500_000, "status_flag": "use_next_year"})
            base_tax = max(fields.get("f1040.line25_withholding", 0) + 500_000, 1_000_000)
            api.post(f"/quarterly/{pid}/compute", json={
                "projected_current_year_tax_cents": base_tax,
                "prior_year_tax_cents": base_tax - 200_000,
                "prior_year_agi_cents": sum(v for k, v in fields.items() if "withholding" not in k),
                "annual_withholding_cents": fields.get("f1040.line25_withholding", 0),
                "method": "even"})
        print(f"  client: {name} ({status}) {'+plan' if make_plan else ''}")

    print("\nSEED COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
