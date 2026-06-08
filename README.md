# Tax-Planning-Ops

**Sovereign, agent-first tax planning & advisory for CPA firms and financial advisors** — a Unicorn Commander suite module.

> Plans the **business and the owner together, on the firm's own ledger** — not a stale uploaded PDF. The Holistiplan / TaxPlanIQ / Corvee category, rebuilt self-hostable, ledger-integrated, and agentic.

**Status:** Specification (2026-06-08). Repo scaffolded; PRD + coding-agent prompt + research in `docs/`. Build not yet started.
**Project-Ops:** P-00070

## What it does
Upload a client's last-filed Form 1040 -> auto-extract (review/correct) -> **Current vs Next-Year** projection (marginal bracket + effective rate) -> **tax-strategy library + ROI** (amount x effective-rate) -> **quarterly estimated-tax** engine (safe harbor, unpaid roll-forward) -> **client tax-plan PDF**. Admin: strategy library + editable brackets per year. Tax-year-per-client (2025 base -> 2026 plan w/ 4 quarters -> 2027).

Distinct from tax *prep* (Drake/Lacerte) and from **Accounting-Ops** (bookkeeping + tax *compliance*), which it federates for tax data.

## The wedge (why it wins — not "a better UI")
1. **Multi-entity / business-owner** — incumbents stop at the 1040; we ingest 1120-S/1065/Sch C and roll multi-entity K-1s + QBI into one household projection.
2. **Integrated = accurate** — ledger-fed, downstream-aware math (IRMAA/NIIT/AMT/SALT), collapsing the firm's two-tool stack.
3. **Living projections** — re-compute as financials change, with a hash-chained audit trail.
4. **Sovereignty / self-host** — 1040s/SSNs never leave the firm; on-prem OCR (no vendor sees client returns); GLBA / FTC-Safeguards / Pub-4557 as a selling point.
5. **Trust-by-design pricing** — no per-household hikes, no billing lock-in.
6. **Agent-first** — Brigade agents scan the whole book, build scenarios, quantify strategies, draft quarterly estimates (advisor approves).

## Docs
- `docs/PRD.md` — full product requirements (data model, 5 engines, substrate reuse map, phased roadmap).
- `docs/CODING-AGENT-PROMPT.md` — paste-ready build prompt for a coding agent.
- `docs/RESEARCH-FINDINGS.md` — the wedge + the client-portal-vs-Wealth roadmap finding.

## Build posture
Reuses the UC/AO substrate (Keycloak auth/MFA, Garage encrypted storage, Qwen3-VL OCR, PDF, Brigade agents/MCP, schema-per-workspace tenancy). Net-new = the tax-planning engines. Agentic (MCP) and human (GUI) interfaces are co-equal. Sells standalone but federates Accounting-Ops.
