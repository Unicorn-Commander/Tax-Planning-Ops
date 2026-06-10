"""Seed lifelike demo data into a running (standalone) backend so every screen
looks alive. Idempotent-enough for a fresh DB. Usage:

  python scripts/seed_demo.py --base-url http://127.0.0.1:8010 --token dev
"""

from __future__ import annotations

import argparse
import io
import sys

import httpx

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

STRATEGIES = [
    ("Solo 401(k) employer contribution", "retirement",
     "Employer profit-sharing into a Solo 401(k) for self-employment income.",
     "Reduce taxable income by contributing to a Solo 401(k)."),
    ("Backdoor Roth IRA", "retirement",
     "Non-deductible IRA + conversion for high earners over the Roth limit.",
     "Build tax-free retirement growth via a Backdoor Roth."),
    ("Donor-Advised Fund (bunching)", "charitable",
     "Bunch multiple years of giving into one DAF contribution to clear the standard deduction.",
     "Bunch charitable gifts to maximize the deduction this year."),
    ("S-Corp reasonable-compensation split", "entity",
     "Elect S-Corp; split owner pay between W-2 and distributions to reduce SE tax.",
     "Lower self-employment tax with an S-Corp election."),
    ("HSA maximization", "health",
     "Max the family HSA — triple tax advantage.",
     "Contribute the family max to your HSA."),
    ("Tax-loss harvesting", "investment",
     "Realize losses to offset gains and up to $3,000 ordinary income.",
     "Harvest investment losses to offset gains."),
]

CLIENTS = [
    ("Marcus Webb", "single", "CA", {
        "f1040.line1z_wages": 18_500_000, "f1040.line2b_taxable_interest": 120_000,
        "f1040.line3a_qualified_div": 350_000, "f1040.line3b_ordinary_div": 350_000,
        "f1040.line7_capital_gain": 1_200_000, "f1040.line25_withholding": 3_600_000,
    }, True),
    ("Priya & Raj Nair", "mfj", "NY", {
        "f1040.line1z_wages": 42_000_000, "f1040.line2b_taxable_interest": 400_000,
        "f1040.line3a_qualified_div": 1_800_000, "f1040.line3b_ordinary_div": 1_800_000,
        "f1040.line7_capital_gain": 6_000_000, "f1040.line25_withholding": 9_000_000,
    }, True),
    ("Dolores Hartman", "hoh", "TX", {
        "f1040.line1z_wages": 9_500_000, "f1040.line5b_pensions_taxable": 1_200_000,
        "f1040.line25_withholding": 1_500_000,
    }, False),
    ("Tom & Lisa Becker", "mfj", "IL", {
        "f1040.line1z_wages": 16_000_000, "f1040.line8_sch1_income": 9_000_000,
        "f1040.line13_qbi": 1_800_000, "f1040.line25_withholding": 2_800_000,
    }, True),
    ("Evelyn Cho", "mfj", "WA", {
        "f1040.line1z_wages": 31_000_000, "f1040.line4b_ira_taxable": 2_000_000,
        "f1040.line6b_ss_taxable": 1_800_000, "f1040.line2b_taxable_interest": 600_000,
        "f1040.line25_withholding": 5_200_000,
    }, True),
    ("Jordan Alvarez", "single", "FL", {
        "f1040.line1z_wages": 12_400_000, "f1040.line3a_qualified_div": 220_000,
        "f1040.line3b_ordinary_div": 220_000, "f1040.line25_withholding": 1_900_000,
    }, False),
]


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
    for name, cat, desc, copy in STRATEGIES:
        s = api.put("/admin/strategy-library", json={
            "name": name, "category": cat, "description": desc, "client_facing_copy": copy,
            "savings_method": "amount_x_effective_rate", "is_active": True,
        }).json()
        strat_ids.append(s["id"])
    print(f"seeded {len(strat_ids)} strategies")

    for idx, (name, status, state, fields, make_plan) in enumerate(CLIENTS):
        client = post("/clients", json={"display_name": name, "filing_status_default": status,
                                        "primary_state": state, "status": "active"})
        cid = client["id"]
        ty = post("/client-tax-years", json={"client_id": cid, "tax_year": 2025, "role": "base",
                                             "filing_status": status})
        up = post(f"/client-tax-years/{ty['id']}/documents/form-1040",
                  files={"file": ("1040.pdf", io.BytesIO(PDF), "application/pdf")})
        er = up.get("id")
        existing = {f["field_key"]: f["id"] for f in up.get("fields", [])}
        for key, cents in fields.items():
            if key in existing:
                api.patch(f"/extracted-fields/{existing[key]}", json={"corrected_value_cents": cents})
        post(f"/extracted-returns/{er}/confirm", json={})
        if make_plan:
            plan = post("/plans", json={"base_tax_year_id": ty["id"], "target_tax_year": 2026})
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
