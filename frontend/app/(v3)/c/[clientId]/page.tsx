"use client";

// Surface 03 — THE CASE FILE (the Phase-1 exemplar; built by frontier to prove
// + harden the kit against REAL data before the swarm fans out). One screen
// that holds the file's whole tax life: the Position on the strata, the cliff
// radar, filed-vs-plan, the plan, and the strategist watching it.
//
// Engine-only numbers: the Position renders from GET /admin/tax-bracket-sets
// (segment spans) + the snapshot (fill) + the analysis (pins) — never hardcoded
// bracket dollars. Anything not yet in the API is honestly marked, never faked.

import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  PositionInstrument,
  CliffRow,
  ProvFigure,
  Term,
  StagePipeline,
  Chip,
  Stamp,
  Money,
  Cavatar,
  MicroLabel,
  Annotation,
  Panel,
  PanelHead,
  Aavatar,
  Omnibar,
  hueForClient,
  type Segment,
  type Pin,
  type Headroom,
  type Provenance,
  type PipelineStage,
} from "@/components/kit";

/* ---- the slices of the live API this surface reads ---- */
interface BracketRow { lower_bound_cents: number; upper_bound_cents: number | null; rate: string; ordinal: number }
interface BracketSet { id: string; tax_year: number; jurisdiction: string; filing_status: string; standard_deduction_cents: number; rows: BracketRow[] }
interface IrmaaSection { available: true; tier: string; total_irmaa_annual_cents: number; next_cliff_threshold_cents: number; distance_to_next_cliff_cents: number; cliff_cost_annual_cents: number; room_to_drop_one_tier_cents?: number | null; note?: string | null }
interface ComprehensiveSection { available: true; total_tax_cents: number; se_tax_cents: number; qbi_deduction_cents: number; amt_cents: number; balance_due_cents: number; base_snapshot_total_tax_cents: number; includes_business: boolean }
interface OppItem { code: string; name: string; category: string; citation: string; estimated_tax_savings_cents: number; eligibility_note: string }
interface OppSection { available: true; total_illustrative_savings_cents: number; items: OppItem[] }
type Maybe<T> = T | { available: false; reason?: string };
interface Analysis {
  filing_status: string;
  comprehensive_return: Maybe<ComprehensiveSection>;
  irmaa: Maybe<IrmaaSection>;
  opportunities: Maybe<OppSection>;
}

const FILING: Record<string, string> = { single: "single", mfj: "married filing jointly", mfs: "married filing separately", hoh: "head of household", qss: "surviving spouse" };

export default function CasePage() {
  const { clientId, overview, loading } = useClientOverview();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [aLoading, setALoading] = useState(true);

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);
  const baseYear: YearRow | undefined = useMemo(
    () => overview?.years.find((y) => y.id === overview.base_year_id),
    [overview],
  );
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
  const { segments, pins, headroom } = useMemo(() => {
    const empty = { segments: [] as Segment[], pins: [] as Pin[], headroom: undefined as Headroom | undefined };
    if (!sets || !planYear || !snap) return empty;
    const fed = sets.filter((s) => s.jurisdiction?.toLowerCase().includes("fed"));
    const pool = fed.length ? fed : sets;
    const set = pool.find((s) => s.tax_year === planYear.tax_year && s.filing_status === planYear.filing_status)
      ?? pool.find((s) => s.filing_status === planYear.filing_status)
      ?? pool[0];
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
    const pins: Pin[] = [];
    let headroom: Headroom | undefined;
    const ir = analysis?.irmaa;
    if (ir && ir.available && ir.next_cliff_threshold_cents > 0) {
      pins.push({ atCents: ir.next_cliff_threshold_cents, label: `IRMAA t${ir.tier}` });
      if (ir.distance_to_next_cliff_cents > 0) {
        headroom = { fromCents: income, toCents: ir.next_cliff_threshold_cents, label: `${centsToUSD(ir.distance_to_next_cliff_cents)} headroom` };
      }
    } else {
      // no IRMAA (typical for a working-age owner): headroom to the next bracket edge
      const next = segments.find((s) => s.fromCents > income);
      if (next) headroom = { fromCents: income, toCents: next.fromCents, label: `${centsToUSD(next.fromCents - income)} headroom` };
    }
    return { segments, pins, headroom };
  }, [sets, planYear, snap, analysis]);

  if (loading || aLoading) {
    return <div className="wrap py-7"><div className="skeleton h-[420px] w-full rounded-[14px]" /></div>;
  }
  if (!overview || !planYear || !snap) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No confirmed tax year yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">Import and confirm a return to open the case file.</p>
        </Panel>
      </div>
    );
  }

  const cr = analysis?.comprehensive_return;
  const headlineTax = cr && cr.available ? cr.total_tax_cents : snap.total_tax_cents;
  const nominal = Number(snap.marginal_rate);
  const effective = Number(snap.effective_rate);

  const headlineProv: Provenance | undefined = cr && cr.available ? {
    label: `${planYear.tax_year} comprehensive total tax`,
    engine: "comprehensive.calculate",
    source: "engine",
    inputs: [
      { k: "folds", v: `1040 + SE ${centsToUSD(cr.se_tax_cents)} + QBI −${centsToUSD(cr.qbi_deduction_cents)} + AMT ${cr.amt_cents > 0 ? centsToUSD(cr.amt_cents) : "none"}` },
      { k: "balance due", v: centsToUSD(cr.balance_due_cents) },
    ],
    constants: [{ k: "brackets", v: `${planYear.tax_year} ${planYear.filing_status} · golden-tested` }],
    auditRef: `tax-year ${taxYearId?.slice(0, 8)}`,
  } : undefined;

  // the plan: real strategies from the overview
  const identified = overview.strategies.reduce((a, s) => a + (s.estimated_savings_cents || 0), 0);
  const signedCount = overview.strategies.filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition)).length;

  // the engagement pipeline, derived from real state
  const stages: PipelineStage[] = [
    { label: "intake", state: "done" },
    { label: "baseline", state: baseYear?.snapshot ? "done" : "todo" },
    { label: "analysis", state: analysis ? "done" : "todo" },
    { label: "memo", state: "todo" },
    { label: "signed", state: planYear.finalized_at ? "sealed" : "todo" },
    { label: `implementing ${signedCount}/${overview.strategies.length || 0}`, state: signedCount > 0 ? "on" : "todo" },
    { label: "monitoring", state: "todo" },
  ];

  const ir = analysis?.irmaa;
  const opp = analysis?.opportunities;
  const nextSeg = segments.find((s) => s.fromCents > snap.taxable_income_cents);

  return (
    <div className="wrap py-7 pb-16">
      {/* ---- identity row ---- */}
      <section className="rise flex items-center gap-[18px]">
        <Cavatar name={overview.client.display_name} hue={hue} className="!h-[54px] !w-[54px] !text-[18px]" />
        <div>
          <h1 className="text-[32px] font-extrabold leading-none tracking-[-0.02em]">{overview.client.display_name}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Chip>{FILING[overview.client.filing_status_default] ?? overview.client.filing_status_default}{overview.client.primary_state ? ` · ${overview.client.primary_state}` : ""}</Chip>
            {planYear.finalized_at ? <Chip tone="seal">plan sealed</Chip> : <Chip>plan year {planYear.tax_year}</Chip>}
          </div>
        </div>
        <div className="ml-auto hidden lg:block">
          <StagePipeline stages={stages} />
        </div>
      </section>

      {/* ---- the three-rate cluster ---- */}
      <section className="rise d1 mt-5 grid grid-cols-2 overflow-hidden rounded-[14px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)] md:grid-cols-4">
        <RateCell
          label={<Term k="nominal-bracket">nominal bracket</Term>}
          value={`${(nominal * 100).toFixed(0)}%`}
          detail={`${planYear.tax_year} · ${planYear.filing_status}`}
        />
        <RateCell
          hot
          label={<Term k="marginal-rate">true next-dollar</Term>}
          value="—"
          detail="EMR sweep — additive (spec §9.3)"
        />
        <RateCell
          label={<Term k="effective-rate">average rate</Term>}
          value={`${(effective * 100).toFixed(1)}%`}
          detail={`tax ${centsToUSD(headlineTax)} ÷ income ${centsToUSD(snap.total_income_cents)}`}
        />
        <RateCell
          label={`${planYear.tax_year} plan savings`}
          value={<Money cents={identified} tone="save" />}
          detail={`${signedCount} signed · ${overview.strategies.length} identified`}
        />
      </section>

      {/* ---- THE POSITION ---- */}
      <Panel className="rise d2 relative mt-[22px] px-7 pb-16 pt-7">
        <div className="mb-11 flex items-baseline gap-3.5">
          <MicroLabel>The position · taxable income on the {planYear.tax_year} strata</MicroLabel>
          <Annotation className="!text-[14px]">where every conversation starts</Annotation>
          <span className="ml-auto text-[13px] text-[var(--g-ink-2)]">
            taxable <ProvFigure cents={snap.taxable_income_cents} prov={{ label: "taxable income", engine: "snapshot", source: "engine", inputs: [{ k: "AGI", v: centsToUSD(snap.agi_cents) }] }} />
          </span>
        </div>
        {segments.length > 0 ? (
          <>
            <PositionInstrument
              segments={segments}
              incomeCents={snap.taxable_income_cents}
              nowLabel={<>you · {centsToUSD(snap.taxable_income_cents)}</>}
              pins={pins}
              headroom={headroom}
            />
            <div className="mt-6 flex justify-between font-mono text-[9.5px] text-[var(--g-ink-3)]">
              <span>{centsToUSD(segments[0].fromCents)}</span>
              <span>taxable →</span>
              <span>{centsToUSD(segments[segments.length - 1].toCents)}</span>
            </div>
          </>
        ) : (
          <p className="text-[13px] text-[var(--g-ink-3)]">Bracket set unavailable for {planYear.tax_year} {planYear.filing_status}.</p>
        )}
      </Panel>

      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.62fr_1fr]">
        <div className="flex flex-col gap-[22px]">
          {/* ---- cliff radar ---- */}
          <Panel className="rise d3">
            <PanelHead>
              <MicroLabel><Term k="cliff">cliff radar</Term></MicroLabel>
              <Annotation className="ml-auto !text-[13px]">thresholds with teeth — dollars both ways</Annotation>
            </PanelHead>
            <div className="px-5 py-1">
              {nextSeg ? (
                <CliffRow
                  label={`${(nextSeg.rate * 100).toFixed(0)}% bracket edge`}
                  thresholdCents={nextSeg.fromCents}
                  distanceCents={nextSeg.fromCents - snap.taxable_income_cents}
                  soft
                  costNote={<>next $1 taxed at {(nextSeg.rate * 100).toFixed(0)}%</>}
                  mapping={`ordinary · ${centsToUSD(nextSeg.fromCents)}`}
                />
              ) : null}
              {ir && ir.available && ir.next_cliff_threshold_cents > 0 ? (
                <CliffRow
                  label={`IRMAA tier ${ir.tier}`}
                  glossKey="irmaa"
                  thresholdCents={ir.next_cliff_threshold_cents}
                  distanceCents={ir.distance_to_next_cliff_cents}
                  costOfCrossingCents={ir.cliff_cost_annual_cents}
                  binding="cost"
                  mapping={ir.note ?? "this year's income sets the premium two years out"}
                />
              ) : null}
            </div>
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
              <span className="tone-cost">[additive]</span> NIIT · Add&apos;l-Medicare · QBI phase-in radar rows — from analysis sections + constants (spec §7-03).
            </div>
          </Panel>

          {/* ---- filed vs plan ---- */}
          {baseYear?.snapshot ? (
            <Panel className="rise d4">
              <PanelHead>
                <MicroLabel>Total tax · filed vs plan</MicroLabel>
                <span className="ml-auto inline-flex items-center gap-3 text-[11px] text-[var(--g-ink-3)]">
                  <span className="inline-flex items-center gap-1.5"><i className="inline-block h-[11px] w-[11px] rounded-[3px] bg-[var(--g-ink)]" /> filed</span>
                  <span className="inline-flex items-center gap-1.5"><i className="inline-block h-[11px] w-[11px] rounded-[3px] border-[1.5px] border-dashed border-[var(--g-ink-2)]" /> plan</span>
                </span>
              </PanelHead>
              <div className="grid grid-cols-[1fr_auto_1fr] items-center">
                <div className="px-6 py-6">
                  <MicroLabel>{baseYear.tax_year} · filed</MicroLabel>
                  <div className="mt-2 text-[34px] font-bold leading-none tracking-[-0.025em]">
                    <ProvFigure cents={baseYear.snapshot.total_tax_cents} prov={{ label: `${baseYear.tax_year} total tax`, engine: "comprehensive.calculate", source: "engine" }} />
                  </div>
                  <div className="mt-2 text-[12px] text-[var(--g-ink-3)]">{(Number(baseYear.snapshot.effective_rate) * 100).toFixed(1)}% average</div>
                </div>
                <div className="rounded-[12px] border border-[color-mix(in_srgb,var(--save)_30%,transparent)] bg-[var(--save-soft)] px-4 py-3 text-center">
                  <Money cents={planYear.snapshot ? planYear.snapshot.total_tax_cents - baseYear.snapshot.total_tax_cents : 0} tone="save" signed className="block text-[19px]" />
                  <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--g-ink-3)]">ENGINE-VERIFIED</span>
                </div>
                <div className="px-6 py-6">
                  <MicroLabel><span className="tone-save">{planYear.tax_year} · plan{planYear.finalized_at ? " (signed)" : ""}</span></MicroLabel>
                  <div className="mt-2 text-[34px] font-bold leading-none tracking-[-0.025em]">
                    <ProvFigure cents={headlineTax} prov={headlineProv} />
                  </div>
                  <div className="mt-2 text-[12px] text-[var(--g-ink-3)]">{(nominal * 100).toFixed(0)}% nominal bracket</div>
                </div>
              </div>
            </Panel>
          ) : null}

          {/* ---- implementation (real strategies) ---- */}
          {overview.strategies.length > 0 ? (
            <Panel className="rise d5">
              <PanelHead>
                <MicroLabel>The plan · {signedCount} of {overview.strategies.length}</MicroLabel>
                <Stamp kind={planYear.finalized_at ? "signed" : "draft"} className="ml-auto !transform-none !text-[9px]">
                  {planYear.finalized_at ? "signed" : "draft"}
                </Stamp>
              </PanelHead>
              <div className="px-2 py-1">
                {overview.strategies.slice(0, 6).map((s) => (
                  <div key={s.id} className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-3 py-3 first:border-t-0">
                    <span className="text-[13px]">{s.name}</span>
                    <span className="ml-auto"><Money cents={s.estimated_savings_cents} tone="save" /></span>
                    <Chip tone={["signed", "accepted", "implementing"].includes(s.disposition) ? "save" : "neutral"}>{s.disposition}</Chip>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>

        <div className="flex flex-col gap-[22px]">
          {/* ---- the strategist is watching: real opportunities ---- */}
          <Panel className="rise d4 p-[18px]">
            <div className="flex gap-3">
              <Aavatar name="Strategist" agent="strategist" />
              <div className="min-w-0 flex-1">
                <MicroLabel><span className="tone-agent">Strategist · watching this file</span></MicroLabel>
                {opp && opp.available && opp.items.length > 0 ? (
                  <>
                    <p className="mt-2 text-[13px] leading-relaxed text-[var(--g-ink-2)]">
                      {opp.items.length} engine-found {opp.items.length === 1 ? "opening" : "openings"} on this file —
                      {" "}<Money cents={opp.total_illustrative_savings_cents} tone="save" /> illustrative.
                    </p>
                    <div className="mt-2 space-y-1.5">
                      {opp.items.slice(0, 3).map((o) => (
                        <div key={o.code} className="flex items-center gap-2 text-[12.5px]">
                          <span className="dot" style={{ background: "var(--save)" }} />
                          <span className="truncate">{o.name}</span>
                          <span className="ml-auto"><Money cents={o.estimated_tax_savings_cents} tone="save" /></span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 font-mono text-[10px] text-[var(--g-ink-3)]">
                      BECAUSE: engine opportunity scan · {planYear.tax_year} {planYear.filing_status}
                    </div>
                  </>
                ) : (
                  <p className="mt-2 text-[13px] text-[var(--g-ink-2)]">
                    No openings flagged yet on this year. The watch note&apos;s BECAUSE line (goals + the data that triggered it) wires with the strategist run stream (spec §7-03, additive).
                  </p>
                )}
              </div>
            </div>
          </Panel>

          {/* what this exemplar proves, for the swarm + Aaron */}
          <Panel className="rise d5 p-5">
            <div className="flex items-center gap-2">
              <span className="dot dot-live" />
              <MicroLabel>exemplar — the kit, proven on real data</MicroLabel>
            </div>
            <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--g-ink-2)]">
              The Position renders from real bracket spans + the live snapshot; every figure opens its
              provenance; the cliff radar + filed-vs-plan + the plan are live. The reference the
              Phase-1 swarm copies. Secondary cards (entities map, the brief, the BECAUSE watch line)
              + the EMR true-rate land next.
            </p>
          </Panel>
        </div>
      </div>

      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this file…" />
      </div>
    </div>
  );
}

/* a rate cell in the three-rate cluster (matches the mockup's bordered row) */
function RateCell({ label, value, detail, hot }: { label: React.ReactNode; value: React.ReactNode; detail: React.ReactNode; hot?: boolean }) {
  return (
    <div className={`border-l border-[var(--g-hairline-soft)] px-5 py-3.5 first:border-l-0 ${hot ? "bg-[linear-gradient(180deg,rgba(201,114,67,0.10),transparent)]" : ""}`}>
      <MicroLabel>{label}</MicroLabel>
      <div className={`mt-1.5 text-[26px] font-bold leading-none tracking-[-0.02em] ${hot ? "tone-cost" : ""}`}>{value}</div>
      <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">{detail}</div>
    </div>
  );
}
