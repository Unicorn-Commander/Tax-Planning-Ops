"use client";

// Surface 05 — THE LAB (frontier). Scenario bank with an immutable Baseline
// (clones only — enforced data model). The conversion instrument: the strata as
// a CONTROL; the drag handle sizes the conversion, the readout chips and the
// scenario ledger column recompute through the REAL engine on release. EMR
// terrain from the real sweep. Crossover (the bracket-fill cost trace) + the
// fill schedule from the optimizer trace. What-if omnibar.
//
// HONESTY PROTOCOL — what is live vs illustrative (never fabricated):
//
// [live] The Position (PositionInstrument): real bracket sets + real snapshot.
//        The baseline row in the ledger: real snapshot figures.
//        The IRMAA cliff: real analysis.irmaa data.
//        Statutory rate steps for EMRTerrain: derived from real bracket-set rows.
//
// [live] The conversion drag recompute — POST /agents/clients/tax-years/:id/scenario
//        with delta_fields {ira_taxable_cents}. On drag-release (debounced) the
//        readout chips (move tax, scenario marginal) and the live scenario ledger
//        column show REAL engine output (tax_delta_cents, agi/taxable deltas,
//        scenario total, marginal_rate_scenario). The IRMAA binding chip stays the
//        real analysis figure. Baseline is untouched.
// [live] The EMR terrain — POST /agents/clients/tax-years/:id/emr-sweep. The curve
//        is the engine's EFFECTIVE marginal (Δtax/Δincome) per step, the badge is
//        the real true-next-dollar rate, the vertical dashed lines are the real
//        cliff_overlays threshold incomes (threshold only — no fabricated cost),
//        and the statutory dashed line stays real (bracket table).
// [live] The crossover + fill schedule — POST /agents/clients/tax-years/:id/optimize/roth.
//        The chart and the schedule rows are the optimizer's engine-recomputed
//        trace (conversion size → real tax cost, with marginal-at-step). Headline
//        figures (recommended conversion, tax cost, effective rate, bracket
//        ceiling, IRMAA warning) are real optimizer output.
//
// [additive] Lifetime NPV (the multi-year projection column) genuinely has no
//        endpoint yet — that one row stays honestly "awaiting endpoint". The Roth
//        engine returns a single-year bracket-fill (one recommended conversion +
//        a cost trace over conversion SIZE), NOT a multi-year calendar ladder, so
//        the schedule is labeled as fill increments, not calendar years.
//
// CRITICAL: Baseline is immutable. Zero recomputed numbers are presented as
// engine output unless they came from one of the endpoints above; everything
// else is from the real snapshot or honestly labeled additive.

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  PositionInstrument,
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Money,
  Aavatar,
  Omnibar,
  hueForClient,
  type Segment,
  type Pin,
} from "@/components/kit";
import {
  EMRTerrain,
  CrossoverChart,
  ChartLegend,
} from "@/components/kit";

/* ---- the slices of the live API this surface reads ---- */
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
interface IrmaaSection {
  available: true;
  tier: string;
  total_irmaa_annual_cents: number;
  next_cliff_threshold_cents: number;
  distance_to_next_cliff_cents: number;
  cliff_cost_annual_cents: number;
}
type Maybe<T> = T | { available: false; reason?: string };
interface Analysis {
  filing_status: string;
  irmaa: Maybe<IrmaaSection>;
}

/* ---- live engine endpoint response shapes (POST) ----
 * Every figure below is real engine recompute output. Rates arrive as the
 * engine's Decimal serialized to a string (e.g. "0.338"); render as %. */
interface ScenarioRecomputeOut {
  base_total_tax_cents: number;
  scenario_total_tax_cents: number;
  tax_delta_cents: number; // scenario − base (negative = savings)
  agi_delta_cents: number;
  taxable_income_delta_cents: number;
  marginal_rate_base: string;
  marginal_rate_scenario: string;
  savings: boolean;
}
interface EMRPoint {
  income_cents: number;
  total_tax_cents: number;
  marginal_rate: string; // effective marginal = Δtax/Δincome at this step
}
interface CliffOverlay {
  label: string;
  threshold_cents: number;
  kind: string; // "irmaa" | "niit" | …
}
interface EMRSweepOut {
  field: string;
  base_income_cents: number;
  points: EMRPoint[];
  true_next_dollar_rate: string;
  nominal_marginal_rate: string;
  cliff_overlays: CliffOverlay[];
}
interface RothTraceStep {
  conversion_cents: number;
  tax_cost_cents: number;
  marginal_at_step: string;
}
interface RothOptimizeOut {
  recommended_conversion_cents: number;
  tax_cost_cents: number;
  effective_rate_on_conversion: string;
  bracket_ceiling_cents: number | null;
  irmaa_warning: string | null;
  trace: RothTraceStep[];
}

// A scenario ledger column. The Baseline column comes from the real snapshot;
// the single live conversion column is fed by the scenario endpoint (real).
interface ScenarioCol {
  id: string;
  label: string;
  isBaseline: boolean;
  agiCents: number;
  taxableIncomeCents: number;
  federalTaxCents: number;
  medicareAnnualCents: number | null; // null = not applicable / not modeled
  scenarioMarginalPct: number | null; // engine marginal_rate_scenario (× 100)
}

// ---- helpers ----

function fmt(cents: number | null): string {
  if (cents === null) return "—";
  return (cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function pctFmt(pct: number | null): string {
  if (pct === null) return "—";
  return `${pct.toFixed(1)}%`;
}

/** Decimal-string rate ("0.338") → percent number (33.8). */
function ratePct(rate: string | number | null | undefined): number | null {
  if (rate === null || rate === undefined) return null;
  const n = typeof rate === "string" ? Number(rate) : rate;
  if (!Number.isFinite(n)) return null;
  return n * 100;
}

// ---- Statutory EMR points (REAL — from bracket rows) ------------------------
// The dashed statutory-bracket line behind the terrain. Derived from the real
// bracket-set rows; the terrain curve itself is now the real engine sweep.

function buildStatutoryPoints(
  rows: BracketRow[],
  baseIncomeCents: number,
  sweepDollars = 100_000,
): { incomeCents: number; ratePct: number }[] {
  if (rows.length === 0) return [];
  const sorted = [...rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents);
  const pts: { incomeCents: number; ratePct: number }[] = [];
  const endCents = baseIncomeCents + sweepDollars * 100;

  let prev = 0;
  for (const row of sorted) {
    const rate = Number(row.rate) * 100;
    const lower = row.lower_bound_cents;
    const upper = row.upper_bound_cents ?? endCents;

    // Add a point at the bracket edge (the step)
    if (lower >= baseIncomeCents && lower <= endCents) {
      if (pts.length > 0) pts.push({ incomeCents: lower, ratePct: prev }); // step-down from prev bracket
      pts.push({ incomeCents: lower, ratePct: rate }); // step-up to this bracket
    } else if (lower < baseIncomeCents && upper > baseIncomeCents) {
      // The bracket we start in
      if (pts.length === 0) pts.push({ incomeCents: baseIncomeCents, ratePct: rate });
    }

    if (upper >= endCents) {
      pts.push({ incomeCents: endCents, ratePct: rate });
      break;
    }
    prev = rate;
  }
  if (pts.length === 0) {
    // fallback: use the last bracket rate
    const lastRate = sorted[sorted.length - 1];
    const rate = Number(lastRate.rate) * 100;
    pts.push({ incomeCents: baseIncomeCents, ratePct: rate });
    pts.push({ incomeCents: endCents, ratePct: rate });
  }
  return pts;
}

// ---- the drag handle (conversion instrument) --------------------------------
// The handle renders at the agent-recommended or user-dragged position. Moving
// it sizes the conversion; on release the scenario endpoint recomputes the real
// before/after through the engine. Baseline is never mutated.

function pctOfRange(valueCents: number, minCents: number, maxCents: number): number {
  return Math.max(0, Math.min(100, ((valueCents - minCents) / Math.max(1, maxCents - minCents)) * 100));
}

// ============================================================ THE PAGE ========

export default function LabPage() {
  const { clientId, overview, loading } = useClientOverview();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [aLoading, setALoading] = useState(true);

  // The conversion handle position (in cents above current taxable income).
  // Starts at 0 — the optimizer's recommendation seeds it once optimize/roth
  // returns (real headroom), and the user can drag from there.
  const [convOffsetCents, setConvOffsetCents] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

  // Live engine results (lazy POSTs).
  const [scenario, setScenario] = useState<ScenarioRecomputeOut | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  const [scenarioError, setScenarioError] = useState(false);

  const [emr, setEmr] = useState<EMRSweepOut | null>(null);
  const [emrBusy, setEmrBusy] = useState(false);
  const [emrError, setEmrError] = useState(false);

  const [roth, setRoth] = useState<RothOptimizeOut | null>(null);
  const [rothBusy, setRothBusy] = useState(false);
  const [rothError, setRothError] = useState(false);
  const rothSeeded = useRef(false);

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);
  const taxYearId = planYear?.id ?? null;

  useEffect(() => {
    api.get("/admin/tax-bracket-sets").then((r) => setSets(r.data)).catch(() => setSets([]));
  }, []);
  useEffect(() => {
    if (!taxYearId) { setALoading(false); return; }
    setALoading(true);
    api.get(`/clients/tax-years/${taxYearId}/analysis`)
      .then((r) => setAnalysis(r.data))
      .catch(() => setAnalysis(null))
      .finally(() => setALoading(false));
  }, [taxYearId]);

  const snap = planYear?.snapshot;
  const hue = hueForClient(clientId);

  /* ---- EMR sweep (real engine) — on mount once the tax year is known ---- */
  useEffect(() => {
    if (!taxYearId) return;
    let cancelled = false;
    setEmrBusy(true);
    setEmrError(false);
    // Sweep wages upward ~+$100k in $2,500 steps for a smooth terrain.
    api.post(`/agents/clients/tax-years/${taxYearId}/emr-sweep`, {
      field: "wages_cents",
      step_cents: 250_000,
      steps: 40,
    })
      .then((r) => { if (!cancelled) setEmr(r.data); })
      .catch(() => { if (!cancelled) { setEmr(null); setEmrError(true); } })
      .finally(() => { if (!cancelled) setEmrBusy(false); });
    return () => { cancelled = true; };
  }, [taxYearId]);

  /* ---- Roth optimizer (real engine) — on mount; seeds the handle once ---- */
  useEffect(() => {
    if (!taxYearId) return;
    let cancelled = false;
    setRothBusy(true);
    setRothError(false);
    api.post(`/agents/clients/tax-years/${taxYearId}/optimize/roth`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data as RothOptimizeOut;
        setRoth(data);
        // Seed the conversion handle at the optimizer's recommendation once.
        if (!rothSeeded.current && data.recommended_conversion_cents > 0) {
          rothSeeded.current = true;
          setConvOffsetCents(data.recommended_conversion_cents);
        }
      })
      .catch(() => { if (!cancelled) { setRoth(null); setRothError(true); } })
      .finally(() => { if (!cancelled) setRothBusy(false); });
    return () => { cancelled = true; };
  }, [taxYearId]);

  /* ---- the Position segments: REAL bracket spans for this year + status ---- */
  const { segments, irmaaPin, irmaaCliffCents, fedRows } = useMemo(() => {
    const empty = { segments: [] as Segment[], irmaaPin: null as Pin | null, irmaaCliffCents: null as number | null, fedRows: [] as BracketRow[] };
    if (!sets || !planYear || !snap) return empty;
    const fed = sets.filter((s) => s.jurisdiction?.toLowerCase().includes("fed"));
    const pool = fed.length ? fed : sets;
    const set =
      pool.find((s) => s.tax_year === planYear.tax_year && s.filing_status === planYear.filing_status) ??
      pool.find((s) => s.filing_status === planYear.filing_status) ??
      pool[0];
    if (!set) return empty;
    const rows = [...set.rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents);
    const topLower = rows[rows.length - 1]?.lower_bound_cents ?? 0;
    const income = snap.taxable_income_cents;
    const cap = Math.max(Math.round(topLower * 1.1), Math.round(income * 1.3), topLower + 5_000_00);
    const segments: Segment[] = rows.map((r, i) => ({
      rate: Number(r.rate),
      fromCents: r.lower_bound_cents,
      toCents: r.upper_bound_cents ?? (i === rows.length - 1 ? cap : r.lower_bound_cents),
    }));

    const ir = analysis?.irmaa;
    let irmaaPin: Pin | null = null;
    let irmaaCliffCents: number | null = null;
    if (ir && ir.available && ir.next_cliff_threshold_cents > 0) {
      irmaaPin = { atCents: ir.next_cliff_threshold_cents, label: `IRMAA t${ir.tier} · MAGI $${Math.round(ir.next_cliff_threshold_cents / 100 / 1000)}k` };
      irmaaCliffCents = ir.next_cliff_threshold_cents;
    }
    return { segments, irmaaPin, irmaaCliffCents, fedRows: rows };
  }, [sets, planYear, snap, analysis]);

  /* ---- cap for the conversion handle: IRMAA cliff or next bracket edge ---- */
  const convCapCents = useMemo(() => {
    if (!snap) return 73_550_00;
    const irmaaDistance = irmaaCliffCents != null
      ? irmaaCliffCents - snap.taxable_income_cents
      : null;
    // Cap is the lesser of: IRMAA cliff distance OR next bracket room OR $100k
    const nextBracketRoom = (() => {
      const nextSeg = segments.find((s) => s.fromCents > snap.taxable_income_cents);
      return nextSeg ? nextSeg.fromCents - snap.taxable_income_cents : 100_000_00;
    })();
    return Math.min(
      irmaaDistance ?? 100_000_00,
      nextBracketRoom,
      100_000_00,
    );
  }, [snap, irmaaCliffCents, segments]);

  /* ---- the real scenario recompute, debounced on handle settle ---- */
  const recomputeScenario = useCallback((offsetCents: number) => {
    if (!taxYearId) return;
    if (offsetCents <= 0) {
      // Nothing to convert — clear to baseline, no engine call.
      setScenario(null);
      setScenarioBusy(false);
      setScenarioError(false);
      return;
    }
    setScenarioBusy(true);
    setScenarioError(false);
    api.post(`/agents/clients/tax-years/${taxYearId}/scenario`, {
      delta_fields: { ira_taxable_cents: offsetCents },
    })
      .then((r) => setScenario(r.data))
      .catch(() => { setScenario(null); setScenarioError(true); })
      .finally(() => setScenarioBusy(false));
  }, [taxYearId]);

  // Debounce the recompute: fire ~350ms after the handle stops moving (so a drag
  // doesn't hammer the engine), and immediately on release.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!taxYearId) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    // While actively dragging, wait for a pause; otherwise recompute promptly.
    const delay = isDragging ? 350 : 120;
    debounceRef.current = setTimeout(() => recomputeScenario(convOffsetCents), delay);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [convOffsetCents, isDragging, taxYearId, recomputeScenario]);

  /* ---- drag math for the conversion handle ---- */
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const track = trackRef.current;
      if (!track || !snap) return;
      const rect = track.getBoundingClientRect();
      const fracAlongTrack = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const axisMin = segments[0]?.fromCents ?? 0;
      const axisMax = segments[segments.length - 1]?.toCents ?? axisMin + 1;
      const hoveredCents = axisMin + fracAlongTrack * (axisMax - axisMin);
      const newOffset = Math.max(0, Math.min(convCapCents, hoveredCents - snap.taxable_income_cents));
      setConvOffsetCents(Math.round(newOffset / 1_00) * 1_00); // snap to $1
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [isDragging, snap, segments, convCapCents]);

  /* ---- scenario ledger columns: Baseline (real snapshot) + live conversion ---- */
  const scenarios: ScenarioCol[] = useMemo(() => {
    if (!snap) return [];
    const ir = analysis?.irmaa;
    const irmaaLive = ir && ir.available ? ir : null;
    const baseline: ScenarioCol = {
      id: "baseline",
      label: "Baseline ⚿",
      isBaseline: true,
      agiCents: snap.agi_cents,
      taxableIncomeCents: snap.taxable_income_cents,
      federalTaxCents: snap.total_tax_cents,
      medicareAnnualCents: irmaaLive ? irmaaLive.total_irmaa_annual_cents : null,
      scenarioMarginalPct: ratePct(snap.marginal_rate),
    };
    if (convOffsetCents <= 0 || !scenario) return [baseline];
    // The live conversion column — every figure is real engine output (deltas
    // applied to the real baseline). IRMAA premium is left unmodeled here (the
    // binding-limit chip shows the real cliff cost separately).
    const conv: ScenarioCol = {
      id: "conv-live",
      label: `Convert ${centsToUSD(convOffsetCents)}`,
      isBaseline: false,
      agiCents: snap.agi_cents + scenario.agi_delta_cents,
      taxableIncomeCents: snap.taxable_income_cents + scenario.taxable_income_delta_cents,
      federalTaxCents: scenario.scenario_total_tax_cents,
      medicareAnnualCents: null,
      scenarioMarginalPct: ratePct(scenario.marginal_rate_scenario),
    };
    return [baseline, conv];
  }, [snap, analysis, convOffsetCents, scenario]);

  const statutoryPoints = useMemo(() => {
    if (!snap || fedRows.length === 0) return [];
    return buildStatutoryPoints(fedRows, snap.taxable_income_cents, 100_000);
  }, [snap, fedRows]);

  /* ---- EMR terrain points (real engine sweep) ---- */
  const emrPoints = useMemo(() => {
    if (!emr) return [];
    return emr.points
      .map((p) => ({ incomeCents: p.income_cents, ratePct: ratePct(p.marginal_rate) }))
      .filter((p): p is { incomeCents: number; ratePct: number } => p.ratePct !== null)
      .map((p) => ({ incomeCents: p.incomeCents, ratePct: p.ratePct / 100 })); // EMRTerrain wants a fraction
  }, [emr]);

  // Cliff overlays → vertical dashed threshold lines on the terrain (real
  // threshold income only; no fabricated cost). Keep only the ones inside the
  // swept income window so they actually land on the chart.
  const emrSpikes = useMemo(() => {
    if (!emr || emr.points.length === 0) return undefined;
    const lo = emr.points[0].income_cents;
    const hi = emr.points[emr.points.length - 1].income_cents;
    const inside = emr.cliff_overlays.filter((c) => c.threshold_cents >= lo && c.threshold_cents <= hi);
    if (inside.length === 0) return undefined;
    return inside.map((c) => ({ incomeCents: c.threshold_cents, label: c.label }));
  }, [emr]);

  const trueNextDollarPct = useMemo(() => (emr ? ratePct(emr.true_next_dollar_rate) : null), [emr]);
  const nominalMarginalPct = useMemo(() => (emr ? ratePct(emr.nominal_marginal_rate) : null), [emr]);

  /* ---- Roth crossover series (real optimizer trace) ---- */
  // The trace sweeps the conversion SIZE from $0 to the recommended headroom and
  // recomputes the real incremental tax cost at each step. We plot tax cost vs
  // conversion size; CrossoverChart's numeric axis is the conversion amount in
  // whole dollars (not a calendar year — the engine returns a single-year fill).
  const rothCrossover = useMemo(() => {
    if (!roth || roth.trace.length < 2) return null;
    const points = roth.trace.map((t) => ({
      year: Math.round(t.conversion_cents / 100), // numeric axis = conversion $
      cents: t.tax_cost_cents,
    }));
    const last = roth.trace[roth.trace.length - 1];
    return {
      series: [
        { label: "tax cost of the fill", tone: "cost" as const, points },
      ],
      crossoverLabel: `cost at recommended = ${centsToUSD(last.tax_cost_cents)}`,
    };
  }, [roth]);

  // The fill schedule rows = the real trace increments (skip the $0 step).
  const rothSchedule = useMemo(() => {
    if (!roth) return [];
    return roth.trace.filter((t) => t.conversion_cents > 0);
  }, [roth]);

  // ---- the conversion handle position in % along the track ----
  const handlePct = useMemo(() => {
    if (!snap || segments.length === 0) return 55;
    const axisMin = segments[0].fromCents;
    const axisMax = segments[segments.length - 1].toCents;
    return pctOfRange(snap.taxable_income_cents + convOffsetCents, axisMin, axisMax);
  }, [snap, segments, convOffsetCents]);

  const nowPct = useMemo(() => {
    if (!snap || segments.length === 0) return 55;
    const axisMin = segments[0].fromCents;
    const axisMax = segments[segments.length - 1].toCents;
    return pctOfRange(snap.taxable_income_cents, axisMin, axisMax);
  }, [snap, segments]);

  // ---- the pins for the Position instrument ----
  const positionPins: Pin[] = useMemo(() => {
    const pins: Pin[] = [];
    if (irmaaPin) pins.push(irmaaPin);
    const nextBracket = segments.find((s) => s.fromCents > (snap?.taxable_income_cents ?? 0));
    if (nextBracket) pins.push({ atCents: nextBracket.fromCents, label: `${Math.round(nextBracket.rate * 100)}% edge`, soft: true });
    return pins;
  }, [irmaaPin, segments, snap]);

  // ---- whether the live conversion crosses the IRMAA cliff (real analysis) ----
  const crossesIrmaa = useMemo(() => {
    if (!snap || irmaaCliffCents == null) return false;
    return snap.taxable_income_cents + convOffsetCents > irmaaCliffCents;
  }, [snap, irmaaCliffCents, convOffsetCents]);

  // ---- loading / empty states ----
  if (loading || aLoading) {
    return <div className="wrap py-7"><div className="skeleton h-[600px] w-full rounded-[14px]" /></div>;
  }
  if (!overview || !planYear || !snap) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No confirmed tax year yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            Import and confirm a return on the Return surface to open the Lab.
          </p>
        </Panel>
      </div>
    );
  }

  const ir = analysis?.irmaa;
  const irmaaLive = ir && ir.available ? ir : null;

  return (
    <div className="wrap py-7 pb-20" style={{ "--chue": hue } as React.CSSProperties}>

      {/* ---- lab header: scenario bank ---- */}
      <section className="rise flex flex-wrap items-center gap-3.5">
        <h1 className="text-[30px] font-[750] tracking-[-0.02em]">The Lab</h1>
        <Annotation className="!text-[13.5px]">
          the strata is the control — drag to size a conversion
        </Annotation>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Chip>⚿ Baseline {planYear.tax_year} <em style={{ color: "var(--g-ink-3)", fontStyle: "normal" }}>— immutable</em></Chip>
          {roth && roth.recommended_conversion_cents > 0 ? (
            <Chip tone="save">Roth rec — {centsToUSD(roth.recommended_conversion_cents)}</Chip>
          ) : null}
          <Chip>＋ scenario</Chip>
        </div>
      </section>

      {/* ===== THE CONVERSION INSTRUMENT ===== */}
      <Panel className="rise d1 relative mt-5 px-7 pb-7 pt-6">
        <div className="mb-12 flex flex-wrap items-baseline gap-3.5">
          <MicroLabel>Roth conversion · drag to size — the chart is the control</MicroLabel>
          <Annotation className="!text-[13.5px]">
            live — each move recomputes through the federal engine on release
          </Annotation>
          <span className="ml-auto flex items-center gap-2">
            {scenarioBusy ? (
              <Chip tone="neutral">recomputing…</Chip>
            ) : null}
            <Chip tone="save">conversion {centsToUSD(convOffsetCents)}</Chip>
          </span>
        </div>

        {/* The position instrument (hero variant, from real bracket data) */}
        {segments.length > 0 ? (
          <div className="relative" ref={trackRef}>
            <PositionInstrument
              segments={segments}
              incomeCents={snap.taxable_income_cents}
              nowLabel={<>taxable {centsToUSD(snap.taxable_income_cents)}</>}
              pins={positionPins}
              variant="hero"
            />
            {/* Conversion fill overlay (positioned over the instrument) */}
            <div
              aria-hidden
              className="pointer-events-none absolute"
              style={{
                top: 0,
                bottom: 28, // leave room for the axis area
                left: `${nowPct}%`,
                width: `${handlePct - nowPct}%`,
                background: "repeating-linear-gradient(135deg,rgba(29,138,91,0.34) 0 7px,rgba(29,138,91,0.12) 7px 14px)",
                borderLeft: "2px solid var(--save)",
                zIndex: 2,
              }}
            />
            {/* Drag handle */}
            <div
              aria-label={`Conversion handle — ${centsToUSD(convOffsetCents)} — drag to resize`}
              className="absolute -top-3 bottom-7 z-[5] flex cursor-ew-resize items-center"
              style={{ left: `${handlePct}%` }}
              onMouseDown={handleMouseDown}
              role="slider"
              aria-valuenow={convOffsetCents}
              aria-valuemin={0}
              aria-valuemax={convCapCents}
              tabIndex={0}
              onKeyDown={(e) => {
                const step = 1_000_00;
                if (e.key === "ArrowRight") setConvOffsetCents((v) => Math.min(convCapCents, v + step));
                if (e.key === "ArrowLeft") setConvOffsetCents((v) => Math.max(0, v - step));
              }}
            >
              {/* Vertical line */}
              <div className="absolute inset-y-0 left-0 w-[2.5px] bg-[var(--save)]" />
              {/* Grip knob */}
              <div
                className="absolute right-[-11px] top-1/2 -translate-y-1/2 grid h-[30px] w-[20px] place-items-center rounded-[7px] text-[9px] tracking-[1px] text-[#eafff5]"
                style={{ background: "linear-gradient(180deg,#3fb985,#1d8a5b)", boxShadow: "0 3px 12px rgba(29,138,91,0.5)" }}
              >
                ⇔
              </div>
              {/* Amount callout */}
              <div className="absolute right-[-54px] top-[-30px] rounded-[7px] border border-[rgba(29,138,91,0.4)] bg-[rgba(29,138,91,0.1)] px-[9px] py-[3px] font-mono text-[11.5px] text-[var(--save)] whitespace-nowrap">
                +{centsToUSD(convOffsetCents)}
              </div>
            </div>
            <div className="mt-6 flex justify-between font-mono text-[9.5px] text-[var(--g-ink-3)]">
              <span>{centsToUSD(segments[0].fromCents)}</span>
              <span>{planYear.tax_year} {planYear.filing_status} taxable →</span>
              <span>{centsToUSD(segments[segments.length - 1].toCents)}</span>
            </div>
          </div>
        ) : (
          <p className="text-[13px] text-[var(--g-ink-3)]">
            Bracket set unavailable for {planYear.tax_year} {planYear.filing_status}.
          </p>
        )}

        {/* Readout chips — REAL engine output (scenario endpoint) ---- */}
        <div className="mt-9 flex flex-wrap gap-2.5">
          <ReadoutChip
            label="conversion tax"
            value={
              convOffsetCents <= 0
                ? "—"
                : scenarioError
                  ? "couldn't recompute"
                  : scenario
                    ? `+${centsToUSD(Math.abs(scenario.tax_delta_cents))}`
                    : scenarioBusy ? "…" : "—"
            }
          />
          <ReadoutChip
            label="marginal rate at this scenario"
            value={
              convOffsetCents <= 0
                ? "—"
                : scenario
                  ? pctFmt(ratePct(scenario.marginal_rate_scenario))
                  : scenarioBusy ? "…" : "—"
            }
          />
          {/* IRMAA binding limit — from real analysis data */}
          {irmaaLive ? (
            <ReadoutChip
              label={`binding limit · IRMAA tier ${irmaaLive.tier}`}
              value={crossesIrmaa
                ? `⚠ crossed — +${centsToUSD(irmaaLive.cliff_cost_annual_cents)}/yr`
                : `$1 over costs ${centsToUSD(irmaaLive.cliff_cost_annual_cents)}/yr`}
              binding={crossesIrmaa}
            />
          ) : null}
          {/* IRMAA premium-year mapping is informational; the dollar cost is the
              real cliff cost above. The two-year lag is a fact, not a recompute. */}
          {irmaaLive ? (
            <ReadoutChip
              label={`${planYear.tax_year + 2} premiums (${planYear.tax_year} MAGI)`}
              value={crossesIrmaa ? "⬆ tier jumps" : "unchanged ✓"}
            />
          ) : null}
          <Link href={`/c/${clientId}/memo`} className="mini-btn seal self-center ml-auto">
            Snapshot → memo
          </Link>
        </div>

        {/* Honesty note */}
        <div className="mt-4 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2 font-mono text-[10px] text-[var(--g-ink-3)]">
          <span className="tone-save">[live]</span> The conversion tax and scenario marginal above are real engine recomputes via{" "}
          <code>POST /agents/clients/tax-years/:id/scenario</code> ({"delta_fields: ira_taxable_cents"}) — the full fold (SE, QBI, AMT, NIIT)
          runs server-side. The IRMAA cliff cost is the real analysis figure. Baseline is the immutable snapshot. Spec §9.2.
        </div>
      </Panel>

      {/* ===== EMR TERRAIN ===== */}
      <Panel className="rise d2 mt-[22px]">
        <PanelHead>
          <MicroLabel>True marginal terrain · the next $100,000 of ordinary income</MicroLabel>
          <Annotation className="!text-[13px]">
            {nominalMarginalPct !== null
              ? <>the nominal bracket says {nominalMarginalPct.toFixed(0)}% — the terrain shows what the next dollar really costs</>
              : <>what the next dollar really costs, recomputed step by step</>}
          </Annotation>
          <span className="ml-auto flex items-center gap-2">
            {emrBusy ? <Chip tone="neutral">sweeping…</Chip> : null}
            {trueNextDollarPct !== null ? (
              <Chip tone="cost">true next $1 · {trueNextDollarPct.toFixed(1)}%</Chip>
            ) : null}
          </span>
        </PanelHead>
        <div className="px-5 pt-4 pb-2">
          {emrError ? (
            <div className="h-[220px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
              <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Couldn&rsquo;t run the sweep — try reloading.</span>
            </div>
          ) : emrPoints.length >= 2 ? (
            <EMRTerrain
              // statutory dashed line = REAL (from bracket rows)
              statutory={statutoryPoints.map((p) => ({ incomeCents: p.incomeCents, ratePct: p.ratePct / 100 }))}
              // the effective-marginal curve = REAL engine sweep (Δtax/Δincome per step)
              points={emrPoints}
              // cliff threshold lines = REAL overlays (threshold income only)
              spikes={emrSpikes}
              height={240}
            />
          ) : emrBusy ? (
            <div className="h-[220px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
              <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Running the engine sweep…</span>
            </div>
          ) : (
            <div className="h-[220px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
              <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Sweep returned no points.</span>
            </div>
          )}
          <ChartLegend
            className="mt-1 px-0.5"
            items={[
              { label: "statutory bracket steps (real)", tone: "var(--g-ink-3)", dashed: true },
              { label: "true effective marginal — engine sweep", tone: "var(--cliff)" },
            ]}
          />
        </div>
        <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3 font-mono text-[10px] text-[var(--g-ink-3)]">
          <span className="tone-save">[live]</span> Curve = the engine&rsquo;s effective marginal (Δtax / Δincome) per step via{" "}
          <code>POST /agents/clients/tax-years/:id/emr-sweep</code>. Dashed = the bracket table (real). Vertical lines = real cliff
          thresholds (IRMAA / NIIT) — threshold income only; the per-cliff dollar cost is honestly not drawn here.
        </div>
      </Panel>

      {/* ===== SCENARIO LEDGER ===== */}
      <Panel className="rise d3 mt-[22px] overflow-x-auto">
        <PanelHead>
          <MicroLabel>Scenario ledger · baseline-anchored, delta always visible</MicroLabel>
          <span className="ml-auto flex items-center gap-2">
            {scenarioBusy ? <Chip tone="neutral">recomputing…</Chip> : null}
            <Chip>⎙ print: baseline + Δ fits the memo</Chip>
          </span>
        </PanelHead>
        <table className="ledger w-full" style={{ minWidth: 620 }}>
          <thead>
            <tr>
              <th className="px-4 py-2 text-left text-[12px]">{planYear.tax_year}</th>
              {scenarios.map((col) => (
                <th
                  key={col.id}
                  className={`r px-4 py-2 text-right text-[12px] ${col.isBaseline ? "text-[var(--g-ink-2)]" : "text-[var(--save)]"}`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <LedgerRow label="AGI / MAGI" cols={scenarios} field="agiCents" format={(v) => fmt(v)} baseline={scenarios[0]} />
            <LedgerRow label="Taxable income" cols={scenarios} field="taxableIncomeCents" format={(v) => fmt(v)} baseline={scenarios[0]} />
            <LedgerRow
              label="Federal tax"
              cols={scenarios}
              field="federalTaxCents"
              format={(v) => fmt(v)}
              baseline={scenarios[0]}
              deltaIsUnfavorable
            />
            {irmaaLive ? (
              <LedgerRow
                label={
                  <span>
                    {planYear.tax_year + 2} Medicare premiums{" "}
                    <span className="font-mono text-[10px] text-[var(--g-ink-3)]">
                      ({planYear.tax_year} MAGI)
                    </span>
                  </span>
                }
                cols={scenarios}
                field="medicareAnnualCents"
                format={(v) => v !== null ? fmt(v) : "—"}
                baseline={scenarios[0]}
                deltaIsUnfavorable
              />
            ) : null}
            {/* Marginal rate at scenario — engine output (no delta column) */}
            <tr>
              <td className="rowlab px-4 py-2 text-[12px] text-[var(--g-ink-2)]">Marginal rate at scenario</td>
              {scenarios.map((col) => (
                <td key={col.id} className={`r px-4 py-2 text-right fig text-[13px] ${col.scenarioMarginalPct !== null ? (col.scenarioMarginalPct > 30 ? "text-[var(--cliff)]" : "text-[var(--g-ink)]") : "text-[var(--g-ink-3)]"}`}>
                  {pctFmt(col.scenarioMarginalPct)}
                </td>
              ))}
            </tr>
            {/* Lifetime NPV row — genuinely no endpoint yet */}
            <tr>
              <td className="rowlab px-4 py-2 text-[12px] text-[var(--g-ink-2)]">
                Lifetime tax (to {planYear.tax_year + 14}, NPV){" "}
                <span className="font-mono text-[9px] text-[var(--g-ink-3)]">[additive]</span>
              </td>
              {scenarios.map((col) => (
                <td key={col.id} className="r px-4 py-2 text-right fig text-[13px] text-[var(--g-ink-3)]">
                  — <span className="font-mono text-[8.5px]">awaiting endpoint</span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3 text-[12px] text-[var(--g-ink-3)]">
          <span className="font-mono text-[10px] tone-save">[live]</span> Baseline = real snapshot; the conversion column is a real engine
          recompute (<code>POST /agents/clients/tax-years/:id/scenario</code>) — drag the handle to change it. The lifetime-NPV row genuinely
          awaits a multi-year projection endpoint. Parentheses in print; negatives never bare-minus in CPA tables.
        </div>
      </Panel>

      {/* ===== CROSSOVER + FILL SCHEDULE ===== */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.25fr_1fr]">

        {/* Crossover / cost trace — real optimizer */}
        <Panel className="rise d4">
          <PanelHead>
            <MicroLabel>The bracket fill · tax cost as the conversion grows</MicroLabel>
            <span className="ml-auto flex items-center gap-2">
              {rothBusy ? <Chip tone="neutral">optimizing…</Chip> : null}
              {roth?.irmaa_warning ? <span className="text-[11px] text-[var(--cliff)]">{roth.irmaa_warning}</span> : null}
            </span>
          </PanelHead>
          <div className="px-4 pt-4 pb-1">
            {rothError ? (
              <div className="h-[200px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
                <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Couldn&rsquo;t run the optimizer.</span>
              </div>
            ) : rothCrossover ? (
              <>
                <CrossoverChart
                  series={rothCrossover.series}
                  crossoverLabel={rothCrossover.crossoverLabel}
                  height={200}
                />
                <div className="mt-2 flex justify-between font-mono text-[9.5px] text-[var(--g-ink-3)]">
                  <span>$0 converted</span>
                  <span>conversion size →</span>
                  <span>{roth ? centsToUSD(roth.recommended_conversion_cents) : ""}</span>
                </div>
              </>
            ) : rothBusy ? (
              <div className="h-[200px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
                <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Running the optimizer…</span>
              </div>
            ) : (
              <div className="h-[200px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
                <span className="font-mono text-[11px] text-[var(--g-ink-3)]">No headroom to convert at this income.</span>
              </div>
            )}
          </div>
          <ChartLegend
            className="px-4 pb-3"
            items={[
              { label: "tax cost of the fill (engine)", tone: "var(--cost)", dashed: false },
            ]}
          />
          <div className="border-t border-[var(--g-hairline-soft)] px-4 pb-3 pt-2 font-mono text-[9.5px] text-[var(--g-ink-3)]">
            <span className="tone-save">[live]</span> Each point is the real incremental tax cost as the conversion grows, via{" "}
            <code>optimize/roth</code> (single-year bracket fill). The engine returns one recommended conversion + this cost trace —
            not a multi-year calendar projection.
          </div>
        </Panel>

        {/* Fill schedule — real optimizer trace increments */}
        <Panel className="rise d5">
          <PanelHead>
            <MicroLabel>The fill · each increment&rsquo;s real marginal cost</MicroLabel>
            <span className="ml-auto">
              <Chip href={`/c/${clientId}/memo`}>→ Exhibit in memo</Chip>
            </span>
          </PanelHead>
          {rothError ? (
            <div className="px-4 py-6 text-center font-mono text-[11px] text-[var(--g-ink-3)]">Couldn&rsquo;t run the optimizer.</div>
          ) : rothSchedule.length > 0 ? (
            <>
              {rothSchedule.map((row, i) => (
                <RothStepView key={row.conversion_cents} row={row} first={i === 0} />
              ))}
              <div className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-4 py-3 bg-[rgba(29,138,91,0.04)]">
                <span className="w-[42px] font-mono text-[11px] text-[var(--g-ink-3)]">Σ</span>
                <span className="text-[13px]">
                  <b>{roth ? centsToUSD(roth.recommended_conversion_cents) : "—"} recommended</b> at the bracket ceiling
                  <span className="block text-[11px] text-[var(--g-ink-3)]">
                    {roth?.bracket_ceiling_cents != null
                      ? <>fills to {centsToUSD(roth.bracket_ceiling_cents)} taxable · effective {pctFmt(ratePct(roth.effective_rate_on_conversion))} on the conversion</>
                      : <>effective {roth ? pctFmt(ratePct(roth.effective_rate_on_conversion)) : "—"} on the conversion</>}
                  </span>
                </span>
                <Money cents={roth ? roth.tax_cost_cents : 0} tone="cost" signed className="ml-auto text-[14px] font-bold" />
              </div>
            </>
          ) : rothBusy ? (
            <div className="px-4 py-6 text-center font-mono text-[11px] text-[var(--g-ink-3)]">Running the optimizer…</div>
          ) : (
            <div className="px-4 py-6 text-center font-mono text-[11px] text-[var(--g-ink-3)]">No conversion headroom at this income.</div>
          )}
          <div className="border-t border-[var(--g-hairline-soft)] px-4 py-2.5 font-mono text-[9.5px] text-[var(--g-ink-3)]">
            <span className="tone-save">[live]</span> Increments + marginal-at-step from the engine trace (<code>optimize/roth</code>).
            Single-year bracket fill — the schedule is the fill, not a multi-year calendar ladder.
          </div>
        </Panel>
      </div>

      {/* ===== WHAT-IF OMNIBAR ===== */}
      <div className="rise d6 mt-[22px] flex items-center gap-3.5 rounded-[14px] border border-dashed border-[var(--g-hairline)] px-[18px] py-[13px]">
        <Aavatar name="Strategist" agent="strategist" />
        <span className="flex-1 text-[14px] text-[var(--g-ink-3)]">
          What if —{" "}
          <b className="text-[var(--g-ink-2)] font-semibold">&ldquo;defer $40k of income into next year&rdquo;</b>
          <span className="inline-block h-[15px] w-[1.5px] bg-[var(--g-ink-2)] align-[-2px] ml-0.5" />
        </span>
        <span className="font-mono text-[10px] text-[var(--g-ink-3)] hidden md:block">
          mutates inputs · full recompute · lands as a new column
        </span>
      </div>

      <div className="mt-[22px]">
        <Omnibar placeholder="What if — type a mutation or question about this scenario…" />
      </div>

      {/* Spec footer */}
      <footer className="mt-8 flex flex-wrap gap-3.5">
        <span className="font-mono text-[10px] text-[var(--g-ink-3)] rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2">
          № 05 — THE LAB · optimizers as instruments. Live: <code>scenario</code> recompute, <code>emr-sweep</code> terrain,{" "}
          <code>optimize/roth</code> crossover + fill. Baseline is immutable; scenarios are clones. Lifetime-NPV awaits a multi-year
          projection endpoint. Present mode hides every control.
        </span>
      </footer>
    </div>
  );
}

// ---- Local sub-components ----

function ReadoutChip({ label, value, binding }: { label: React.ReactNode; value: React.ReactNode; binding?: boolean }) {
  return (
    <div
      className={`rounded-[10px] border px-3.5 py-2.5 bg-[rgba(31,28,23,0.02)] ${
        binding
          ? "border-[rgba(194,58,82,0.5)] bg-[rgba(194,58,82,0.06)]"
          : "border-[var(--g-hairline)]"
      }`}
    >
      <div className="font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--g-ink-3)]">{label}</div>
      <div className={`mt-0.5 text-[15px] font-bold fig ${binding ? "text-[var(--cliff)]" : ""}`}>{value}</div>
    </div>
  );
}

type ScenarioField = keyof Pick<ScenarioCol, "agiCents" | "taxableIncomeCents" | "federalTaxCents" | "medicareAnnualCents">;

function LedgerRow({
  label,
  cols,
  field,
  format,
  baseline,
  deltaIsUnfavorable,
}: {
  label: React.ReactNode;
  cols: ScenarioCol[];
  field: ScenarioField;
  format: (v: number | null) => string;
  baseline: ScenarioCol;
  deltaIsUnfavorable?: boolean;
}) {
  const baseVal = baseline[field] as number | null;
  return (
    <tr>
      <td className="rowlab px-4 py-2 text-[12px] text-[var(--g-ink-2)]">{label}</td>
      {cols.map((col) => {
        const val = col[field] as number | null;
        const isBase = col.isBaseline;
        const delta = val !== null && baseVal !== null && !isBase ? val - baseVal : null;
        return (
          <td key={col.id} className="r px-4 py-2 text-right fig text-[13px]">
            {format(val)}
            {delta !== null ? (
              <span className={`ml-3 ${
                deltaIsUnfavorable
                  ? (delta > 0 ? "text-[var(--cliff)]" : delta < 0 ? "text-[var(--save)]" : "text-[var(--g-ink-3)]")
                  : (delta < 0 ? "text-[var(--cliff)]" : delta > 0 ? "text-[var(--save)]" : "text-[var(--g-ink-3)]")
              } text-[11px]`}>
                {delta > 0 ? "+" : delta < 0 ? "−" : ""}{fmt(Math.abs(delta))}
              </span>
            ) : null}
          </td>
        );
      })}
    </tr>
  );
}

function RothStepView({ row, first }: { row: RothTraceStep; first: boolean }) {
  const marginal = ratePct(row.marginal_at_step);
  return (
    <div className={`flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-4 py-3 text-[13px] ${first ? "first:border-t-0" : ""}`}>
      <span className="w-[80px] font-mono text-[11px] text-[var(--g-ink-3)]">{centsToUSD(row.conversion_cents)}</span>
      <span>
        cumulative tax cost
        <span className="block text-[11px] text-[var(--g-ink-3)]">
          marginal at this step · {marginal !== null ? `${marginal.toFixed(1)}%` : "—"}
        </span>
      </span>
      <b className="ml-auto fig text-[14px]">{centsToUSD(row.tax_cost_cents)}</b>
    </div>
  );
}
