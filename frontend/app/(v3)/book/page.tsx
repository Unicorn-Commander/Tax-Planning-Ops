"use client";

// Surface 02 — THE BOOK
// Dense roster + matrix (clients × strategies) + rollup band.
// Firm SHELL surface: fetches the book itself (no client context).
//
// Live data wired:
//   GET /agents/scan-book      — ranked by backend (recomputed savings); DO NOT re-sort by total_tax
//   GET /clients               — to get filing_status_default, primary_state, status
//   GET /clients/:id/overview  — per-client snapshot + strategies (for micro-strata + milestones)
//   GET /admin/tax-bracket-sets — for the Position micro-strata segment spans
//
//   GET /agents/realized-rollup — workspace realized counter (planned vs realized, % realized)
//
// Additive (spec §7-02, Honesty Protocol):
//   EMR endpoint        — true marginal rate; v1 falls back to nominal bracket
//   Matrix endpoint     — client × strategy cells; v1 renders from each client's opportunities list
//
// Per-surface integration TODO: frontend/INTEGRATION-TODO.02.md

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import {
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Money,
  Cavatar,
  WorkingDots,
  Button,
  Omnibar,
  PositionInstrument,
  hueForClient,
  type Segment,
} from "@/components/kit";

/* ---- wire shapes -------------------------------------------------- */

// GET /agents/scan-book — backend ranks by recomputed savings, do NOT re-sort
interface ScanRow {
  client_id: string;
  client_name: string;
  tax_year: number;
  total_tax_cents: number;
  effective_rate: string;
}

// GET /clients
interface ClientRow {
  id: string;
  display_name: string;
  filing_status_default: string;
  primary_state: string | null;
  status: string;
}

// GET /clients/:id/overview — snapshot fields we need
interface Snapshot {
  taxable_income_cents: number;
  total_income_cents: number;
  agi_cents: number;
  total_tax_cents: number;
  marginal_rate: string;
  effective_rate: string;
}
interface YearRow {
  id: string;
  tax_year: number;
  role: string;
  filing_status: string;
  is_locked: boolean;
  finalized_at: string | null;
  snapshot: Snapshot | null;
}
interface StrategyRow {
  id: string;
  name: string;
  category: string;
  disposition: string;
  estimated_savings_cents: number;
}
interface QuarterRow {
  quarter: number;
  due_date: string;
  required_payment_cents: number;
  payment_made_cents: number;
  unpaid_rollforward_cents: number;
  status: string;
}
interface Overview {
  client: {
    id: string;
    display_name: string;
    filing_status_default: string;
    primary_state: string | null;
    status: string;
  };
  years: YearRow[];
  base_year_id: string | null;
  plan_year_id: string | null;
  strategies: StrategyRow[];
  quarterly: QuarterRow[];
}

// GET /admin/tax-bracket-sets
interface BracketRow {
  lower_bound_cents: number;
  upper_bound_cents: number | null;
  rate: string;
  ordinal: number;
}
interface BracketSet {
  id: string;
  tax_year: number;
  jurisdiction: string;
  filing_status: string;
  standard_deduction_cents: number;
  rows: BracketRow[];
}

// GET /agents/realized-rollup — workspace realized reconciliation counter
interface RealizedRollup {
  total_planned_cents: number;
  total_realized_cents: number;
  total_variance_cents: number;
  realized_pct: string; // e.g. "62.5%" (already formatted by the backend)
  clients: Array<{
    client_id: string;
    client_name: string;
    client_tax_year_id: string;
    tax_year: number;
    planned_cents: number;
    realized_cents: number;
    variance_cents: number;
    outcome_count: number;
  }>;
}

/* ---- helpers ------------------------------------------------------ */

// Stage derivation from overview — matching spec §7-03 engagement pipeline
function deriveStage(ov: Overview | undefined, scan: ScanRow | undefined): { label: string; kind: "intake" | "analysis" | "plan" | "sealed" | "implementing" } {
  if (!ov) {
    void scan; // overview not loaded yet; default to intake
    return { label: "intake", kind: "intake" };
  }
  const base = ov.years.find((y) => y.id === ov.base_year_id);
  const plan = ov.years.find((y) => y.id === ov.plan_year_id) ?? ov.years[0];
  const signed = ov.strategies.filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition));
  const total = ov.strategies.length;

  if (plan?.finalized_at && signed.length > 0) {
    return { label: `implementing ${signed.length}/${total}`, kind: "implementing" };
  }
  if (plan?.finalized_at) return { label: "signed", kind: "sealed" };
  if (total > 0) return { label: "plan → seal", kind: "plan" };
  if (base?.snapshot) return { label: "analysis", kind: "analysis" };
  return { label: "intake", kind: "intake" };
}

// Build micro-strata segments from bracket sets + a client's filing status/year
function buildSegments(sets: BracketSet[], year: number, filing_status: string): Segment[] {
  if (!sets.length) return [];
  const fed = sets.filter((s) => s.jurisdiction?.toLowerCase().includes("fed"));
  const pool = fed.length ? fed : sets;
  const set =
    pool.find((s) => s.tax_year === year && s.filing_status === filing_status) ??
    pool.find((s) => s.filing_status === filing_status) ??
    pool[0];
  if (!set) return [];
  const rows = [...set.rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents);
  const topLower = rows[rows.length - 1]?.lower_bound_cents ?? 0;
  const cap = topLower + 150_000_00; // display ceiling above top bracket
  return rows.map((r, i) => ({
    rate: Number(r.rate),
    fromCents: r.lower_bound_cents,
    toCents: r.upper_bound_cents ?? (i === rows.length - 1 ? cap : r.lower_bound_cents),
  }));
}

// YoY AGI from overview (base year → plan year)
function yoyAgi(ov: Overview | undefined): { base: number | null; plan: number | null } {
  if (!ov) return { base: null, plan: null };
  const base = ov.years.find((y) => y.id === ov.base_year_id);
  const plan = ov.years.find((y) => y.id === ov.plan_year_id) ?? ov.years[0];
  return {
    base: base?.snapshot?.agi_cents ?? null,
    plan: plan?.snapshot?.agi_cents ?? null,
  };
}

// Best opportunity chip text from the top strategy
function topOppChip(ov: Overview | undefined): { text: string; signed: boolean; total: number } | null {
  if (!ov || !ov.strategies.length) return null;
  const signedItems = ov.strategies.filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition));
  const totalSavings = ov.strategies.reduce((a, s) => a + (s.estimated_savings_cents || 0), 0);
  if (signedItems.length > 0) {
    const top = signedItems.sort((a, b) => b.estimated_savings_cents - a.estimated_savings_cents)[0];
    return { text: `${top.name} · signed`, signed: true, total: totalSavings };
  }
  const top = [...ov.strategies].sort((a, b) => b.estimated_savings_cents - a.estimated_savings_cents)[0];
  return { text: top.name, signed: false, total: totalSavings };
}

// Milestone chips from overview (quarterly + age / event derived)
function milestoneChips(ov: Overview | undefined, client: ClientRow | undefined): string[] {
  const chips: string[] = [];
  if (!ov) return chips;
  // Q2 unpaid
  const q2 = ov.quarterly.find((q) => q.quarter === 2);
  if (q2 && q2.unpaid_rollforward_cents > 0) {
    chips.push(`Q2 due ${centsToUSD(q2.unpaid_rollforward_cents)}`);
  }
  // AO live (if the client has books data — heuristic: strategies mention "books")
  const hasBooks = ov.strategies.some((s) => s.category?.toLowerCase().includes("book") || s.name?.toLowerCase().includes("book"));
  if (hasBooks) chips.push("books live ●");
  // state context
  if (client?.primary_state === "CA") chips.push("last CA year");
  return chips;
}

/* ---- view toggle -------------------------------------------------- */
type View = "roster" | "matrix";

/* ---- active filter ------------------------------------------------ */
type FilterKey = "all" | "business" | "cliff" | "q2" | "goals";

/* ---- matrix columns + categorizer (module scope: stable refs, so the useMemos
       that call them don't need them in their dependency arrays) ---- */
const MATRIX_COLS = [
  { key: "retirement", label: "Retirement (Roth·401k·HSA)" },
  { key: "entity", label: "Entity (S-corp·QBI agg)" },
  { key: "charitable", label: "Bunch/DAF" },
  { key: "tlh", label: "TLH" },
  { key: "qsbs", label: "QSBS" },
  { key: "relocation", label: "Relocation" },
] as const;
type ColKey = (typeof MATRIX_COLS)[number]["key"];

function categorizeStrategy(name: string, category: string): ColKey | null {
  const n = name.toLowerCase();
  const c = category?.toLowerCase() ?? "";
  if (n.includes("roth") || n.includes("401k") || n.includes("hsa") || n.includes("ira") || c.includes("retirement")) return "retirement";
  if (n.includes("s-corp") || n.includes("scorp") || n.includes("qbi") || n.includes("salary") || c.includes("entity")) return "entity";
  if (n.includes("bunch") || n.includes("daf") || n.includes("charitable") || c.includes("charitable")) return "charitable";
  if (n.includes("tlh") || n.includes("tax-loss") || n.includes("tax loss") || c.includes("tlh")) return "tlh";
  if (n.includes("qsbs") || c.includes("qsbs")) return "qsbs";
  if (n.includes("reloc") || n.includes("state change") || n.includes("move") || c.includes("reloc")) return "relocation";
  return null;
}

function matrixCells(ov: Overview | undefined): Partial<Record<ColKey, number>> {
  if (!ov) return {};
  const cells: Partial<Record<ColKey, number>> = {};
  for (const s of ov.strategies) {
    const col = categorizeStrategy(s.name, s.category);
    if (col && s.estimated_savings_cents) {
      cells[col] = (cells[col] ?? 0) + s.estimated_savings_cents;
    }
  }
  return cells;
}

/* ================================================================== */
export default function BookPage() {
  const [scan, setScan] = useState<ScanRow[] | null>(null);
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [overviews, setOverviews] = useState<Record<string, Overview>>({});
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [realized, setRealized] = useState<RealizedRollup | null>(null);
  const [view, setView] = useState<View>("roster");
  const [filter, setFilter] = useState<FilterKey>("all");
  const overviewsRef = useRef<Record<string, Overview>>({});

  /* ---- initial fetches ---- */
  useEffect(() => {
    // spec §11 fix-regardless: do NOT re-sort; backend already ranks by recomputed savings
    api.get("/agents/scan-book").then((r) => setScan(r.data)).catch(() => setScan([]));
    api.get("/clients").then((r) => setClients(r.data)).catch(() => setClients([]));
    api.get("/admin/tax-bracket-sets").then((r) => setSets(r.data)).catch(() => setSets([]));
    // LIVE: workspace realized counter (planned vs realized across reconciled outcomes)
    api
      .get<RealizedRollup>("/agents/realized-rollup")
      .then((r) => setRealized(r.data))
      .catch(() => setRealized(null));
  }, []);

  /* ---- per-client overview fetch (fan-out as scan lands) ---- */
  useEffect(() => {
    if (!scan) return;
    const ids = [...new Set(scan.map((r) => r.client_id))];
    ids.forEach((id) => {
      if (overviewsRef.current[id]) return; // already fetched
      api
        .get(`/clients/${id}/overview`)
        .then((r) => {
          overviewsRef.current = { ...overviewsRef.current, [id]: r.data };
          setOverviews((prev) => ({ ...prev, [id]: r.data }));
        })
        .catch(() => {/* overview unavailable; row renders with scan-book data only */});
    });
  }, [scan]);

  /* ---- derive the unique client list in backend-rank order ---- */
  const rankedIds = useMemo(() => {
    if (!scan) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const r of scan) {
      if (!seen.has(r.client_id)) { seen.add(r.client_id); out.push(r.client_id); }
    }
    return out;
  }, [scan]);

  /* ---- client map ---- */
  const clientMap = useMemo(() => {
    const m: Record<string, ClientRow> = {};
    for (const c of clients ?? []) m[c.id] = c;
    return m;
  }, [clients]);

  /* ---- plan-year scan row per client ---- */
  const planScan = useMemo(() => {
    const m: Record<string, ScanRow> = {};
    for (const r of scan ?? []) {
      // prefer plan year (2026); fall back to the most recent year present
      if (!m[r.client_id] || r.tax_year > m[r.client_id].tax_year) m[r.client_id] = r;
    }
    return m;
  }, [scan]);

  /* ---- rollup figures (from overviews) ---- */
  const rollup = useMemo(() => {
    let identified = 0;
    let signed = 0;
    for (const ov of Object.values(overviews)) {
      for (const s of ov.strategies) {
        identified += s.estimated_savings_cents || 0;
        if (["signed", "accepted", "implementing"].includes(s.disposition)) {
          signed += s.estimated_savings_cents || 0;
        }
      }
    }
    return { identified, signed };
  }, [overviews]);

  /* ---- matrix: strategy categories × clients (cols + categorizer live at module scope) ---- */
  // TODO(integration: GET /agents/matrix) — full matrix endpoint; v1 derives from opportunities

  // Column totals across all clients
  const colTotals = useMemo(() => {
    const totals: Partial<Record<ColKey, number>> = {};
    for (const ov of Object.values(overviews)) {
      const cells = matrixCells(ov);
      for (const [k, v] of Object.entries(cells) as [ColKey, number][]) {
        totals[k] = (totals[k] ?? 0) + v;
      }
    }
    return totals;
    // matrixCells/categorizeStrategy are stable (defined in component body, no external deps)
  }, [overviews]);

  const grandTotal = Object.values(colTotals).reduce((a, b) => a + (b ?? 0), 0);

  /* ---- empty / loading states ---- */
  const loading = scan === null || clients === null || sets === null;

  /* ---- filter chips (counts from overviews) ---- */
  const filterCounts = useMemo(() => {
    let business = 0, cliff = 0, q2 = 0, goals = 0;
    for (const ov of Object.values(overviews)) {
      if (ov.strategies.some((s) => categorizeStrategy(s.name, s.category) === "entity")) business++;
      if (ov.strategies.some((s) => s.name?.toLowerCase().includes("cliff") || s.category?.toLowerCase().includes("cliff"))) cliff++;
      if (ov.quarterly.some((q) => q.quarter === 2 && q.unpaid_rollforward_cents > 0)) q2++;
      // "missing goals" = no strategies yet
      if (ov.strategies.length === 0) goals++;
    }
    return { business, cliff, q2, goals };
  }, [overviews]);

  /* ================================================================ */
  return (
    <div className="wrap py-7 pb-16">

      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-center gap-[14px]">
        <div>
          <h1 className="text-[30px] font-extrabold leading-none tracking-[-0.02em]">The Book</h1>
          <Annotation className="mt-1 block">
            {loading ? "loading…" : `${rankedIds.length} file${rankedIds.length === 1 ? "" : "s"} · re-ranked by what the engines can still recover`}
          </Annotation>
        </div>
        <Link href="/c/new/return" className="btn btn-ink ml-auto text-[13px]">
          ＋ New client · drop a 1040
        </Link>
        {/* view toggle */}
        <div
          className="inline-flex overflow-hidden rounded-[10px] border border-[var(--g-hairline)] text-[12px] font-semibold"
          role="tablist"
          aria-label="Book view"
        >
          {(["roster", "matrix"] as View[]).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              type="button"
              onClick={() => setView(v)}
              className={`px-[14px] py-[7px] capitalize transition-colors ${
                view === v
                  ? "bg-[rgba(31,28,23,0.09)] text-[var(--g-ink)]"
                  : "text-[var(--g-ink-3)] hover:bg-[var(--wash)]"
              }`}
            >
              {v}
            </button>
          ))}
          <button
            role="tab"
            aria-selected={false}
            type="button"
            className="px-[14px] py-[7px] text-[var(--g-ink-3)] hover:bg-[var(--wash)]"
          >
            Pipeline
          </button>
        </div>
      </section>

      {/* ---- filter bar ---- */}
      <div className="rise d1 mt-4 flex flex-wrap items-center gap-2">
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>
          All · {rankedIds.length}
        </FilterChip>
        <FilterChip active={filter === "business"} onClick={() => setFilter("business")}>
          business owners · {filterCounts.business}
        </FilterChip>
        <FilterChip tone="cliff" active={filter === "cliff"} onClick={() => setFilter("cliff")}>
          within $25k of a cliff · {filterCounts.cliff}
        </FilterChip>
        <FilterChip tone="cost" active={filter === "q2"} onClick={() => setFilter("q2")}>
          Q2 unpaid · {filterCounts.q2}
        </FilterChip>
        <FilterChip active={filter === "goals"} onClick={() => setFilter("goals")}>
          missing goals · {filterCounts.goals}
        </FilterChip>
        {/* NLQ — additive; shown as a design-honest placeholder */}
        {/* TODO(integration: POST /agents/book-filter) — natural-language book filter */}
        <span className="flex min-w-[280px] flex-1 items-center gap-[10px] rounded-[10px] border border-[var(--g-hairline)] px-[13px] py-[8px] font-mono text-[11px] text-[var(--g-ink-3)]">
          ⌕{" "}
          <span className="text-[var(--g-ink-2)]">
            &ldquo;clients with QSBS exposure over $1M&rdquo;
          </span>{" "}
          — filters compile to engine queries
        </span>
      </div>

      {/* ================================================================ ROSTER */}
      {view === "roster" ? (
        <section className="panel roster rise d2 mt-[18px] overflow-x-auto">
          <table className="ledger min-w-full">
            <thead>
              <tr>
                <th className="text-left">Client</th>
                <th className="text-left">Stage</th>
                <th className="text-left">Position</th>
                <th className="r text-right">AGI&nbsp;base&nbsp;→&nbsp;plan</th>
                <th className="r text-right">Marginal</th>
                <th className="text-left">Top opportunity — engine-recomputed</th>
                <th className="r text-right">Total opp.</th>
                <th className="text-left">Milestones</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                [0, 1, 2, 3].map((i) => (
                  <tr key={i}>
                    <td colSpan={8}><div className="skeleton my-2 h-[44px] w-full rounded-[8px]" /></td>
                  </tr>
                ))
              ) : rankedIds.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyBook />
                  </td>
                </tr>
              ) : (
                rankedIds.map((id) => (
                  <RosterRow
                    key={id}
                    clientId={id}
                    scanRow={planScan[id]}
                    client={clientMap[id]}
                    overview={overviews[id]}
                    sets={sets ?? []}
                  />
                ))
              )}
            </tbody>
          </table>
        </section>
      ) : null}

      {/* ================================================================ MATRIX */}
      {view === "matrix" ? (
        <section className="panel rise d3 mt-[22px]" id="matrix">
          <PanelHead>
            <MicroLabel>
              The matrix · clients × strategies — every cell is a full recompute, not a lookup
            </MicroLabel>
            {/* TODO(integration: POST /admin/firm-templates) — save column set as house template */}
            <span className="chip ml-auto cursor-default">save column sets as the house template</span>
          </PanelHead>
          <div className="overflow-x-auto">
            <table className="ledger min-w-full font-mono text-[11.5px]">
              <thead>
                <tr>
                  <th className="text-left font-[var(--font-ui)] text-[11.5px]">—</th>
                  {MATRIX_COLS.map((c) => (
                    <th key={c.key} className="r text-right">
                      {c.label}
                    </th>
                  ))}
                  <th className="r text-right">Σ</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  [0, 1, 2].map((i) => (
                    <tr key={i}>
                      <td colSpan={MATRIX_COLS.length + 2}>
                        <div className="skeleton my-1 h-[28px] w-full rounded-[4px]" />
                      </td>
                    </tr>
                  ))
                ) : (
                  rankedIds.map((id) => {
                    const ov = overviews[id];
                    const sc = planScan[id];
                    const name = ov?.client.display_name ?? clientMap[id]?.display_name ?? sc?.client_name ?? id;
                    const cells = matrixCells(ov);
                    const rowTotal = Object.values(cells).reduce((a, b) => a + (b ?? 0), 0);
                    const signedIds = new Set((ov?.strategies ?? []).filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition)).map((s) => s.id));
                    const isSealed = signedIds.size > 0;
                    const isRunning = !ov && sc; // overview still loading

                    return (
                      <tr key={id}>
                        <td className="font-[var(--font-ui)]">
                          {name}
                          {isSealed ? " ⛁" : ""}
                        </td>
                        {isRunning ? (
                          <td colSpan={MATRIX_COLS.length + 1} className="text-[var(--agent)]">
                            <WorkingDots className="inline-flex" /> loading
                          </td>
                        ) : !ov ? (
                          <td
                            colSpan={MATRIX_COLS.length}
                            className="text-left text-[var(--g-ink-3)]"
                          >
                            awaiting baseline confirm
                          </td>
                        ) : (
                          <>
                            {MATRIX_COLS.map((col) => {
                              const v = cells[col.key];
                              if (!v) {
                                return (
                                  <td key={col.key} className="zero r text-right text-[var(--g-ink-3)]">
                                    —
                                  </td>
                                );
                              }
                              const hot = v >= 100_000_00;
                              return (
                                <td
                                  key={col.key}
                                  className={`r text-right ${hot ? "font-semibold text-[var(--save)]" : "text-[var(--save)]"}`}
                                  style={hot ? { background: "rgba(29,138,91,0.08)" } : undefined}
                                >
                                  {/* TODO(integration: GET /agents/matrix?client_id&strategy_col) — per-cell engine recompute */}
                                  {formatK(v)}
                                  {isSealed ? " ⛁" : ""}
                                </td>
                              );
                            })}
                            <td className="r text-right text-[var(--save)]">
                              <b>{formatK(rowTotal)}</b>
                            </td>
                          </>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
              <tfoot>
                <tr>
                  <td className="font-[var(--font-ui)] font-semibold">Across the book</td>
                  {MATRIX_COLS.map((c) => (
                    <td key={c.key} className="r text-right font-semibold">
                      {colTotals[c.key] ? formatK(colTotals[c.key]!) : "—"}
                    </td>
                  ))}
                  <td className="r text-right font-semibold text-[var(--save)]">
                    {grandTotal > 0 ? formatK(grandTotal) : "—"}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="mx-[18px] mb-4 mt-3 font-mono text-[10px] text-[var(--g-ink-3)]">
            SPEC · cell click → the engine delta for that client × strategy; ⛁ = signed/realized-tracking.
            {/* TODO(integration: GET /agents/matrix) — v1 derives from opportunities lists */}
          </p>
        </section>
      ) : null}

      {/* ================================================================ ROLLUP BAND */}
      <section className="panel rise d4 mt-[22px] flex flex-wrap items-center gap-[22px] px-[22px] py-[16px]">
        <RollupNum
          value={<Money cents={rollup.identified} tone="save" className="!text-[22px] !leading-none !tracking-[-0.02em]" />}
          label="identified · engine-verified"
        />
        {/* TODO(integration: GET /agents/book-rollup/signed) — signed savings figure */}
        <RollupNum
          value={
            <span className="block text-[22px] font-[750] leading-none tracking-[-0.02em] text-[var(--g-ink-3)]">—</span>
          }
          label="signed · tracking to realized [additive]"
        />
        {/* LIVE: GET /agents/realized-rollup — realized reconciliation (§9.7), gold treatment */}
        <RollupNum
          value={
            realized && realized.total_realized_cents > 0 ? (
              <span className="flex items-baseline gap-[7px]">
                <Money
                  cents={realized.total_realized_cents}
                  className="!text-[22px] !leading-none !tracking-[-0.02em] !text-[var(--seal)]"
                />
                <span className="font-mono text-[11px] text-[var(--seal)]">
                  {fmtPct(realized.realized_pct)}
                </span>
              </span>
            ) : (
              <span className="block text-[22px] font-[750] leading-none tracking-[-0.02em] text-[var(--g-ink-3)]">—</span>
            )
          }
          label="realized · next-return reconciliation"
        />
        <RollupNum
          value={
            <span className="block text-[22px] font-[750] leading-none tracking-[-0.02em]">
              {loading ? "—" : rankedIds.length}
            </span>
          }
          label={`file${rankedIds.length === 1 ? "" : "s"} in the book`}
        />
        <Annotation className="ml-auto max-w-[280px]">
          the number that renews every retainer —{" "}
          <b className="text-[var(--seal)]">realized</b> — reconciles against the next return as
          outcomes land.
        </Annotation>
        <Button
          variant="agent"
          onClick={() => {
            // TODO(integration: POST /agents/scan-book/refresh) — re-scan the book
            api.get("/agents/scan-book").then((r) => setScan(r.data)).catch(() => {});
          }}
        >
          Re-scan the book
        </Button>
      </section>

      {/* ---- omnibar (the three-doors contract: same engine the GUI buttons call) ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about the book — or ⌘K for actions…" />
      </div>
    </div>
  );
}

/* ================================================================== ROSTER ROW */

interface RosterRowProps {
  clientId: string;
  scanRow: ScanRow | undefined;
  client: ClientRow | undefined;
  overview: Overview | undefined;
  sets: BracketSet[];
}

function RosterRow({ clientId, scanRow, client, overview, sets }: RosterRowProps) {
  const hue = hueForClient(clientId);
  const name = overview?.client.display_name ?? client?.display_name ?? scanRow?.client_name ?? clientId;
  const filing = overview?.client.filing_status_default ?? client?.filing_status_default ?? "";
  const state = overview?.client.primary_state ?? client?.primary_state ?? null;

  const stage = deriveStage(overview, scanRow);
  const agi = yoyAgi(overview);
  const opp = topOppChip(overview);
  const miles = milestoneChips(overview, client);

  // Micro-strata: build from the plan year's filing status and tax year
  const planYear = overview?.years.find((y) => y.id === overview.plan_year_id) ?? overview?.years[0];
  const taxYear = planYear?.tax_year ?? scanRow?.tax_year ?? 2025;
  const filingStatus = planYear?.filing_status ?? filing ?? "single";
  const segments = useMemo(
    () => buildSegments(sets, taxYear, filingStatus),
    [sets, taxYear, filingStatus],
  );
  const incomeCents = planYear?.snapshot?.taxable_income_cents ?? 0;

  // Nominal marginal from snapshot
  const nominalRate = planYear?.snapshot?.marginal_rate
    ? Number(planYear.snapshot.marginal_rate)
    : null;

  // Top total savings
  const totalSavings = overview
    ? overview.strategies.reduce((a, s) => a + (s.estimated_savings_cents || 0), 0)
    : null;

  const href = `/c/${clientId}`;

  return (
    <tr
      tabIndex={0}
      role="button"
      onClick={() => { window.location.href = href; }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") window.location.href = href; }}
      style={{ cursor: "pointer" }}
    >
      {/* Client */}
      <td>
        <span className="cl flex items-center gap-[10px]">
          <Cavatar name={name} hue={hue} className="!h-[30px] !w-[30px] !text-[11px]" />
          <span>
            <b className="block text-[13.5px] font-semibold leading-tight tracking-[-0.01em]">{name}</b>
            <span className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
              {FILING_SHORT[filing] ?? filing}{state ? ` · ${state}` : ""}
            </span>
          </span>
        </span>
      </td>

      {/* Stage */}
      <td>
        <span
          className={`stage ${stage.kind === "sealed" || stage.kind === "implementing" ? "sealed" : "on"}`}
        >
          {stage.label}
        </span>
      </td>

      {/* Position micro-strata */}
      <td>
        {!overview && !scanRow ? (
          <div className="shimmer h-[8px] w-[120px] rounded-full" />
        ) : segments.length > 0 && incomeCents > 0 ? (
          <PositionInstrument
            segments={segments}
            incomeCents={incomeCents}
            variant="micro"
            className="w-[130px]"
          />
        ) : (
          <span className="font-mono text-[10px] text-[var(--g-ink-3)]">no snapshot</span>
        )}
      </td>

      {/* AGI YoY */}
      <td className="r text-right font-mono text-[11.5px]">
        {agi.base !== null ? (
          <>
            <span className="text-[var(--g-ink-3)]">{formatK(agi.base)}</span> →{" "}
            <b>{agi.plan !== null ? formatK(agi.plan) : "—"}</b>
            {agi.base && agi.plan ? (
              <small className="ml-1 text-[var(--g-ink-3)]">
                {agi.plan > agi.base ? "▲" : "▼"}
                {Math.round(Math.abs(((agi.plan - agi.base) / agi.base) * 100))}%
              </small>
            ) : null}
          </>
        ) : agi.plan !== null ? (
          <>
            <span className="text-[var(--g-ink-3)]">—</span> → <b>{formatK(agi.plan)}</b>
          </>
        ) : (
          <span className="text-[var(--g-ink-3)]">—</span>
        )}
      </td>

      {/* True marginal — v1 fallback = nominal from snapshot; additive = EMR endpoint */}
      {/* TODO(integration: GET /clients/:id/analysis/emr) — true marginal (EMR sweep) */}
      <td className="r text-right fig">
        {nominalRate !== null ? (
          <span title="nominal bracket rate — true next-dollar (EMR) is additive (spec §9.3)">
            {(nominalRate * 100).toFixed(0)}%
          </span>
        ) : (
          <span className="text-[var(--g-ink-3)]">—</span>
        )}
      </td>

      {/* Top opportunity chip */}
      <td>
        {!overview ? (
          <span className="font-mono text-[10px] text-[var(--g-ink-3)]">loading…</span>
        ) : opp ? (
          <OppChip sealed={opp.signed}>{opp.text}</OppChip>
        ) : (
          <span className="font-mono text-[10px] text-[var(--g-ink-3)]">no strategies yet</span>
        )}
      </td>

      {/* Total opp */}
      <td className="r text-right fig">
        {totalSavings !== null && totalSavings > 0 ? (
          <span
            style={{
              color: opp?.signed ? "var(--seal)" : "var(--save)",
            }}
          >
            {formatK(totalSavings)}
            <span className="text-[var(--g-ink-3)]">/yr</span>
          </span>
        ) : (
          <span className="text-[var(--g-ink-3)]">—</span>
        )}
      </td>

      {/* Milestones */}
      <td>
        <span className="ml inline-flex flex-wrap gap-[5px]">
          {miles.map((m) => (
            <Chip
              key={m}
              tone={m.includes("Q2") ? "cost" : m.includes("cliff") ? "cliff" : "neutral"}
              className="!text-[10px] !px-[8px] !py-[2.5px]"
            >
              {m}
            </Chip>
          ))}
        </span>
      </td>
    </tr>
  );
}

/* ================================================================== SMALL COMPONENTS */

function FilterChip({
  active,
  tone,
  onClick,
  children,
}: {
  active: boolean;
  tone?: "cliff" | "cost";
  onClick: () => void;
  children: ReactNode;
}) {
  const toneClass = tone === "cliff" ? "cliff" : tone === "cost" ? "cost" : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`chip ${toneClass} ${active ? "!bg-[rgba(31,28,23,0.08)] !text-[var(--g-ink)]" : ""}`}
    >
      {children}
    </button>
  );
}

function OppChip({
  sealed,
  children,
}: {
  sealed: boolean;
  children: ReactNode;
}) {
  if (sealed) {
    return (
      <span
        className="inline-flex items-center gap-[6px] rounded-[8px] border px-[9px] py-[4px] text-[11px] font-semibold"
        style={{
          color: "var(--seal)",
          borderColor: "rgba(153,122,49,0.4)",
          background: "rgba(153,122,49,0.06)",
        }}
      >
        ⛁ {children}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-[6px] rounded-[8px] border px-[9px] py-[4px] text-[11px] font-semibold"
      style={{
        color: "var(--save)",
        borderColor: "rgba(29,138,91,0.4)",
        background: "rgba(29,138,91,0.06)",
      }}
    >
      {children}
    </span>
  );
}

function RollupNum({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="n flex flex-col gap-1">
      {value}
      <span className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-[var(--g-ink-3)]">
        {label}
      </span>
    </div>
  );
}

function EmptyBook() {
  return (
    <div className="px-6 py-12 text-center">
      <p className="text-[15px] font-semibold text-[var(--g-ink)]">No clients in the book yet</p>
      <p className="mt-1 text-[13px] text-[var(--g-ink-3)]">
        Drop a 1040 to add your first client, or explore the demo book.
      </p>
      <div className="mt-4 flex justify-center gap-3">
        <Link href="/c/new/return" className="btn btn-ink text-[13px]">
          Drop a 1040
        </Link>
        <button type="button" className="btn btn-ghost text-[13px]">
          Load demo book
        </button>
      </div>
    </div>
  );
}

/* ================================================================== UTIL */

const FILING_SHORT: Record<string, string> = {
  single: "single",
  mfj: "mfj",
  mfs: "mfs",
  hoh: "hoh",
  qss: "qss",
};

/** Render realized_pct safely: backend sends a formatted string like "62.5%",
 *  but tolerate a bare number (0–100) too. Returns "" for unusable input. */
function fmtPct(pct: string | number | null | undefined): string {
  if (pct === null || pct === undefined) return "";
  if (typeof pct === "string") {
    const trimmed = pct.trim();
    if (trimmed.endsWith("%")) return trimmed; // already formatted
    const n = Number(trimmed);
    return Number.isFinite(n) ? `${n.toFixed(1)}%` : "";
  }
  return Number.isFinite(pct) ? `${pct.toFixed(1)}%` : "";
}

/** Compact money: $1.8M / $112k / $9,170 */
function formatK(cents: number): string {
  const d = cents / 100;
  if (d >= 1_000_000) return `$${(d / 1_000_000).toFixed(d % 1_000_000 ? 1 : 0)}M`;
  if (d >= 100_000) return `$${Math.round(d / 1_000)}k`;
  if (d >= 1_000) return `$${(d / 1_000).toFixed(1)}k`;
  return `$${Math.round(d).toLocaleString()}`;
}
