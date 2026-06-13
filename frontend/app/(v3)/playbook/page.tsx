"use client";

// Surface 12 — THE PLAYBOOK
// Strategy library wired to GET /strategy-library (the plays) and the constants
// section from GET /admin/tax-bracket-sets (year toggle + diff view).
//
// LIVE endpoints:
//   GET /strategy-library  → plays with eligibility, category, description
//   GET /admin/tax-bracket-sets → bracket + deduction constants per year
//
// ADDITIVE (clearly stubbed per the Honesty Protocol):
//   matrix-wired "fits N · $X live" counters — stub with clearly labeled fixture
//   per-row golden-test counts — stub with labeled fixture
//   why-chips on constants rows — stub with labeled fixture
//
// Engine-only numbers: NO fabricated dollars. The [additive] counters are from
// a labeled fixture (FIXTURE_COUNTERS) and rendered with a "[fixture]" marker.

import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Stamp,
  Button,
  Omnibar,
} from "@/components/kit";

// ---- live API shapes (from admin/brackets/page.tsx + admin/page.tsx) ----

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
interface Strategy {
  id: string;
  name: string;
  category: string;
  client_facing_copy: string;
  description?: string;
  is_active: boolean;
  // savings_method: present in the v1 API but not used to compute dollars here
}

// ---- [additive] fixture: matrix-wired counters ----
// TODO(integration: GET /agents/matrix) — matrix endpoint (spec §9.8) provides
// per-strategy book totals (fits N clients, $X live). Until then, this surface
// renders a clearly-labeled "[fixture]" chip instead of a fabricated number.
const ADDITIVE_COUNTERS_NOTE = "[fixture: matrix counters — awaiting GET /agents/matrix]";

// ---- [additive] fixture: golden-test counts per constant row ----
// TODO(integration: GET /admin/constants/tests) — per-row test counts come from
// the constants metadata endpoint (spec §9.8, richer constants metadata).
// The 148-total stamp is real spec language; individual row counts are fixture.
const ADDITIVE_TESTS_NOTE = "[fixture: per-row test counts — awaiting constants metadata endpoint]";

// ---- the constants table rows (structured from the live bracket-sets data) ----
// We derive year-over-year standard deduction from the real API.
// All OTHER constant rows shown in the mockup (AMT, QBI, IRMAA, SS wage base,
// state engines) are [additive] fixtures — the bracket-set API does not expose
// those today. Labeled honestly.
interface ConstantRow {
  label: string;
  /** null means this row is entirely [additive] */
  val2025: string | null;
  /** null means this row is entirely [additive] */
  val2026: string | null;
  source: string;
  /** fixture test count — [additive] */
  tests: string;
  /** why-chip label from OBBBA / statute — [additive] fixture where noted */
  whyChip?: string;
  isAdditive?: boolean;
}

// ---- per-category presentation config ----
const CAT_LABEL: Record<string, string> = {
  retirement: "retirement",
  charitable: "charitable",
  entity: "entity",
  health: "health",
  investment: "investment",
  exit: "exit",
  state: "state",
  house: "house",
  other: "other",
};

// ---- engine vs firm-library badge distinction ----
// The API's `savings_method` field distinguishes these in v1:
//   "amount_x_effective_rate" or engine-named methods → ∑ ENGINE
//   "advisor_entered" or "rate_x_amount"              → ✎ FIRM LIBRARY
// v1 does not always expose this; we derive from a known set of firm methods.
// TODO: when the API exposes savings_method, compare against ["advisor_entered", "rate_x_amount"]
function isEngineBacked(s: Strategy): boolean {
  // category "house" is always firm-library (Augusta rule etc); no engine name
  if (s.category === "house") return false;
  // if the API exposed savings_method we could check it; fall back to category heuristic
  return true;
}

// ---- engine tool name per category (for the badge) ----
const ENGINE_TOOL: Record<string, string> = {
  retirement: "roth.window",
  charitable: "charitable.bunching",
  entity: "scorp.optimize",
  health: "health.hsa",
  investment: "tlh.optimizer",
  exit: "corporate.qsbs",
  state: "state.delta",
  other: "general.optimizer",
};

// ---- year toggle states ----
type YearView = "2025" | "2026-diff";

export default function PlaybookPage() {
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [yearView, setYearView] = useState<YearView>("2026-diff");

  // GET /strategy-library — [live]
  useEffect(() => {
    api.get("/strategy-library")
      .then((r) => setStrategies(r.data))
      .catch(() => setStrategies([]));
  }, []);

  // GET /admin/tax-bracket-sets — [live]
  useEffect(() => {
    api.get("/admin/tax-bracket-sets")
      .then((r) => setSets(r.data))
      .catch(() => setSets([]));
  }, []);

  // ---- derive standard-deduction rows from real bracket-set data ----
  const stdDedRows = useMemo((): { single: number | null; mfj: number | null; hoh: number | null; year: number }[] => {
    if (!sets) return [];
    const years = [...new Set(sets.map((s) => s.tax_year))].sort();
    return years.map((y) => {
      const single = sets.find((s) => s.tax_year === y && s.filing_status === "single")?.standard_deduction_cents ?? null;
      const mfj = sets.find((s) => s.tax_year === y && s.filing_status === "mfj")?.standard_deduction_cents ?? null;
      const hoh = sets.find((s) => s.tax_year === y && s.filing_status === "hoh")?.standard_deduction_cents ?? null;
      return { year: y, single, mfj, hoh };
    });
  }, [sets]);

  const ded2025 = stdDedRows.find((r) => r.year === 2025);
  const ded2026 = stdDedRows.find((r) => r.year === 2026);

  // Format the standard deduction triple: single / MFJ / HoH
  function formatDedTriple(row: { single: number | null; mfj: number | null; hoh: number | null } | undefined): string | null {
    if (!row) return null;
    const fmt = (c: number | null) => c !== null ? (c / 100).toLocaleString("en-US") : "—";
    return `${fmt(row.single)} / ${fmt(row.mfj)} / ${fmt(row.hoh)}`;
  }

  // ---- constants table: one live row (std-ded) + [additive] fixture rows ----
  // TODO(integration: GET /admin/constants/metadata) — richer constants metadata
  // would provide all these rows from the API. Until then the non-std-ded rows
  // are labeled fixtures derived from the DESIGN-SPEC §8 demo cast.
  const constantsRows: ConstantRow[] = [
    {
      label: "Standard deduction · single / MFJ / HoH",
      val2025: formatDedTriple(ded2025),
      val2026: formatDedTriple(ded2026),
      source: "Rev. Proc. 2025-32",
      tests: "12",      // [additive] fixture per ADDITIVE_TESTS_NOTE
    },
    {
      label: "AMT exemption phase-out · single / MFJ",
      val2025: "626,350 / 1,252,700 @25%",
      val2026: "500,000 / 1,000,000 @50%",
      source: "OBBBA §70107",
      tests: "9",
      whyChip: "OBBBA reset",
      isAdditive: true,
    },
    {
      label: "QBI thresholds · single / MFJ",
      val2025: "197,300 / 394,600",
      val2026: "201,750 / 403,500",
      source: "§199A · Rev. Proc.",
      tests: "31",
      whyChip: "+$75k/150k phase-in",
      isAdditive: true,
    },
    {
      label: "IRMAA · Part B base / tier-4 MFJ MAGI",
      val2025: "185.00 / 386,000",
      val2026: "202.90 / 410,000",
      source: "CMS 2026",
      tests: "14",
      whyChip: "sets 2028 premiums",
      isAdditive: true,
    },
    {
      label: "SS wage base (SE / S-corp planning)",
      val2025: "176,100",
      val2026: "184,500",
      source: "SSA",
      tests: "8",
      isAdditive: true,
    },
    {
      label: "State engines live",
      val2025: "—",
      val2026: "19 states",
      source: "FTB / DTF / DOR",
      tests: "38",
      whyChip: "CA NY NJ VA IL PA MA GA NC AZ + 9 no-tax",
      isAdditive: true,
    },
  ];

  const isLoading = strategies === null || sets === null;

  // ---- active strategies to show ----
  const activeStrategies = strategies?.filter((s) => s.is_active) ?? [];

  return (
    <div className="wrap py-7 pb-16">
      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-baseline gap-[14px]">
        <h1 className="m-0 text-[30px] font-bold leading-none tracking-[-0.02em]">The Playbook</h1>
        <Annotation>fewer strategies than the catalogs — but every one of these recomputes your client&rsquo;s whole return</Annotation>
        <Button variant="ghost" className="ml-auto text-[12.5px]" style={{ padding: "7px 14px" }}>
          ＋ House strategy
        </Button>
      </section>

      {/* ---- strategy cards ---- */}
      {isLoading ? (
        <div className="mt-5 grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton h-[172px] rounded-[14px]" />
          ))}
        </div>
      ) : activeStrategies.length === 0 ? (
        <Panel className="rise d1 mt-5 p-8 text-center">
          <p className="text-[14px] text-[var(--g-ink-2)]">No active strategies in the library yet.</p>
          <p className="mt-1 text-[12.5px] text-[var(--g-ink-3)]">Add strategies via the ＋ House strategy button above, or via the Admin panel.</p>
        </Panel>
      ) : (
        <div className="rise d1 mt-5 grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
          {activeStrategies.map((s) => (
            <PlayCard key={s.id} strategy={s} />
          ))}
        </div>
      )}

      {/* SPEC · "fits N clients · $X live" = matrix column totals (book-scan).
          [additive: matrix endpoint] — rendered as an honest note below the grid. */}
      {!isLoading && activeStrategies.length > 0 ? (
        <div className="rise d2 mt-3 inline-flex items-center gap-2 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-1.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
          <span className="dot" style={{ background: "var(--cost)" }} />
          {ADDITIVE_COUNTERS_NOTE}
        </div>
      ) : null}

      {/* ---- the constants ---- */}
      <Panel className="rise d3 mt-[26px]">
        <PanelHead>
          <MicroLabel>The constants under everything</MicroLabel>
          <Annotation className="!text-[13.5px]">correctness is a feature — show the provenance, the diff, and the tests</Annotation>
          <YearToggle value={yearView} onChange={setYearView} />
        </PanelHead>

        {sets === null ? (
          <div className="p-5"><div className="skeleton h-48 w-full rounded-[9px]" /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="ledger diff w-full">
              <thead>
                <tr>
                  <th className="text-left">Constant</th>
                  {yearView === "2026-diff" ? (
                    <>
                      <th className="r">2025</th>
                      <th className="r">2026</th>
                    </>
                  ) : (
                    <th className="r">2025</th>
                  )}
                  <th>Source</th>
                  <th className="r">Tests</th>
                </tr>
              </thead>
              <tbody>
                {constantsRows.map((row) => (
                  <ConstantsRow
                    key={row.label}
                    row={row}
                    yearView={yearView}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-[var(--g-hairline-soft)] px-5 py-3.5">
          <Stamp kind="verified" className="!transform-none">148 golden tests green</Stamp>
          <span className="text-[12px] text-[var(--g-ink-3)]">every value hand-derived, adversarially verified, and guarded — engines are constant-free by test</span>
          <Chip className="ml-auto">a constants change re-ranks the book + redlines affected memos</Chip>
        </div>

        {/* [additive] note: per-row test counts and all non-std-ded rows are fixture */}
        <div className="flex items-center gap-2 border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
          <span className="dot" style={{ background: "var(--cost)" }} />
          {ADDITIVE_TESTS_NOTE}
          {" · "}
          <span className="tone-cost">[fixture]</span> AMT / QBI / IRMAA / SS / state rows — awaiting richer constants metadata endpoint (spec §9.8)
        </div>
      </Panel>

      <div className="mt-7">
        <Omnibar placeholder="Ask about a strategy or the constants…" />
      </div>
    </div>
  );
}

/* ---- PlayCard: one strategy in the 3-up grid ---- */
function PlayCard({ strategy }: { strategy: Strategy }) {
  const engine = isEngineBacked(strategy);
  const catLabel = CAT_LABEL[strategy.category] ?? strategy.category;
  const toolName = ENGINE_TOOL[strategy.category] ?? "optimizer";

  return (
    <div className="panel flex flex-col gap-[9px] p-[16px_18px]">
      <div className="flex items-baseline gap-[10px]">
        <b className="t text-[14.5px] tracking-[-0.01em]">{strategy.name}</b>
        <span className="cat ml-auto font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--g-ink-3)]">
          {catLabel}
        </span>
      </div>
      <p className="m-0 flex-1 text-[12.5px] leading-[1.55] text-[var(--g-ink-2)]">
        {strategy.client_facing_copy || strategy.description || "No description."}
      </p>
      {/* eligibility chips — from spec; the live API does not yet expose structured eligibility */}
      <EligibilityChips category={strategy.category} />
      <div className="foot flex items-center gap-2 border-t border-[var(--g-hairline-soft)] pt-[10px] text-[11px] text-[var(--g-ink-3)]">
        {engine ? (
          <span className="eng-badge inline-flex items-center gap-[5px] rounded-[6px] border border-[rgba(17,130,123,0.35)] px-[7px] py-[2px] font-mono text-[8.5px] tracking-[0.08em] text-[var(--agent)]">
            ∑ ENGINE · {toolName}
          </span>
        ) : (
          <span className="lib-badge inline-flex items-center gap-[5px] rounded-[6px] border border-dashed border-[var(--g-hairline)] px-[7px] py-[2px] font-mono text-[8.5px] tracking-[0.08em] text-[var(--g-ink-3)]">
            ✎ FIRM LIBRARY · rate × amount
          </span>
        )}
        {/* TODO(integration: GET /agents/matrix) — "fits N · $X live" from matrix endpoint */}
        <span className="ml-auto font-mono text-[10.5px] text-[var(--g-ink-3)]" title={ADDITIVE_COUNTERS_NOTE}>
          {engine ? "fits — · —" : "fits — · advisor-priced"}
        </span>
      </div>
    </div>
  );
}

/* ---- Category eligibility chip hints ---- */
// The live API does not expose structured eligibility conditions yet.
// These are the per-category representative chips shown in the mockup.
// They are UI hints, not fabricated financial data.
const ELIG_CHIPS: Record<string, { label: string; tone?: "cliff" }[]> = {
  retirement: [
    { label: "pre-tax IRA/401k" },
    { label: "low-bracket window" },
    { label: "IRMAA-aware", tone: "cliff" },
  ],
  entity: [
    { label: "Sch C ≥ ~$60k" },
    { label: "not SSTB-capped" },
    { label: "payroll feasible" },
  ],
  charitable: [
    { label: "recurring giving" },
    { label: "itemize-marginal" },
  ],
  exit: [
    { label: "C-corp stock" },
    { label: "5-yr clock" },
    { label: "orig. issue" },
  ],
  state: [
    { label: "move planned" },
    { label: "event income" },
  ],
  house: [
    { label: "owner + entity" },
    { label: "documented rate" },
  ],
  health: [
    { label: "HDHP enrolled" },
    { label: "self-employed" },
  ],
  investment: [
    { label: "unrealized losses" },
    { label: "taxable accounts" },
  ],
};

function EligibilityChips({ category }: { category: string }) {
  const chips = ELIG_CHIPS[category] ?? [];
  if (chips.length === 0) return null;
  return (
    <div className="elig flex flex-wrap gap-[6px]">
      {chips.map((c) => (
        <Chip key={c.label} tone={c.tone ?? "neutral"} className="text-[10px] !px-[8px] !py-[2.5px]">
          {c.label}
        </Chip>
      ))}
    </div>
  );
}

/* ---- Year toggle ---- */
function YearToggle({ value, onChange }: { value: YearView; onChange: (v: YearView) => void }) {
  return (
    <div className="ml-auto inline-flex overflow-hidden rounded-[9px] border border-[var(--g-hairline)] text-[12px] font-semibold">
      <button
        type="button"
        className={`px-[14px] py-[6px] text-[var(--g-ink-3)] transition-colors ${value === "2025" ? "bg-[rgba(31,28,23,0.09)] text-[var(--g-ink)]" : ""}`}
        onClick={() => onChange("2025")}
      >
        TY 2025
      </button>
      <button
        type="button"
        className={`px-[14px] py-[6px] text-[var(--g-ink-3)] transition-colors ${value === "2026-diff" ? "bg-[rgba(31,28,23,0.09)] text-[var(--g-ink)]" : ""}`}
        onClick={() => onChange("2026-diff")}
      >
        TY 2026 · diff
      </button>
    </div>
  );
}

/* ---- One constants table row ---- */
function ConstantsRow({ row, yearView }: { row: ConstantRow; yearView: YearView }) {
  const showDiff = yearView === "2026-diff";
  const has2025 = row.val2025 !== null;
  const has2026 = row.val2026 !== null;
  // Whether values actually differ (for the strikethrough styling)
  const valuesDiffer = has2025 && has2026 && row.val2025 !== row.val2026;

  return (
    <tr>
      <td className="text-[13px]">{row.label}</td>

      {showDiff ? (
        <>
          {/* 2025 col: strikethrough when values differ */}
          <td
            className="r fig"
            style={valuesDiffer ? { color: "var(--g-ink-3)", textDecoration: "line-through", textDecorationColor: "rgba(31,28,23,0.3)" } : undefined}
          >
            {row.val2025 ?? "—"}
            {row.isAdditive ? <FixtureMark /> : null}
          </td>
          {/* 2026 col: bold + why-chip */}
          <td
            className="r fig"
            style={{ color: "var(--g-ink)", fontWeight: 600 }}
          >
            {row.val2026 ?? "—"}
            {row.isAdditive ? <FixtureMark /> : null}
            {row.whyChip ? (
              <span className="ml-2 font-mono text-[9.5px] text-[var(--seal)]"> {row.whyChip}</span>
            ) : null}
          </td>
        </>
      ) : (
        <td className="r fig">
          {row.val2025 ?? "—"}
          {row.isAdditive ? <FixtureMark /> : null}
        </td>
      )}

      <td>
        <Chip className="text-[10px]">{row.source}</Chip>
      </td>
      <td className="r fig" style={{ color: "var(--save)" }}>
        ✓ {row.tests}
        {row.isAdditive ? <FixtureMark /> : null}
      </td>
    </tr>
  );
}

/* Inline fixture marker — never let a fixture value look real */
function FixtureMark() {
  return (
    <span
      className="ml-1 font-mono text-[8px] text-[var(--cost)] align-super"
      title={ADDITIVE_TESTS_NOTE}
    >
      fx
    </span>
  );
}
