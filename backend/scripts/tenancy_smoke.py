"""Real-DB smoke of multi-workspace tenancy (Phase 10).

Proves, against a running backend + a real Postgres (RLS), that a user can own
several named workspaces and switch between them — and, critically, that a user
CANNOT select a workspace they aren't a member of.

Usage:
  python scripts/tenancy_smoke.py --base-url http://127.0.0.1:8400 \
      --token-a <jwt for user A, home=W1> --w1 <W1 uuid> \
      --token-b <jwt for user B, home=WB>

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8400")
    p.add_argument("--token-a", required=True)
    p.add_argument("--w1", required=True)
    p.add_argument("--token-b", required=True)
    args = p.parse_args()

    base = f"{args.base_url}/api/v1"
    a = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {args.token_a}"}, timeout=30)

    def ok(label: str, cond: bool, extra: str = "") -> None:
        if not cond:
            print(f"[FAIL] {label} {extra}")
            sys.exit(1)
        print(f"[ok] {label}")

    # 1. /me seeds + lists the home workspace W1 (named).
    me = a.get("/me").json()
    ws_ids = {w["workspaceId"] for w in me.get("workspaces", [])}
    ok("/me lists home workspace W1", args.w1 in ws_ids, f"got {ws_ids}")

    # 2. Create a second named workspace.
    created = a.post("/workspaces", json={"name": "Magic Unicorn"})
    ok("create workspace W2", created.status_code == 201, f"HTTP {created.status_code}")
    w2 = created.json()["workspaceId"]

    # 3. /me now lists BOTH.
    ids2 = {w["workspaceId"] for w in a.get("/me").json().get("workspaces", [])}
    ok("/me lists W1 + W2", args.w1 in ids2 and w2 in ids2, f"got {ids2}")

    # 4. List endpoint reflects the membership.
    listed = {w["workspaceId"] for w in a.get("/workspaces").json()}
    ok("GET /workspaces lists W2", w2 in listed, f"got {listed}")

    # 5. Switch to W2 (member) and create a client there — authorized by membership.
    a2 = httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {args.token_a}", "X-Workspace-Id": w2},
        timeout=30,
    )
    c = a2.post(
        "/clients",
        json={"display_name": "MU client", "filing_status_default": "single"},
    )
    ok("member can transact in W2", c.status_code == 201, f"HTTP {c.status_code}")

    # 6. SECURITY: a DIFFERENT user (B) cannot select W2 — they aren't a member.
    b = httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {args.token_b}", "X-Workspace-Id": w2},
        timeout=30,
    )
    denied = b.get("/clients")
    ok("non-member denied W2 (403)", denied.status_code == 403, f"HTTP {denied.status_code}")

    # 7. And B's own /me must NOT see W2.
    b_ids = {w["workspaceId"] for w in b.get("/me").json().get("workspaces", [])}
    ok("W2 not visible to B", w2 not in b_ids, f"got {b_ids}")

    # 8. Rename W1.
    r = a.patch(f"/workspaces/{args.w1}", json={"name": "Personal"})
    ok("rename W1 -> Personal", r.status_code == 200 and r.json()["displayName"] == "Personal")
    renamed = next(w for w in a.get("/me").json()["workspaces"] if w["workspaceId"] == args.w1)
    ok("rename persisted in /me", renamed["displayName"] == "Personal")

    print("\nTENANCY SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
