"use client";

// Surface 14 — YOUR PLAN (solo / company posture)
//
// The root home when the firm shell is NOT mounted (individual or company self-
// host). The firm shell dissolves; this is their native home. Copy of the Case
// File data wiring: Position hero + cliff radar + "Needs you" queue (your
// decisions — no "client") + your entities + your four estimate quarters + omnibar.
//
// POSTURE NOTE: The v1 data strategy is to take GET /clients → first client as
// "your file". The [additive] posture resolver (spec §7-14) will let the user
// select/switch which file is their own. The selection is honest-labelled below.
//
// DATA WIRING:
// [live] GET /clients → first client as "your file" for v1
// [live] GET /clients/:id/overview → Position + cliff data + strategies + quarterly
// [live] GET /clients/:id/analysis  → analysis.irmaa for cliff pins
// [live] GET /admin/tax-bracket-sets → real bracket spans for the Position
//
// [additive] posture resolver (workspace.fileCount/kind → 14 vs 01)
// [additive] workspace switcher (you / your company / a firm)
// [additive] entities from AO sync (v1 shows from analysis.business or placeholder)
// [additive] tasks model (the "Needs you" queue v1 derives from strategies / plan state)
// [additive] "your file" selection — v1 uses the first client returned; full
//            per-user home-file assignment lands with the posture resolver

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import {
  PositionInstrument,
  CliffRow,
  ProvFigure,
  Term,
  Chip,
  Money,
  MicroLabel,
  Annotation,
  Panel,
  PanelHead,
  Aavatar,
  MiniButton,
  Omnibar,
  QueueItem,
  type Segment,
  type Pin,
  type Headroom,
  type Provenance,
} from "@/components/kit";

/* ---- shapes mirrored from the Case File exemplar ---- */
interface BracketRow { lower_bound_cents: number; upper_bound_cents: number | null; rate: string; ordinal: number }
interface BracketSet { id: string; tax_year: number; jurisdiction: string; filing_status: string; standard_deduction_cents: number; rows: BracketRow[] }
interface IrmaaSection { available: true; tier: string; total_irmaa_annual_cents: number; next_cliff_threshold_cents: number; distance_to_next_cliff_cents: number; cliff_cost_annual_cents: number; room_to_drop_one_tier_cents?: number | null; note?: string | null }
interface ComprehensiveSection { available: true; total_tax_cents: number; se_tax_cents: number; qbi_deduction_cents: number; amt_cents: number; balance_due_cents: number; base_snapshot_total_tax_cents: number; includes_business: boolean }
interface OppItem { code: string; name: string; category: string; citation: string; estimated_tax_savings_cents: number; eligibility_note: string }
interface OppSection { available: true; total_illustrative_savings_cents: number; items: OppItem[] }
interface BusinessSection { available: true; entities?: { id: string; name: string; entity_type: string; qbi_eligible: boolean; qbi_deduction_cents: number }[]; notes?: string }
type Maybe<T> = T | { available: false; reason?: string };
interface Analysis {
  filing_status: string;
  comprehensive_return: Maybe<ComprehensiveSection>;
  irmaa: Maybe<IrmaaSection>;
  opportunities: Maybe<OppSection>;
  business: Maybe<BusinessSection>;
}
interface ClientSummary { id: string; display_name: string; filing_status_default: string; primary_state: string | null; status: string }
interface Snapshot { total_income_cents: number; agi_cents: number; taxable_income_cents: number; total_tax_cents: number; marginal_rate: string; effective_rate: string; has_manual_override: boolean }
interface YearRow { id: string; tax_year: number; role: string; filing_status: string; is_locked: boolean; finalized_at: string | null; snapshot: Snapshot | null }
interface StrategyRow { id: string; name: string; category: string; client_facing_copy: string; disposition: string; amount_cents: number; estimated_savings_cents: number; effective_rate_used: string; status_flag: string }
interface QuarterRow { quarter: number; due_date: string; required_payment_cents: number; payment_made_cents: number; unpaid_rollforward_cents: number; safe_harbor_basis: string; status: string }
interface Overview {
  client: { id: string; display_name: string; filing_status_default: string; primary_state: string | null; status: string; external_ref: string | null; notes: string | null };
  years: YearRow[];
  base_year_id: string | null;
  plan_year_id: string | null;
  strategies: StrategyRow[];
  quarterly: QuarterRow[];
}

const FILING: Record<string, string> = { single: "single", mfj: "married filing jointly", mfs: "married filing separately", hoh: "head of household", qss: "surviving spouse" };

const QUARTER_LABELS: Record<number, { label: string; dueLabel: string }> = {
  1: { label: "Q1", dueLabel: "Apr 15" },
  2: { label: "Q2", dueLabel: "Jun 15" },
  3: { label: "Q3", dueLabel: "Sep 15" },
  4: { label: "Q4", dueLabel: "Jan 15" },
};

export default function HomePage() {
  // [live] GET /clients — first client as "your file" for v1
  // TODO(integration: workspace.fileCount / workspace.kind → posture resolver, spec §7-14)
  const [clients, setClients] = useState<ClientSummary[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [cLoading, setCLoading] = useState(true);
  const [oLoading, setOLoading] = useState(false);
  const [aLoading, setALoading] = useState(false);

  // ALL hooks are called before any early return (rules-of-hooks)
  useEffect(() => {
    // [live] GET /clients
    api.get("/clients")
      .then((r) => {
        const list: ClientSummary[] = Array.isArray(r.data) ? r.data : (r.data?.clients ?? []);
        setClients(list);
      })
      .catch(() => setClients([]))
      .finally(() => setCLoading(false));
  }, []);

  useEffect(() => {
    // [live] GET /admin/tax-bracket-sets
    api.get("/admin/tax-bracket-sets")
      .then((r) => setSets(r.data))
      .catch(() => setSets([]));
  }, []);

  const myClient = clients?.[0] ?? null;
  const myClientId = myClient?.id ?? null;

  useEffect(() => {
    if (!myClientId) return;
    setOLoading(true);
    // [live] GET /clients/:id/overview
    api.get(`/clients/${myClientId}/overview`)
      .then((r) => setOverview(r.data))
      .catch(() => setOverview(null))
      .finally(() => setOLoading(false));
  }, [myClientId]);

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);

  const taxYearId = planYear?.id ?? null;

  useEffect(() => {
    if (!taxYearId) { setALoading(false); return; }
    setALoading(true);
    // [live] GET /clients/tax-years/:id/analysis
    api.get(`/clients/tax-years/${taxYearId}/analysis`)
      .then((r) => setAnalysis(r.data))
      .catch(() => setAnalysis(null))
      .finally(() => setALoading(false));
  }, [taxYearId]);

  /* ---- Position segments: REAL bracket spans (same logic as Case File) ---- */
  const { segments, pins, headroom } = useMemo<{
    segments: Segment[];
    pins: Pin[];
    headroom: Headroom | undefined;
  }>(() => {
    const empty = { segments: [] as Segment[], pins: [] as Pin[], headroom: undefined };
    if (!sets || !planYear || !planYear.snapshot) return empty;
    const snap = planYear.snapshot;
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
    const segs: Segment[] = rows.map((r, i) => ({
      rate: Number(r.rate),
      fromCents: r.lower_bound_cents,
      toCents: r.upper_bound_cents ?? (i === rows.length - 1 ? cap : r.lower_bound_cents),
    }));
    const pinArr: Pin[] = [];
    let hr: Headroom | undefined;
    const ir = analysis?.irmaa;
    if (ir && ir.available && ir.next_cliff_threshold_cents > 0) {
      pinArr.push({ atCents: ir.next_cliff_threshold_cents, label: `IRMAA t${ir.tier}` });
      if (ir.distance_to_next_cliff_cents > 0) {
        hr = { fromCents: income, toCents: ir.next_cliff_threshold_cents, label: `${centsToUSD(ir.distance_to_next_cliff_cents)} headroom` };
      }
    } else {
      const next = segs.find((s) => s.fromCents > income);
      if (next) hr = { fromCents: income, toCents: next.fromCents, label: `${centsToUSD(next.fromCents - income)} headroom` };
    }
    return { segments: segs, pins: pinArr, headroom: hr };
  }, [sets, planYear, analysis]);

  /* ---- derived display values ---- */
  const snap = planYear?.snapshot ?? null;

  const identified = (overview?.strategies ?? []).reduce((a, s) => a + (s.estimated_savings_cents || 0), 0);
  const signedCount = (overview?.strategies ?? []).filter((s) => ["signed", "accepted", "implementing"].includes(s.disposition)).length;

  const headlineProv: Provenance | undefined = (() => {
    const cr = analysis?.comprehensive_return;
    if (!cr || !cr.available || !taxYearId) return undefined;
    return {
      label: `${planYear?.tax_year ?? ""} comprehensive total tax`,
      engine: "comprehensive.calculate",
      source: "engine" as const,
      inputs: [
        { k: "folds", v: `1040 + SE ${centsToUSD(cr.se_tax_cents)} + QBI −${centsToUSD(cr.qbi_deduction_cents)}` },
        { k: "balance due", v: centsToUSD(cr.balance_due_cents) },
      ],
      constants: [{ k: "brackets", v: `${planYear?.tax_year ?? ""} ${planYear?.filing_status ?? ""} · golden-tested` }],
      auditRef: `tax-year ${taxYearId?.slice(0, 8)}`,
    };
  })();

  const headlineTax = (() => {
    const cr = analysis?.comprehensive_return;
    if (cr && cr.available) return cr.total_tax_cents;
    return snap?.total_tax_cents ?? 0;
  })();

  const opp = analysis?.opportunities;
  const nextSeg = snap ? segments.find((s) => s.fromCents > snap.taxable_income_cents) : undefined;

  // Business entities [additive: AO sync; v1 derives from analysis.business]
  const businessSection = analysis?.business;
  const entities = businessSection && businessSection.available ? (businessSection.entities ?? []) : [];

  // Estimates: live quarterly data
  const quarterly = overview?.quarterly ?? [];
  const allPaid = quarterly.length > 0 && quarterly.every((q) => q.status === "paid" || q.payment_made_cents >= q.required_payment_cents);
  const hasPaidAny = quarterly.some((q) => q.status === "paid" || q.payment_made_cents >= q.required_payment_cents);

  // "Needs you" queue: [additive: tasks model, memo persistence; v1 derives
  // from strategies + plan state + the real quarterly data]
  // TODO(integration: GET /agents/clients/:id/tasks) — task model for this queue
  const unsignedStrategies = (overview?.strategies ?? []).filter((s) => !["signed", "accepted", "implementing"].includes(s.disposition));
  const behindOnQuarter = quarterly.some((q) => q.status === "underpaid" || (q.required_payment_cents > 0 && q.payment_made_cents < q.required_payment_cents));

  /* ---- loading / empty states ---- */
  if (cLoading || oLoading || aLoading) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[52px] w-[340px] rounded-[14px]" />
        <div className="mt-5 skeleton h-[52px] w-full rounded-[14px]" />
        <div className="mt-5 grid gap-[22px] lg:grid-cols-[1.55fr_1fr]">
          <div className="flex flex-col gap-[22px]">
            <div className="skeleton h-[300px] rounded-[14px]" />
            <div className="skeleton h-[220px] rounded-[14px]" />
          </div>
          <div className="flex flex-col gap-[22px]">
            <div className="skeleton h-[160px] rounded-[14px]" />
            <div className="skeleton h-[200px] rounded-[14px]" />
          </div>
        </div>
      </div>
    );
  }

  if (!myClient || !overview || !planYear || !snap) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No file found</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            Add your first return to open Your Plan, or{" "}
            <Link href="/start" className="underline">start here</Link>.
          </p>
        </Panel>
      </div>
    );
  }

  const nominal = Number(snap.marginal_rate);
  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 18) return "Good afternoon";
    return "Good evening";
  })();

  return (
    <div className="wrap py-7 pb-16">
      {/* ---- head ---- */}
      <section className="rise">
        <MicroLabel>Solo posture · self-hosted · your books, your plan</MicroLabel>
        <h1 className="mt-2 text-[34px] font-extrabold leading-tight tracking-[-0.025em]">
          {greeting}, {overview.client.display_name.split(" ")[0]}.<br />
          Your {planYear.tax_year} plan is {allPaid ? "on pace" : "underway"}{unsignedStrategies.length > 0 ? ` — ${unsignedStrategies.length} thing${unsignedStrategies.length > 1 ? "s" : ""} need${unsignedStrategies.length === 1 ? "s" : ""} you` : ""}.
        </h1>
        <div className="mt-3 flex flex-wrap gap-[22px] text-[12.5px] text-[var(--g-ink-3)]">
          <span>your {planYear.tax_year} tax (plan) <ProvFigure cents={headlineTax} prov={headlineProv} className="text-[var(--g-ink)]" /></span>
          {identified > 0 ? (
            <span>you&rsquo;re saving <Money cents={identified} tone="save" /> /yr vs no plan</span>
          ) : null}
          {signedCount > 0 ? (
            <span>implementing <b className="text-[var(--g-ink)]">{signedCount}</b> of {overview.strategies.length} strategies</span>
          ) : null}
          {hasPaidAny ? (
            <span>estimates <b className="tone-save">on track ✓</b></span>
          ) : behindOnQuarter ? (
            <span>estimates <b className="tone-cost">behind ⚠</b></span>
          ) : null}
        </div>
      </section>

      {/* ---- posture banner (the architecture, made explicit) ---- */}
      <div className="rise d1 mt-[18px] flex items-center gap-3 rounded-[12px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-4 py-3 text-[12.5px] text-[var(--g-ink-2)]">
        <span className="text-[15px]">▦</span>
        <span>
          Same engine a CPA firm runs across a book of clients — here it&rsquo;s just <b className="text-[var(--g-ink)]">you and your entities</b>. No clients, no roster, nothing leaves this box.
          A firm sees a book; you see your file. <b className="text-[var(--g-ink)]">The file is identical.</b>
        </span>
        {/* TODO(integration: posture resolver spec §7-14) — this label is the v1 stand-in for your-file selection */}
        <span className="ml-auto shrink-0 font-mono text-[10px] text-[var(--g-ink-3)]">your file: {overview.client.display_name}</span>
      </div>

      {/* ---- omnibar (door 2 collapsed) ---- */}
      <div className="rise d1 mt-[18px]">
        <div className="relative flex items-center gap-3 rounded-[16px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-[18px] py-[15px] shadow-[var(--shadow-panel)]"
          style={{ background: "var(--g-surface)" }}>
          {/* strata ring */}
          <span className="pointer-events-none absolute inset-[-1px] rounded-[17px] p-px [background:var(--strata)] opacity-30 [-webkit-mask:linear-gradient(#000_0_0)_content-box,linear-gradient(#000_0_0)] [-webkit-mask-composite:xor] [mask-composite:exclude]" aria-hidden />
          <Aavatar name="S" agent="strategist" className="!h-[34px] !w-[34px] !rounded-[10px]" />
          <span className="flex-1 text-[14.5px] text-[var(--g-ink-3)]">
            Ask your strategist — <b className="text-[var(--g-ink-2)] font-medium">&ldquo;should I do a Roth conversion this year?&rdquo;</b>
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link href="/console" className="chip agent">● open the console</Link>
          <Link href="/console?q=what%27s+my+best+move+this+year" className="chip">what&rsquo;s my best move this year?</Link>
          {myClientId ? <Link href={`/c/${myClientId}/entities`} className="chip">is the S-corp still worth it?</Link> : null}
          <Link href="/console?q=am+I+safe+on+estimates" className="chip">am I safe on estimates?</Link>
        </div>
      </div>

      {/* ---- main grid: position + queue on left; entities + estimates on right ---- */}
      <div className="rise d2 mt-6 grid items-start gap-[22px] lg:grid-cols-[1.55fr_1fr]">
        <div className="flex flex-col gap-[22px]">

          {/* ---- your position: same instrument as the Case File ---- */}
          <Panel className="relative px-7 pb-16 pt-7">
            <div className="mb-11 flex items-baseline gap-3.5">
              <MicroLabel>Your position · taxable income on the {planYear.tax_year} strata</MicroLabel>
              {identified > 0 ? (
                <span className="ml-auto text-right">
                  <Money cents={-identified} tone="save" signed className="block text-[22px] font-bold" />
                  <span className="block font-mono text-[9.5px] text-[var(--g-ink-3)]">YOUR PLAN VS NO PLAN</span>
                </span>
              ) : null}
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
                  <span>your taxable income →</span>
                  <span>{centsToUSD(segments[segments.length - 1].toCents)}</span>
                </div>
              </>
            ) : (
              <p className="text-[13px] text-[var(--g-ink-3)]">Bracket set unavailable for {planYear.tax_year} {planYear.filing_status}.</p>
            )}
          </Panel>

          {/* ---- cliff radar ---- */}
          <Panel>
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
              {(() => {
                const ir = analysis?.irmaa;
                if (ir && ir.available && ir.next_cliff_threshold_cents > 0) {
                  return (
                    <CliffRow
                      label={`IRMAA tier ${ir.tier}`}
                      glossKey="irmaa"
                      thresholdCents={ir.next_cliff_threshold_cents}
                      distanceCents={ir.distance_to_next_cliff_cents}
                      costOfCrossingCents={ir.cliff_cost_annual_cents}
                      binding="cost"
                      mapping={ir.note ?? "this year's income sets the premium two years out"}
                    />
                  );
                }
                return null;
              })()}
            </div>
            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
              <span className="tone-cost">[additive]</span> NIIT · Add&apos;l-Medicare · QBI phase-in radar rows — from analysis sections + constants (spec §7-03).
            </div>
          </Panel>

          {/* ---- your decisions: the sign-off queue reframed as YOUR calls ---- */}
          {/* [additive: tasks model] — v1 derives from strategies/plan/quarterly */}
          <Panel>
            <PanelHead>
              <MicroLabel style={{ color: "var(--seal)" }}>Needs you</MicroLabel>
              <Annotation className="ml-auto !text-[13px]">your strategist proposes — you decide</Annotation>
            </PanelHead>

            {/* AO / books sync item: books are behind plan */}
            {opp && opp.available && opp.items.length > 0 ? (
              <QueueItem
                lead={<QueueIcon type="ao" />}
                title="Books data updated — review the projection"
                sub={
                  <>
                    Strategist found <b className="fig">{opp.items.length}</b> opening{opp.items.length !== 1 ? "s" : ""} — <Money cents={opp.total_illustrative_savings_cents} tone="save" /> illustrative. Check whether the projection still holds.
                  </>
                }
                actions={
                  <>
                    {myClientId ? <MiniButton href={`/c/${myClientId}/lab`}>Show me</MiniButton> : null}
                    {myClientId ? <MiniButton go href={`/c/${myClientId}`}>Re-project</MiniButton> : null}
                  </>
                }
              />
            ) : null}

            {/* unsigned strategies */}
            {unsignedStrategies.slice(0, 2).map((s) => (
              <QueueItem
                key={s.id}
                lead={<QueueIcon type="task" />}
                title={s.name}
                sub={
                  <>
                    Worth <Money cents={s.estimated_savings_cents} tone="save" className="fig" /> · review the strategy and mark it for implementation
                  </>
                }
                actions={
                  myClientId ? <MiniButton go href={`/c/${myClientId}/plan`}>Do it</MiniButton> : undefined
                }
              />
            ))}

            {/* the plan memo — review and keep */}
            {myClientId ? (
              <QueueItem
                lead={<QueueIcon type="memo" />}
                title={`Your ${planYear.tax_year} plan — review & keep`}
                sub={
                  <>
                    {overview.strategies.length} strategies · this is for <b>you</b>, not a client letterhead · export a copy for your records or your accountant
                  </>
                }
                actions={<MiniButton seal href={`/c/${myClientId}/memo`}>Review</MiniButton>}
              />
            ) : null}

            {/* empty state: nothing pending */}
            {!opp?.available && unsignedStrategies.length === 0 ? (
              <div className="px-5 py-4 text-[13px] text-[var(--g-ink-3)]">
                Nothing pending — your plan is up to date.
                {/* TODO(integration: GET /agents/clients/:id/tasks) — richer queue with task model */}
              </div>
            ) : null}

            <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10px] text-[var(--g-ink-3)]">
              <span className="tone-cost">[additive]</span> full task model (5-field contracts, statutory deadlines, agent-drafted reminders) lands with spec §9.4.
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-[22px]">
          {/* ---- the strategist watching ---- */}
          <Panel className="p-[18px]">
            <div className="flex gap-3">
              <Aavatar name="Strategist" agent="strategist" />
              <div className="min-w-0 flex-1">
                <MicroLabel><span className="tone-agent">Strategist · watching your file</span></MicroLabel>
                {opp && opp.available && opp.items.length > 0 ? (
                  <>
                    <p className="mt-2 text-[13px] leading-relaxed text-[var(--g-ink-2)]">
                      {opp.items.length} engine-found {opp.items.length === 1 ? "opening" : "openings"} on your file —{" "}
                      <Money cents={opp.total_illustrative_savings_cents} tone="save" /> illustrative.
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
                    No openings flagged yet on your file. Run the strategist on the Memo tab to surface opportunities and draft your plan.
                  </p>
                )}
              </div>
            </div>
          </Panel>

          {/* ---- your entities ---- */}
          {/* [additive: AO sync for YTD/pace; v1 derives entity list from analysis.business] */}
          <Panel>
            <PanelHead>
              <MicroLabel>Your entities</MicroLabel>
              {myClientId ? (
                <Link href={`/c/${myClientId}/entities`} className="chip agent ml-auto">structure map →</Link>
              ) : null}
            </PanelHead>
            {entities.length > 0 ? (
              <>
                {entities.map((e) => (
                  <div key={e.id} className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-[18px] py-3 first:border-t-0">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border border-[color-mix(in_srgb,var(--agent)_25%,transparent)] bg-[var(--agent-soft)] font-mono text-[10px] text-[var(--agent)]">
                      {e.entity_type?.slice(0, 1).toUpperCase() ?? "E"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <b className="block text-[13px]">{e.name}</b>
                      <div className="text-[11px] text-[var(--g-ink-3)]">
                        {e.entity_type}
                        {e.qbi_eligible ? <> · <span className="tone-agent">QBI</span></> : null}
                        {e.qbi_deduction_cents > 0 ? ` ${centsToUSD(e.qbi_deduction_cents)}` : ""}
                      </div>
                    </div>
                    {/* [additive: AO sync for YTD figure] */}
                    <span className="font-mono text-[10px] text-[var(--g-ink-3)]">[AO sync: additive]</span>
                  </div>
                ))}
              </>
            ) : (
              <div className="px-5 py-4">
                <p className="text-[12.5px] text-[var(--g-ink-3)]">
                  No entities detected on this file.
                </p>
                <p className="mt-1.5 font-mono text-[10px] text-[var(--g-ink-3)]">
                  {/* TODO(integration: GET /clients/:id/business-entities + AO sync, spec §7-08) */}
                  <span className="tone-cost">[additive]</span> the structure map (AO-synced YTD, salary curve) lands with spec §9.2 + §7-08.
                </p>
              </div>
            )}
            {myClientId ? (
              <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10px] text-[var(--g-ink-3)]">
                <span className="tone-cost">[additive]</span> YTD + books-pace flag from AO federation (spec §7-08).
              </div>
            ) : null}
          </Panel>

          {/* ---- your estimates: just YOUR four quarters, no cross-client season ---- */}
          <Panel>
            <PanelHead>
              <MicroLabel>Your estimates · {planYear.tax_year}</MicroLabel>
              {allPaid ? (
                <Chip tone="save" className="ml-auto">on track ✓</Chip>
              ) : behindOnQuarter ? (
                <Chip tone="cost" className="ml-auto">check estimates ⚠</Chip>
              ) : null}
            </PanelHead>
            {quarterly.length > 0 ? (
              <>
                {quarterly.map((q) => {
                  const qinfo = QUARTER_LABELS[q.quarter] ?? { label: `Q${q.quarter}`, dueLabel: q.due_date };
                  const paid = q.payment_made_cents >= q.required_payment_cents;
                  const isEst = q.required_payment_cents > 0 && q.payment_made_cents === 0;
                  return (
                    <div key={q.quarter} className="flex justify-between border-t border-[var(--g-hairline-soft)] px-[18px] py-2 text-[12.5px] first:border-t-0">
                      <span>{qinfo.label} · {qinfo.dueLabel}</span>
                      <span className={`font-mono text-[10.5px] ${paid ? "tone-save" : isEst ? "text-[var(--g-ink-3)]" : "tone-cost"}`}>
                        {paid
                          ? `PAID ${centsToUSD(q.payment_made_cents)}`
                          : isEst
                            ? `${centsToUSD(q.required_payment_cents)} est`
                            : `UNDERPAID — ${centsToUSD(q.required_payment_cents - q.payment_made_cents)} short`}
                      </span>
                    </div>
                  );
                })}
                <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3 text-[11.5px] text-[var(--g-ink-3)]">
                  <Term k="safe-harbor">Safe harbor</Term>: pay at least this much to avoid the underpayment penalty. Your strategist watches for under/over-payment as the books update.
                </div>
              </>
            ) : (
              <>
                <div className="px-5 py-4 text-[12.5px] text-[var(--g-ink-3)]">
                  No quarterly estimates yet. The engine computes these from your confirmed return.
                </div>
                <div className="border-t border-[var(--g-hairline-soft)] px-5 py-2.5 font-mono text-[10px] text-[var(--g-ink-3)]">
                  <span className="tone-cost">[additive]</span> quarterly from GET /clients/{myClientId ?? ":id"}/quarterly when available.
                </div>
              </>
            )}
          </Panel>

          {/* ---- the case file / lab / memo quick links ---- */}
          {myClientId ? (
            <Panel className="p-4">
              <div className="grid grid-cols-3 gap-2 text-center text-[12px]">
                <Link href={`/c/${myClientId}`} className="mini-btn flex flex-col items-center gap-1 py-3">
                  <span className="text-[16px]">⊞</span>
                  <span>Case file</span>
                </Link>
                <Link href={`/c/${myClientId}/lab`} className="mini-btn flex flex-col items-center gap-1 py-3">
                  <span className="text-[16px]">⌁</span>
                  <span>Lab</span>
                </Link>
                <Link href={`/c/${myClientId}/memo`} className="mini-btn flex flex-col items-center gap-1 py-3">
                  <span className="text-[16px]">✍</span>
                  <span>Memo</span>
                </Link>
              </div>
            </Panel>
          ) : null}
        </div>
      </div>

      {/* ---- the filing year and plan stats bar ---- */}
      <section className="rise d3 mt-5 grid grid-cols-2 overflow-hidden rounded-[14px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)] md:grid-cols-4">
        <RateCell
          label={<Term k="nominal-bracket">nominal bracket</Term>}
          value={`${(nominal * 100).toFixed(0)}%`}
          detail={`${planYear.tax_year} · ${FILING[planYear.filing_status] ?? planYear.filing_status}`}
        />
        <RateCell
          hot
          label={<Term k="marginal-rate">true next-dollar</Term>}
          value="—"
          detail="EMR sweep — additive (spec §9.3)"
        />
        <RateCell
          label={<Term k="effective-rate">average rate</Term>}
          value={`${(Number(snap.effective_rate) * 100).toFixed(1)}%`}
          detail={`tax ${centsToUSD(headlineTax)} ÷ income ${centsToUSD(snap.total_income_cents)}`}
        />
        <RateCell
          label="your plan savings"
          value={identified > 0 ? <Money cents={identified} tone="save" /> : "—"}
          detail={identified > 0 ? `${signedCount} signed · ${overview.strategies.length} identified` : "run the strategist to identify savings"}
        />
      </section>

      {/* ---- omnibar at the base ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about your plan…" />
      </div>

      <footer className="mt-8 font-mono text-[9.5px] text-[var(--g-ink-3)]">
        Surface 14 — Your Plan (solo / company posture) · your file: {overview.client.display_name}
        {/* TODO(integration: posture resolver spec §7-14 + workspace switcher) — v1 uses first client; full file selection additive */}
        {" "}&nbsp;·&nbsp; <span className="tone-cost">[additive]</span> posture resolver (solo vs firm), workspace switcher (you / your company / a firm).
      </footer>
    </div>
  );
}

/* ---- rate cell (the three-rate cluster row) ---- */
function RateCell({ label, value, detail, hot }: { label: ReactNode; value: ReactNode; detail: ReactNode; hot?: boolean }) {
  return (
    <div className={`border-l border-[var(--g-hairline-soft)] px-5 py-3.5 first:border-l-0 ${hot ? "bg-[linear-gradient(180deg,rgba(201,114,67,0.10),transparent)]" : ""}`}>
      <MicroLabel>{label}</MicroLabel>
      <div className={`mt-1.5 text-[26px] font-bold leading-none tracking-[-0.02em] ${hot ? "tone-cost" : ""}`}>{value}</div>
      <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">{detail}</div>
    </div>
  );
}

/* ---- queue icon glyph (the type indicator) ---- */
function QueueIcon({ type }: { type: "memo" | "ao" | "task" }) {
  const styles: Record<typeof type, string> = {
    memo: "bg-[var(--seal-soft)] text-[var(--seal)] border-[color-mix(in_srgb,var(--seal)_30%,transparent)]",
    ao:   "bg-[var(--agent-soft)] text-[var(--agent)] border-[color-mix(in_srgb,var(--agent)_30%,transparent)]",
    task: "bg-[var(--cost-soft)] text-[var(--cost)] border-[color-mix(in_srgb,var(--cost)_30%,transparent)]",
  };
  const glyphs: Record<typeof type, string> = { memo: "✍", ao: "⇄", task: "◷" };
  return (
    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border text-[13px] ${styles[type]}`}>
      {glyphs[type]}
    </span>
  );
}
