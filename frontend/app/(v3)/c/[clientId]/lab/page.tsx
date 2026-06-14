"use client";

// Surface 05 — THE LAB (frontier). Scenario bank with an immutable Baseline
// (clones only — enforced data model). The conversion instrument: the strata as
// a CONTROL; the drag handle sizes the conversion, snaps to engine inflection
// points, readout chips (move tax, true rate, binding limit, premium effect with
// year mapping). EMR terrain. Scenario ledger (delta-first). Crossover chart +
// ladder schedule. What-if omnibar.
//
// HONESTY PROTOCOL — what is live vs illustrative (never fabricated):
//
// [live] The Position (PositionInstrument): real bracket sets + real snapshot.
//        The baseline row in the ledger: real snapshot figures.
//        The IRMAA cliff: real analysis.irmaa data.
//        Statutory rate steps for EMRTerrain: derived from real bracket-set rows.
//
// [additive] The conversion drag recompute: expose recompute_scenario as an
//   endpoint. Today the conversion handle renders at a CLEARLY-LABELED illustrative
//   position; move-tax / true-rate-on-move / lifetime NPV columns are labeled
//   illustrative fixtures. INTEGRATION-TODO.05.md.
// [additive] The true EMR sweep: POST /agents/clients/tax-years/:id/emr-sweep.
//   The terrain renders illustrative points (amber); the statutory dashed line
//   is real (bracket table). Labeled.
// [additive] The crossover + ladder schedule: optimize_roth_conversion search
//   trace. The chart and schedule rows are illustrative fixtures for the Cho
//   demo case; a real client sees the "awaiting endpoint" state. Labeled.
//
// CRITICAL: Baseline is immutable. Zero recomputed numbers are presented as
// real engine output — all non-baseline figures are CLEARLY labeled illustrative
// or are from the real snapshot.

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

// ---- illustrative fixture types (never passed as engine output) ----

/** A single scenario column. The Baseline column comes from the real snapshot;
 *  all others are [additive] illustrative until recompute_scenario exists. */
interface ScenarioCol {
  id: string;
  label: string;
  isBaseline: boolean;
  isIllustrative: boolean;
  // These fields are real on the baseline (from snapshot), illustrative on others.
  agiCents: number;
  taxableIncomeCents: number;
  federalTaxCents: number;
  medicareAnnualCents: number | null; // null = not applicable
  trueRatePct: number | null; // null on baseline (additive to show)
  lifetimeTaxNpvCents: number | null; // null = additive
}

/** One year of the ladder schedule (illustrative until optimize_roth_conversion). */
interface LadderRow {
  year: number;
  note: string;
  cap: string;
  amountCents: number;
  isIllustrative: true;
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

// ---- Illustrative fixture builder -------------------------------------------
// These are NOT engine output. They are labeled ILLUSTRATIVE to show the surface
// shape. They use the real baseline numbers where available, and extend the Cho
// demo narrative (MAGI $391,600, taxable $330,400 — §8 demo cast).
// TODO(integration: POST /clients/tax-years/:id/scenarios/recompute) — when this
//   endpoint lands, replace these with real recomputed values.

function buildIllustrativeScenarios(
  baselineSnap: {
    agiCents: number;
    taxableIncomeCents: number;
    federalTaxCents: number;
  },
  irmaa: IrmaaSection | null,
): ScenarioCol[] {
  const baseline: ScenarioCol = {
    id: "baseline",
    label: "Baseline ⚿",
    isBaseline: true,
    isIllustrative: false, // baseline figures ARE the real snapshot
    agiCents: baselineSnap.agiCents,
    taxableIncomeCents: baselineSnap.taxableIncomeCents,
    federalTaxCents: baselineSnap.federalTaxCents,
    medicareAnnualCents: irmaa ? irmaa.total_irmaa_annual_cents : null,
    trueRatePct: null, // EMR additive
    lifetimeTaxNpvCents: null, // additive — lifetime NPV needs optimizer
  };

  // Illustrative scenario A: $18,400 conversion (IRMAA-capped)
  // All non-baseline figures are illustrative — the endpoint does not exist yet.
  const convA: ScenarioCol = {
    id: "conv-18400",
    label: "Convert $18,400 ◀ rec",
    isBaseline: false,
    isIllustrative: true,
    agiCents: baselineSnap.agiCents + 18_400_00,
    taxableIncomeCents: baselineSnap.taxableIncomeCents + 18_400_00,
    federalTaxCents: baselineSnap.federalTaxCents + 4_674_00,
    medicareAnnualCents: irmaa ? irmaa.total_irmaa_annual_cents : null, // unchanged — stays below cliff
    trueRatePct: 25.4,
    lifetimeTaxNpvCents: null, // lifetime NPV additive
  };

  // Illustrative scenario B: $73,550 conversion (crosses IRMAA cliff)
  const convB: ScenarioCol = {
    id: "conv-73550",
    label: "Convert $73,550",
    isBaseline: false,
    isIllustrative: true,
    agiCents: baselineSnap.agiCents + 73_550_00,
    taxableIncomeCents: baselineSnap.taxableIncomeCents + 73_550_00,
    federalTaxCents: baselineSnap.federalTaxCents + 19_655_00,
    medicareAnnualCents: irmaa ? irmaa.total_irmaa_annual_cents + irmaa.cliff_cost_annual_cents : null,
    trueRatePct: 31.4,
    lifetimeTaxNpvCents: null, // additive
  };

  return [baseline, convA, convB];
}

// ---- Statutory EMR points (REAL — from bracket rows) ------------------------
// These are the dashed statutory-bracket line on the terrain; the amber true-EMR
// curve is [additive]. We derive these from the real bracket set rows.

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

// ---- Illustrative EMR curve (labeled — not engine output) -------------------
// TODO(integration: POST /agents/clients/tax-years/:id/emr-sweep) — when this
//   endpoint lands, replace with the engine sweep at $500 income steps.
// The SS phase-in ripple + IRMAA spike shapes mirror the Cho §8 demo narrative.

function buildIllustrativeEMR(
  baseIncomeCents: number,
  irmaaCliffCents: number | null,
): { incomeCents: number; ratePct: number }[] {
  // Illustrative only — never presented as engine recompute output.
  const pts: { incomeCents: number; ratePct: number }[] = [];
  const end = baseIncomeCents + 100_000_00;
  const irmaaOffset = irmaaCliffCents != null ? irmaaCliffCents - baseIncomeCents : 18_500_00;
  const step32Offset = 73_550_00; // illustrative: 32% bracket edge offset

  // Base 24% — before any cliff
  pts.push({ incomeCents: baseIncomeCents, ratePct: 24 });
  // SS taxability ripple ~$6k wide, ~+3.5%
  const ssStart = Math.min(6_000_00, irmaaOffset - 5_000_00);
  if (ssStart > 0) {
    pts.push({ incomeCents: baseIncomeCents + ssStart, ratePct: 24 });
    pts.push({ incomeCents: baseIncomeCents + ssStart + 1_000_00, ratePct: 27.5 });
    pts.push({ incomeCents: baseIncomeCents + ssStart + 3_000_00, ratePct: 27.5 });
    pts.push({ incomeCents: baseIncomeCents + ssStart + 4_000_00, ratePct: 24 });
  }
  // IRMAA cliff spike — effective rate shoots very high for 1 dollar
  if (irmaaOffset > 0 && irmaaOffset < 100_000_00) {
    pts.push({ incomeCents: baseIncomeCents + irmaaOffset - 100, ratePct: 24 });
    pts.push({ incomeCents: baseIncomeCents + irmaaOffset, ratePct: 65 }); // spike (illustrative)
    pts.push({ incomeCents: baseIncomeCents + irmaaOffset + 100, ratePct: 24 }); // returns to base
  }
  // Resume at 24% until 32% edge
  pts.push({ incomeCents: baseIncomeCents + Math.min(step32Offset - 500_00, 100_000_00), ratePct: 24 });
  if (step32Offset < 100_000_00) {
    pts.push({ incomeCents: baseIncomeCents + step32Offset, ratePct: 24 });
    pts.push({ incomeCents: baseIncomeCents + step32Offset + 100, ratePct: 32 });
    pts.push({ incomeCents: end, ratePct: 32 });
  } else {
    pts.push({ incomeCents: end, ratePct: 24 });
  }
  return pts;
}

// ---- Illustrative crossover series (labeled) --------------------------------
// TODO(integration: POST /agents/clients/tax-years/:id/optimize-roth-conversion)
//   When this endpoint lands, replace with the optimizer search trace.

function buildIllustrativeCrossover(baseYear: number): {
  series: { label: string; tone: "save" | "cost" | "ink"; points: { year: number; cents: number }[] }[];
  crossoverLabel: string;
} {
  const years = [baseYear, baseYear + 1, baseYear + 2, baseYear + 3, baseYear + 4,
    baseYear + 5, baseYear + 6, baseYear + 7, baseYear + 8, baseYear + 9, baseYear + 10,
    baseYear + 11, baseYear + 12, baseYear + 13, baseYear + 14];

  // "Do nothing" — tax grows as RMDs kick in ~year 8 (2034 in the Cho narrative)
  const doNothing = years.map((yr, i) => {
    const base = 6_192_000; // baseline cumulative ~$61,920/yr
    const rmdRamp = i > 7 ? (i - 7) * 800_000 : 0; // RMDs steepen after 2034
    return { year: yr, cents: base * (i + 1) + rmdRamp };
  });

  // Ladder — higher early (conversion tax), then flattens because RMDs are smaller
  const ladder = years.map((yr, i) => {
    const base = 6_192_000;
    const earlyBump = i < 3 ? (i + 1) * 467_400 : 3 * 467_400; // conversion taxes 2026-2028
    const rmdSaving = i > 7 ? (i - 7) * 300_000 : 0; // Roth grows tax-free → smaller RMDs
    return { year: yr, cents: base * (i + 1) + earlyBump - rmdSaving };
  });

  return {
    series: [
      { label: "do nothing", tone: "ink" as const, points: doNothing },
      { label: "conversion ladder", tone: "save" as const, points: ladder },
    ],
    crossoverLabel: "gap at 2040 = $112,400 (illustrative)",
  };
}

// ---- Illustrative ladder schedule (labeled) ---------------------------------
const ILLUSTRATIVE_LADDER: LadderRow[] = [
  { year: 2026, note: "while Evelyn still earns", cap: "cap: IRMAA tier 4 at $410k MAGI", amountCents: 18_400_00, isIllustrative: true },
  { year: 2027, note: "Evelyn retires in June", cap: "cap: IRMAA tier 3 — lower MAGI base", amountCents: 52_000_00, isIllustrative: true },
  { year: 2028, note: "first full valley year", cap: "cap: top of 24% — IRMAA clear", amountCents: 74_000_00, isIllustrative: true },
];
const ILLUSTRATIVE_LADDER_TOTAL_CENTS = 144_400_00;
const ILLUSTRATIVE_LIFETIME_SAVING_CENTS = 112_400_00;

// ---- the drag handle (conversion instrument) --------------------------------
// The handle renders at the agent-recommended or user-dragged position.
// Dragging is OPTIMISTIC: in v1, moving the handle updates an [illustrative]
// conversion amount and the readout chips update accordingly. When
// recompute_scenario lands, the handle triggers a real recompute.
// TODO(integration: POST /clients/tax-years/:id/scenarios/recompute)

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
  // Starts at the illustrative-optimal $18,400 for the Cho demo case.
  // [additive]: a real client would start at 0 until the optimizer runs.
  const [convOffsetCents, setConvOffsetCents] = useState(18_400_00);
  const [isDragging, setIsDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

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
    // Cap is the lesser of: IRMAA cliff distance OR 32% bracket room OR $100k
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

  /* ---- illustrative data built from real snapshot + fixtures ---- */
  const scenarios = useMemo(() => {
    if (!snap) return [];
    const ir = analysis?.irmaa;
    const irmaaLive = ir && ir.available ? ir : null;
    return buildIllustrativeScenarios(
      { agiCents: snap.agi_cents, taxableIncomeCents: snap.taxable_income_cents, federalTaxCents: snap.total_tax_cents },
      irmaaLive,
    );
  }, [snap, analysis]);

  const statutoryPoints = useMemo(() => {
    if (!snap || fedRows.length === 0) return [];
    return buildStatutoryPoints(fedRows, snap.taxable_income_cents, 100_000);
  }, [snap, fedRows]);

  const illustrativeEMR = useMemo(() => {
    if (!snap) return [];
    return buildIllustrativeEMR(snap.taxable_income_cents, irmaaCliffCents);
  }, [snap, irmaaCliffCents]);

  const crossoverData = useMemo(() => {
    return buildIllustrativeCrossover(planYear?.tax_year ?? 2026);
  }, [planYear]);

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

  // ---- the illustrative readout for the conversion handle ----
  // [additive] These are CLEARLY-LABELED illustrative estimates — NOT engine output.
  // They are proportional to the bracket rate at the handle position, but the
  // IRMAA effect, the true marginal, and the IRMAA year-mapping are illustrative
  // until recompute_scenario exists.
  // TODO(integration: POST /clients/tax-years/:id/scenarios/recompute)
  const convReadout = useMemo(() => {
    if (!snap) return null;
    const bracketAtHandle = segments.find(
      (s) => snap.taxable_income_cents + convOffsetCents >= s.fromCents &&
             snap.taxable_income_cents + convOffsetCents < s.toCents,
    ) ?? segments.find((s) => s.fromCents > snap.taxable_income_cents);
    const bracketRate = bracketAtHandle ? bracketAtHandle.rate : Number(snap.marginal_rate);
    const illustrativeTax = Math.round(convOffsetCents * bracketRate);
    const illustrativeRate = bracketRate * 100;
    const crossesIrmaa = irmaaCliffCents != null &&
      snap.taxable_income_cents + convOffsetCents > irmaaCliffCents;
    return { illustrativeTax, illustrativeRate, crossesIrmaa };
  }, [snap, segments, convOffsetCents, irmaaCliffCents]);

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
          <Chip tone="cost">Roth ladder — illustrative</Chip>
          <Chip>＋ scenario</Chip>
        </div>
      </section>

      {/* ===== THE CONVERSION INSTRUMENT ===== */}
      <Panel className="rise d1 relative mt-5 px-7 pb-7 pt-6">
        <div className="mb-12 flex flex-wrap items-baseline gap-3.5">
          <MicroLabel>Roth conversion · drag to size — the chart is the control</MicroLabel>
          <Annotation className="!text-[13.5px]">
            illustrative — live recompute + the optimizer land with the scenario endpoint
          </Annotation>
          <span className="ml-auto">
            <Chip tone="cost">illustrative: {centsToUSD(convOffsetCents)} · seeded</Chip>
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
            {/* Conversion fill overlay (illustrative — positioned over the instrument) */}
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

        {/* Readout chips — ILLUSTRATIVE until recompute_scenario endpoint exists */}
        <div className="mt-9 flex flex-wrap gap-2.5">
          {/* conversion tax chip — illustrative, not engine output */}
          <ReadoutChip
            label="conversion tax (illustrative)"
            value={convReadout ? `+${centsToUSD(convReadout.illustrativeTax)}` : "—"}
          />
          <ReadoutChip
            label="effective rate on this move (illustrative)"
            value={convReadout ? `${convReadout.illustrativeRate.toFixed(1)}%` : "—"}
          />
          {/* IRMAA binding limit — from real analysis data */}
          {irmaaLive ? (
            <ReadoutChip
              label={`binding limit · IRMAA tier ${irmaaLive.tier}`}
              value={convReadout?.crossesIrmaa
                ? `⚠ crossed — +${centsToUSD(irmaaLive.cliff_cost_annual_cents)}/yr`
                : `$1 over costs ${centsToUSD(irmaaLive.cliff_cost_annual_cents)}/yr`}
              binding={!!convReadout?.crossesIrmaa}
            />
          ) : null}
          {irmaaLive ? (
            <ReadoutChip
              label={`${planYear.tax_year + 2} premiums (${planYear.tax_year} MAGI · both enrolled) (illustrative)`}
              value={convReadout?.crossesIrmaa ? "⬆ tier jumps" : "unchanged ✓"}
            />
          ) : null}
          <ReadoutChip
            label="vs converting later at (illustrative)"
            value={convReadout ? `${(convReadout.illustrativeRate + 6.5).toFixed(1)}% + surcharges` : "—"}
          />
          <Link href={`/c/${clientId}/memo`} className="mini-btn seal self-center ml-auto">
            Snapshot → memo
          </Link>
        </div>

        {/* Honesty note */}
        <div className="mt-4 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2 font-mono text-[10px] text-[var(--g-ink-3)]">
          <span className="tone-cost">[additive]</span> Drag = optimistic recompute (&lt;100ms). Readout chips above are{" "}
          <b>ILLUSTRATIVE</b> — they use bracket math only; the full recompute (IRMAA year-mapping, SE, QBI, AMT) requires{" "}
          <code>POST /clients/tax-years/:id/scenarios/recompute</code>. Baseline figures are the real snapshot.
          Spec §9.2. See INTEGRATION-TODO.05.md.
        </div>
      </Panel>

      {/* ===== EMR TERRAIN ===== */}
      <Panel className="rise d2 mt-[22px]">
        <PanelHead>
          <MicroLabel>True marginal terrain · the next $100,000 of ordinary income</MicroLabel>
          <Annotation className="!text-[13px]">
            the nominal bracket says {Math.round(Number(snap.marginal_rate) * 100)}% — the terrain shows what the next dollar really costs
          </Annotation>
          <span className="ml-auto">
            <Chip>[additive] engine-recomputed at $500 steps</Chip>
          </span>
        </PanelHead>
        <div className="px-5 pt-4 pb-2">
          {statutoryPoints.length >= 2 ? (
            <EMRTerrain
              // statutory dashed line = REAL (from bracket rows)
              statutory={statutoryPoints.map((p) => ({ incomeCents: p.incomeCents, ratePct: p.ratePct / 100 }))}
              // illustrative amber curve — NOT engine output
              points={illustrativeEMR.map((p) => ({ incomeCents: p.incomeCents, ratePct: p.ratePct / 100 }))}
              spikes={irmaaLive ? [{ incomeCents: irmaaLive.next_cliff_threshold_cents, label: `IRMAA t${irmaaLive.tier} cliff` }] : undefined}
              height={240}
            />
          ) : (
            <div className="h-[220px] rounded-[10px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] flex items-center justify-center">
              <span className="font-mono text-[11px] text-[var(--g-ink-3)]">Bracket data unavailable for terrain</span>
            </div>
          )}
          <ChartLegend
            className="mt-1 px-0.5"
            items={[
              { label: "statutory bracket steps (real)", tone: "var(--g-ink-3)", dashed: true },
              { label: "true EMR incl. cliffs — ILLUSTRATIVE (additive)", tone: "var(--cliff)" },
            ]}
          />
        </div>
        <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3 font-mono text-[10px] text-[var(--g-ink-3)]">
          Dashed = the bracket table (real). Amber = illustrative shape including SS phase-in and the Medicare cliff.{" "}
          <span className="tone-cost">[additive]</span> true curve requires{" "}
          <code>POST /agents/clients/tax-years/:id/emr-sweep</code> at $500 steps.
          Click any spike to decompose — <span className="tone-cost">[additive]</span>.
        </div>
      </Panel>

      {/* ===== SCENARIO LEDGER ===== */}
      <Panel className="rise d3 mt-[22px] overflow-x-auto">
        <PanelHead>
          <MicroLabel>Scenario ledger · baseline-anchored, delta always visible</MicroLabel>
          <span className="ml-auto">
            <Chip>⎙ print: 3 columns + Δ fits the memo</Chip>
          </span>
        </PanelHead>
        <table className="ledger w-full" style={{ minWidth: 620 }}>
          <thead>
            <tr>
              <th className="px-4 py-2 text-left text-[12px]">{planYear.tax_year}</th>
              {scenarios.map((col) => (
                <th
                  key={col.id}
                  className={`r px-4 py-2 text-right text-[12px] ${col.isBaseline ? "text-[var(--g-ink-2)]" : col.id === "conv-18400" ? "text-[var(--save)]" : "text-[var(--g-ink-2)]"}`}
                >
                  {col.label}
                  {col.isIllustrative ? (
                    <span className="ml-1 font-mono text-[8.5px] text-[var(--g-ink-3)] uppercase tracking-wide">[illus.]</span>
                  ) : null}
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
                      ({planYear.tax_year} MAGI · both enrolled)
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
            {/* True rate row — all except baseline are illustrative */}
            <tr>
              <td className="rowlab px-4 py-2 text-[12px] text-[var(--g-ink-2)]">True rate on the move</td>
              {scenarios.map((col) => (
                <td key={col.id} className={`r px-4 py-2 text-right fig text-[13px] ${col.trueRatePct !== null ? (col.trueRatePct > 30 ? "text-[var(--cliff)]" : "text-[var(--g-ink)]") : "text-[var(--g-ink-3)]"}`}>
                  {col.isBaseline ? "—" : pctFmt(col.trueRatePct)}
                  {col.isIllustrative && col.trueRatePct !== null ? (
                    <span className="ml-0.5 font-mono text-[8px] text-[var(--g-ink-3)]">†</span>
                  ) : null}
                </td>
              ))}
            </tr>
            {/* Lifetime NPV row — fully additive */}
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
          Baseline = real snapshot. Scenario columns are{" "}
          <b>ILLUSTRATIVE</b> (bracket-math only, not full recompute).{" "}
          <span className="font-mono text-[10px] tone-cost">[additive]</span>{" "}
          <code>POST /clients/tax-years/:id/scenarios/recompute</code>.{" "}
          Parentheses in print; negatives never bare-minus in CPA tables. † = illustrative rate.
        </div>
      </Panel>

      {/* ===== CROSSOVER + LADDER ===== */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.25fr_1fr]">

        {/* Crossover chart — illustrative */}
        <Panel className="rise d4">
          <PanelHead>
            <MicroLabel>Cumulative tax · the crossover</MicroLabel>
            <span className="ml-auto text-[11px] text-[var(--g-ink-3)]">pain now, payoff from {planYear.tax_year + 5}</span>
          </PanelHead>
          <div className="px-4 pt-4 pb-1">
            <CrossoverChart
              series={crossoverData.series}
              crossoverLabel={crossoverData.crossoverLabel}
              height={200}
            />
            <div className="mt-2 flex justify-between font-mono text-[9.5px] text-[var(--g-ink-3)]">
              <span>{planYear.tax_year}</span>
              <span>{planYear.tax_year + 5}</span>
              <span>{planYear.tax_year + 9}</span>
              <span>{planYear.tax_year + 14}</span>
            </div>
          </div>
          <ChartLegend
            className="px-4 pb-3"
            items={[
              { label: "do nothing", tone: "var(--g-ink)", dashed: false },
              { label: "conversion ladder", tone: "var(--save)", dashed: false },
            ]}
          />
          <div className="border-t border-[var(--g-hairline-soft)] px-4 pb-3 pt-2 font-mono text-[9.5px] text-[var(--g-ink-3)]">
            <span className="tone-cost">[additive · illustrative series]</span> RMDs begin {planYear.tax_year + 8} — the do-nothing line steepens.
            Real ladder requires <code>optimize_roth_conversion</code> endpoint (spec §9.2).
          </div>
        </Panel>

        {/* Ladder schedule — illustrative fixture */}
        <Panel className="rise d5">
          <PanelHead>
            <MicroLabel>The ladder · each year capped by its own cliff</MicroLabel>
            <span className="ml-auto">
              <Chip href={`/c/${clientId}/memo`}>→ Exhibit in memo</Chip>
            </span>
          </PanelHead>
          {ILLUSTRATIVE_LADDER.map((row) => (
            <LadderRowView key={row.year} row={row} />
          ))}
          <div className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-4 py-3 bg-[rgba(29,138,91,0.04)]">
            <span className="w-[42px] font-mono text-[11px] text-[var(--g-ink-3)]">Σ</span>
            <span className="text-[13px]">
              <b>{centsToUSD(ILLUSTRATIVE_LADDER_TOTAL_CENTS)} converted</b> before RMDs begin
              <span className="block text-[11px] text-[var(--g-ink-3)]">
                every cap engine-priced · re-runs when books or law change
              </span>
            </span>
            <Money cents={-ILLUSTRATIVE_LIFETIME_SAVING_CENTS} tone="save" signed className="ml-auto text-[14px] font-bold" />
          </div>
          <div className="border-t border-[var(--g-hairline-soft)] px-4 py-2.5 font-mono text-[9.5px] text-[var(--g-ink-3)]">
            <span className="tone-cost">[additive · illustrative fixture]</span> Years 2027–2028 use Cho demo narrative (§8).
            Real ladder: <code>optimize_roth_conversion</code>. See INTEGRATION-TODO.05.md.
          </div>
        </Panel>
      </div>

      {/* ===== WHAT-IF OMNIBAR ===== */}
      <div className="rise d6 mt-[22px] flex items-center gap-3.5 rounded-[14px] border border-dashed border-[var(--g-hairline)] px-[18px] py-[13px]">
        <Aavatar name="Strategist" agent="strategist" />
        <span className="flex-1 text-[14px] text-[var(--g-ink-3)]">
          What if —{" "}
          <b className="text-[var(--g-ink-2)] font-semibold">&ldquo;Evelyn retires in March instead of June&rdquo;</b>
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
          № 05 — THE LAB · optimizers as instruments. Backend: expose{" "}
          <code>recompute_scenario</code> + <code>optimize_roth_conversion</code> +{" "}
          <code>emr-sweep</code> optimizer search traces (engines exist; spec §9.2–9.3).
          Baseline is immutable; scenarios are clones. Present mode hides every control.
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
          <td key={col.id} className={`r px-4 py-2 text-right fig text-[13px] ${col.isIllustrative && !isBase ? "bg-[rgba(29,138,91,0.045)]" : ""}`}>
            {format(val)}
            {delta !== null ? (
              <span className={`ml-3 ${
                deltaIsUnfavorable
                  ? (delta > 0 ? "text-[var(--cliff)]" : delta < 0 ? "text-[var(--save)]" : "text-[var(--g-ink-3)]")
                  : (delta < 0 ? "text-[var(--cliff)]" : delta > 0 ? "text-[var(--save)]" : "text-[var(--g-ink-3)]")
              } text-[11px]`}>
                {delta > 0 ? "+" : delta < 0 ? "−" : ""}{fmt(Math.abs(delta))}
                {col.isIllustrative ? <span className="font-mono text-[8px]">†</span> : null}
              </span>
            ) : null}
          </td>
        );
      })}
    </tr>
  );
}

function LadderRowView({ row }: { row: LadderRow }) {
  return (
    <div className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-4 py-3 text-[13px] first:border-t-0">
      <span className="w-[42px] font-mono text-[11px] text-[var(--g-ink-3)]">{row.year}</span>
      <span>
        {row.note}
        <span className="block text-[11px] text-[var(--g-ink-3)]">{row.cap}</span>
      </span>
      <b className="ml-auto fig text-[14px]">
        {centsToUSD(row.amountCents)}
        <span className="ml-0.5 font-mono text-[8px] text-[var(--g-ink-3)]">†</span>
      </b>
    </div>
  );
}
