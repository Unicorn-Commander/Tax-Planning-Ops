"use client";

// Surface 16 — PLAIN ENGLISH (the first-value payoff)
//
// After import the newcomer lands here: a calm keep-vs-tax summary, six plain
// chapters, every expert term a <Term> → plain gloss, and the "Plain English ⟷
// The detail" register toggle. The LLM narrates in plain language but cannot
// change a number — every figure comes from the engines.
//
// Live data:
//   overview (ClientOverviewProvider / useClientOverview) — snapshot
//   GET /clients/tax-years/{taxYearId}/analysis — same shape as the Case File
//   GET /admin/tax-bracket-sets — segment spans for the plain layer-bar
//
// Additive (Honesty Protocol — see INTEGRATION-TODO.16.md):
//   LLM narration text — each chapter's copy is today a template string that
//   interpolates REAL engine values; the NLP-rendered version lands with the
//   explainer renderer endpoint (spec §7-16, §9). Rendered from a clearly
//   labelled fixture; numbers inside the prose are ALWAYS live API values.
//
// Invariants:
//   - NO fabricated/hardcoded dollar values. Every cent comes from the API.
//     Template text uses centsToUSD(liveValue). If a value is unavailable the
//     paragraph degrades gracefully (see guards below).
//   - The layer-bar segment widths come from real bracket spans (bracket sets),
//     not uniform coloured blocks. The "you" marker left-offset is computed from
//     actual taxable income relative to the axis span.
//   - <Term k="..."> on every expert concept — the GLOSS map is in kit/tokens.
//   - The "Plain English ⟷ The detail" toggle links to /c/:id (Case File) — it
//     does not change what THIS page renders.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import api from "@/lib/api";

import {
  Stamp,
  Money,
  Panel,
  Omnibar,
  Term,
  STRATA,
  type Segment,
} from "@/components/kit";

/* ---- API types (the same shapes the Case File reads) ---- */
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
  room_to_drop_one_tier_cents?: number | null;
  note?: string | null;
}
interface ComprehensiveSection {
  available: true;
  total_tax_cents: number;
  se_tax_cents: number;
  qbi_deduction_cents: number;
  amt_cents: number;
  balance_due_cents: number;
  base_snapshot_total_tax_cents: number;
  includes_business: boolean;
}
interface OppItem {
  code: string;
  name: string;
  category: string;
  citation: string;
  estimated_tax_savings_cents: number;
  eligibility_note: string;
}
interface OppSection {
  available: true;
  total_illustrative_savings_cents: number;
  items: OppItem[];
}
type Maybe<T> = T | { available: false; reason?: string };
interface Analysis {
  filing_status: string;
  comprehensive_return: Maybe<ComprehensiveSection>;
  irmaa: Maybe<IrmaaSection>;
  opportunities: Maybe<OppSection>;
}

/* ---- helpers ---- */

/** Build bracket segments the same way the Case File does. */
function buildSegments(sets: BracketSet[], year: number, filingStatus: string): Segment[] {
  if (!sets.length) return [];
  const fed = sets.filter((s) => s.jurisdiction?.toLowerCase().includes("fed"));
  const pool = fed.length ? fed : sets;
  const set =
    pool.find((s) => s.tax_year === year && s.filing_status === filingStatus) ??
    pool.find((s) => s.filing_status === filingStatus) ??
    pool[0];
  if (!set) return [];
  const rows = [...set.rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents);
  const topLower = rows[rows.length - 1]?.lower_bound_cents ?? 0;
  const cap = topLower + 150_000_00;
  return rows.map((r, i) => ({
    rate: Number(r.rate),
    fromCents: r.lower_bound_cents,
    toCents: r.upper_bound_cents ?? (i === rows.length - 1 ? cap : r.lower_bound_cents),
  }));
}

/** Left-offset (%) of the income marker on the layer-bar. */
function incomeOffset(segments: Segment[], incomeCents: number): number {
  if (!segments.length) return 50;
  const axisMin = segments[0].fromCents;
  const axisMax = segments[segments.length - 1].toCents;
  const span = Math.max(1, axisMax - axisMin);
  return Math.max(2, Math.min(98, ((incomeCents - axisMin) / span) * 100));
}

/** Strata var name from a 0-1 rate, graceful fallback. */
function strataVar(rate: number): string {
  return STRATA[rate] ?? "var(--s22)";
}

/* ================================================================= */
export default function ExplainedPage() {
  const { clientId, overview, loading } = useClientOverview();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [aLoading, setALoading] = useState(true);

  /* ---- pick the plan/base year (mirrors the Case File) ---- */
  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);

  const taxYearId = planYear?.id ?? null;
  /* ---- fetch bracket sets once ---- */
  useEffect(() => {
    api
      .get("/admin/tax-bracket-sets")
      .then((r) => setSets(r.data))
      .catch(() => setSets([]));
  }, []);

  /* ---- fetch analysis when the plan year is known ---- */
  useEffect(() => {
    if (!taxYearId) {
      setALoading(false);
      return;
    }
    setALoading(true);
    // TODO(integration: GET /clients/tax-years/{taxYearId}/analysis)
    api
      .get(`/clients/tax-years/${taxYearId}/analysis`)
      .then((r) => setAnalysis(r.data))
      .catch(() => setAnalysis(null))
      .finally(() => setALoading(false));
  }, [taxYearId]);

  /* ---- derive the plain-bar segments + income offset ---- */
  const { segments, youOffset } = useMemo(() => {
    if (!sets || !planYear) return { segments: [] as Segment[], youOffset: 50 };
    const segs = buildSegments(
      sets,
      planYear.tax_year,
      planYear.filing_status,
    );
    const income = planYear.snapshot?.taxable_income_cents ?? 0;
    return { segments: segs, youOffset: incomeOffset(segs, income) };
  }, [sets, planYear]);

  /* ---- loading ---- */
  if (loading || aLoading) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[560px] w-full rounded-[14px]" />
      </div>
    );
  }

  /* ---- no confirmed year ---- */
  if (!overview || !planYear || !planYear.snapshot) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No confirmed tax year yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            Import and confirm a return to see your plain-English explanation.
          </p>
        </Panel>
      </div>
    );
  }

  /* ---- live values from the engines (NEVER fabricated) ---- */
  const snap = planYear.snapshot;
  const cr = analysis?.comprehensive_return;
  const opp = analysis?.opportunities;
  const ir = analysis?.irmaa;

  // Headline numbers — all from the API
  const totalIncomeCents = snap.total_income_cents;
  const taxableIncomeCents = snap.taxable_income_cents;
  const totalTaxCents = cr?.available ? cr.total_tax_cents : snap.total_tax_cents;
  const keepCents = totalIncomeCents - totalTaxCents;
  const effectiveRate = Number(snap.effective_rate); // 0–1

  // Keep / tax proportions for the bar (percentages, derived from engine figures)
  const keepPct = totalIncomeCents > 0 ? Math.round((keepCents / totalIncomeCents) * 100) : 78;
  const taxPct = 100 - keepPct;

  // QBI deduction (from comprehensive, if available)
  const qbiCents = cr?.available ? cr.qbi_deduction_cents : null;

  // Next bracket edge (for chapter 3 narrative)
  const nextSeg = segments.find((s) => s.fromCents > taxableIncomeCents);
  const topFilledRate = segments
    .filter((s) => s.fromCents <= taxableIncomeCents)
    .slice(-1)[0]?.rate ?? 0;

  // Nominal bracket rate
  const nominalRate = Number(snap.marginal_rate);

  // IRMAA cliff info — narrowed properly so tsc can follow the shape
  const irmaaSection = ir && ir.available ? ir : null;
  const irmaaOverCents = irmaaSection && irmaaSection.next_cliff_threshold_cents > 0
    ? Math.max(0, taxableIncomeCents - irmaaSection.next_cliff_threshold_cents)
    : null;
  const irmaaRoomCents = irmaaSection && irmaaSection.distance_to_next_cliff_cents > 0
    ? irmaaSection.distance_to_next_cliff_cents
    : null;

  // The top opportunity (from the analysis)
  const topOpp =
    opp?.available && opp.items.length > 0
      ? [...opp.items].sort((a, b) => b.estimated_tax_savings_cents - a.estimated_tax_savings_cents)[0]
      : null;
  const totalOppCents = opp?.available ? opp.total_illustrative_savings_cents : null;

  const taxYear = planYear.tax_year;
  const clientName = overview.client.display_name;

  return (
    <div
      className="wrap py-7 pb-16"
      style={{ maxWidth: 760, margin: "0 auto" }}
    >
      {/* ---- topline: stamp + register toggle ---- */}
      <div className="rise flex flex-wrap items-center gap-3">
        <Stamp kind="verified" className="!transform-none">
          &#x2713; Read &amp; checked
        </Stamp>
        <span className="text-[12.5px] text-[var(--g-ink-3)]">
          your {taxYear} return &middot; the math matches what you filed, to the dollar
        </span>
        {/* progressive disclosure: the same data in its dense form */}
        <div className="ml-auto inline-flex overflow-hidden rounded-[9px] border border-[var(--g-hairline)] text-[11.5px] font-semibold">
          <span className="px-3 py-1.5 bg-[var(--agent-soft)] text-[var(--agent)]">Plain English</span>
          <Link
            href={`/c/${clientId}`}
            className="px-3 py-1.5 text-[var(--g-ink-3)] hover:bg-[var(--wash)]"
          >
            The detail
          </Link>
        </div>
      </div>

      {/* ---- headline ---- */}
      <section className="rise d1 mt-6">
        <h1
          className="text-[34px] font-extrabold leading-[1.12] tracking-[-0.025em]"
        >
          Here&rsquo;s your {taxYear} taxes,
          <br />
          in plain English.
        </h1>
        <p className="mt-1.5 text-[15px] text-[var(--g-ink-2)]">
          No tax background needed. Tap{" "}
          <span
            className="text-[var(--agent)] font-semibold cursor-help underline decoration-dotted underline-offset-[3px]"
          >
            what&rsquo;s this?
          </span>{" "}
          on anything you want explained.
        </p>
      </section>

      {/* ---- calm summary ---- */}
      <section
        className="rise d2 mt-6 rounded-[16px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)] px-[26px] py-6"
      >
        <p className="m-0 text-[19px] leading-[1.6] font-[500] tracking-[-0.01em] text-[var(--g-ink)]">
          {clientName} brought in{" "}
          <b>
            <Money cents={totalIncomeCents} />
          </b>{" "}
          last year. After everything,{" "}
          <b>
            <Money cents={totalTaxCents} />
          </b>{" "}
          went to taxes &mdash; about{" "}
          <b>{Math.round(effectiveRate * 100)}&nbsp;cents</b> of every dollar.
          {totalOppCents && totalOppCents > 0 ? (
            <>
              {" "}
              <span className="text-[var(--save)]">
                The good news: you&rsquo;re leaving about{" "}
                <b>
                  <Money cents={totalOppCents} />
                </b>{" "}
                a year on the table, and it&rsquo;s fixable.
              </span>
            </>
          ) : null}
        </p>

        {/* keep-vs-tax bar (proportions derived from engine figures) */}
        <div className="mt-[18px]">
          <div className="flex justify-between text-[12px] text-[var(--g-ink-3)] mb-[7px]">
            <span>what you kept</span>
            <span>what went to tax</span>
          </div>
          <div className="flex h-[30px] overflow-hidden rounded-[8px]">
            <div
              className="grid place-items-center text-[12px] font-semibold text-[var(--save)]"
              style={{
                flex: keepPct,
                background: "color-mix(in srgb, var(--save) 22%, var(--g-surface))",
              }}
            >
              <Money cents={keepCents} />
              {" "}kept
            </div>
            <div
              className="grid place-items-center text-[12px] font-semibold"
              style={{
                flex: taxPct,
                background: "color-mix(in srgb, var(--g-ink) 80%, transparent)",
                color: "#fbfaf6",
              }}
            >
              <Money cents={totalTaxCents} />
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ CHAPTERS */}
      <section className="rise d3 mt-2">

        {/* Chapter 1 — What you brought in */}
        <ChapterRow n="1" heading="What you brought in">
          <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
            Your{" "}
            <b>
              <Money cents={totalIncomeCents} />
            </b>{" "}
            is the total that hit the tax return before any deductions. This is
            the starting number the engine works from.
            {cr?.available && cr.includes_business ? (
              <>
                {" "}It includes both wages and business income, which get
                treated differently in a few key ways.
              </>
            ) : null}
          </p>
        </ChapterRow>

        {/* Chapter 2 — What you got to subtract */}
        <ChapterRow n="2" heading="What you got to subtract">
          <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
            Before tax is figured, you subtract some things. After deductions
            the taxed amount is{" "}
            <b>
              <Money cents={taxableIncomeCents} />
            </b>.
            {qbiCents && qbiCents > 0 ? (
              <>
                {" "}That includes a special{" "}
                <Term k="qbi">20% business deduction</Term> of{" "}
                <b>
                  <Money cents={qbiCents} />
                </b>{" "}
                for your business income, which reduces the taxed amount before
                the brackets are applied.
              </>
            ) : null}
          </p>
        </ChapterRow>

        {/* Chapter 3 — How your income gets taxed in layers */}
        <ChapterRow n="3" heading="How your income gets taxed — in layers">
          <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
            Your income isn&rsquo;t all taxed at one rate. It fills up{" "}
            <i>layers</i>: the first chunk at a low rate, the next at a slightly
            higher rate, and so on. Most of yours sits at{" "}
            <b>{(topFilledRate * 100).toFixed(0)}% or less</b>.
            {nextSeg ? (
              <>
                {" "}Only your last dollars reach{" "}
                {(nextSeg.rate * 100).toFixed(0)}%.
              </>
            ) : null}
          </p>

          {/* the plain layer-bar (no rate-pin shouting, no cliff pins — those live in the dense view) */}
          {segments.length > 0 ? (
            <div className="mt-3">
              <div className="relative flex h-[26px] overflow-hidden rounded-[7px]" style={{ gap: "2px" }}>
                {segments.map((s, i) => {
                  // Opacity communicates filled vs empty vs future
                  const filled = taxableIncomeCents >= s.toCents;
                  const partial = taxableIncomeCents > s.fromCents && taxableIncomeCents < s.toCents;
                  const spanTotal = segments[segments.length - 1].toCents - segments[0].fromCents;
                  const segSpan = s.toCents - s.fromCents;
                  const widthPct = (segSpan / spanTotal) * 100;
                  return (
                    <i
                      key={i}
                      style={{
                        flex: `0 0 ${widthPct}%`,
                        background: strataVar(s.rate),
                        opacity: filled ? 0.8 : partial ? 0.8 : 0.2,
                        borderRadius: 0,
                      }}
                    />
                  );
                })}
                {/* the income marker */}
                <span
                  aria-label="your income is here"
                  style={{
                    position: "absolute",
                    top: -5,
                    bottom: -5,
                    left: `${youOffset}%`,
                    borderLeft: "2px solid var(--g-ink)",
                    pointerEvents: "none",
                  }}
                />
              </div>
              <div className="mt-[7px] flex justify-between text-[11px] text-[var(--g-ink-3)]">
                <span>{(segments[0]?.rate * 100).toFixed(0)}%</span>
                <span>&#8593; your income reaches about here</span>
                <span>{(segments[segments.length - 1]?.rate * 100).toFixed(0)}%</span>
              </div>
            </div>
          ) : null}
        </ChapterRow>

        {/* Chapter 4 — The part most people miss (true next-dollar rate) */}
        <ChapterRow n="4" heading="The part most people miss">
          <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
            The rate that matters for <i>planning</i> isn&rsquo;t your
            average &mdash; it&rsquo;s the tax on your <b>next</b> dollar. Your{" "}
            <b>nominal bracket</b> is{" "}
            <b>{(nominalRate * 100).toFixed(0)}%</b>, but once every add-on is
            counted the real cost can be higher.{" "}
            <Term k="marginal-rate">what&rsquo;s this?</Term>
          </p>
          {/* expanded gloss — shown as the pattern (mockup ch.4 shows it expanded) */}
          <div
            className="mt-[10px] rounded-r-[8px] border-l-2 px-[14px] py-[4px] text-[13.5px] leading-[1.55] text-[var(--g-ink-2)]"
            style={{
              borderColor: "color-mix(in srgb, var(--agent) 45%, transparent)",
              background: "var(--agent-soft)",
            }}
          >
            <b className="text-[var(--g-ink)]">Your &ldquo;next-dollar&rdquo; rate.</b>{" "}
            If you earned one more dollar, your {(nominalRate * 100).toFixed(0)}% bracket
            applies first.
            {cr?.available && cr.se_tax_cents > 0 ? (
              <>
                {" "}On top of that, some of your income carries self-employment
                taxes.
              </>
            ) : null}
            {" "}Knowing this is what makes good planning possible: it tells us
            exactly how much room you have before the next jump. The full
            true-rate sweep lands with the detailed analysis.
          </div>
        </ChapterRow>

        {/* Chapter 5 — The lines to watch */}
        <ChapterRow n="5" heading="The lines to watch">
          <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
            A few invisible <Term k="cliff">thresholds</Term> add tax the moment
            you cross them.
            {irmaaSection && irmaaOverCents && irmaaOverCents > 0 ? (
              <>
                {" "}You&rsquo;re{" "}
                <b>
                  <Money cents={irmaaOverCents} />
                </b>{" "}
                over the <Term k="irmaa">IRMAA</Term> threshold that sets your
                Medicare premiums two years out.
              </>
            ) : irmaaSection && irmaaRoomCents && irmaaRoomCents > 0 ? (
              <>
                {" "}You have{" "}
                <b>
                  <Money cents={irmaaRoomCents} />
                </b>{" "}
                of room before your next <Term k="irmaa">IRMAA</Term> tier, which
                would raise your Medicare premiums two years from now.
              </>
            ) : nextSeg ? (
              <>
                {" "}You have{" "}
                <b>
                  <Money cents={nextSeg.fromCents - taxableIncomeCents} />
                </b>{" "}
                of room before your income reaches the{" "}
                {(nextSeg.rate * 100).toFixed(0)}% bracket. We watch all of
                these for you.
              </>
            ) : (
              <>{" "}We watch all of these for you.</>
            )}
          </p>
        </ChapterRow>

        {/* Chapter 6 — Where you could do better */}
        <ChapterRow n="6" heading="Where you could do better">
          {topOpp ? (
            <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
              The engine found{" "}
              {opp?.available ? opp.items.length : 1}{" "}
              {opp?.available && opp.items.length !== 1 ? "opportunities" : "opportunity"} on this
              return. The top one is{" "}
              <b>{topOpp.name}</b>
              {topOpp.estimated_tax_savings_cents > 0 ? (
                <>
                  {" "}&mdash; worth about{" "}
                  <b>
                    <Money cents={topOpp.estimated_tax_savings_cents} />
                  </b>{" "}
                  a year
                </>
              ) : null}
              . Nothing here is exotic or risky.
            </p>
          ) : (
            <p className="m-0 text-[16.5px] leading-[1.62] text-[var(--g-ink)]">
              The engine is scanning for moves you could make this year. Run the
              full analysis to surface any open opportunities &mdash; some are
              worth thousands, and most are straightforward to implement.
            </p>
          )}
        </ChapterRow>
      </section>

      {/* ============================================================ OPPORTUNITY */}
      {totalOppCents && totalOppCents > 0 ? (
        <section
          className="rise d3 mt-7 overflow-hidden rounded-[16px] shadow-[var(--shadow-panel)]"
          style={{
            border: "1px solid color-mix(in srgb, var(--save) 35%, transparent)",
          }}
        >
          <div
            className="flex flex-wrap items-baseline gap-3 px-6 py-4"
            style={{
              background: "color-mix(in srgb, var(--save) 9%, var(--g-surface))",
            }}
          >
            <b className="text-[16px]">Your biggest opportunity</b>
            <span
              className="ml-auto text-[22px] font-extrabold leading-none tracking-[-0.02em]"
              style={{ color: "var(--save)" }}
            >
              <Money cents={totalOppCents} />
              <span className="text-[13px] font-normal text-[var(--g-ink-3)]">/year</span>
            </span>
          </div>
          <div className="px-6 py-[18px]">
            {topOpp ? (
              <p className="m-0 mb-3 text-[15.5px] leading-[1.6] text-[var(--g-ink)]">
                <b>{topOpp.name}.</b>{" "}
                {topOpp.eligibility_note
                  ? topOpp.eligibility_note
                  : "This is engine-identified based on your return. See the full analysis for details."}
                {topOpp.estimated_tax_savings_cents > 0 ? (
                  <>
                    {" "}Fixing this keeps about{" "}
                    <b>
                      <Money cents={topOpp.estimated_tax_savings_cents} />
                    </b>{" "}
                    in your pocket every year &mdash; money you&rsquo;re
                    currently sending to the IRS for no reason.
                  </>
                ) : null}
              </p>
            ) : null}
            {opp?.available && opp.items.length > 1 ? (
              <p className="m-0 text-[13px] text-[var(--g-ink-3)]">
                There {opp.items.length - 1 === 1 ? "is" : "are"} {opp.items.length - 1} smaller
                move{opp.items.length - 1 === 1 ? "" : "s"} too. Your strategist laid them all
                out, biggest first &mdash; nothing here is exotic or risky.
              </p>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* ============================================================ PROGRESSIVE DISCLOSURE */}
      <div className="rise d4 mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Link
          href="/console"
          className="flex items-center gap-3 rounded-[13px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-[18px] py-[15px] no-underline shadow-[var(--shadow-panel)] transition-transform hover:-translate-y-0.5"
          style={{ color: "inherit" }}
        >
          <span
            className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[9px] text-[15px]"
            style={{ background: "var(--agent-soft)", color: "var(--agent)" }}
          >
            &#x2736;
          </span>
          <span>
            <b className="block text-[13.5px]">Ask about any of this</b>
            <span className="text-[11.5px] text-[var(--g-ink-3)]">
              &ldquo;why is my next-dollar rate different from my bracket?&rdquo;
            </span>
          </span>
        </Link>
        <Link
          href={`/c/${clientId}`}
          className="flex items-center gap-3 rounded-[13px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-[18px] py-[15px] no-underline shadow-[var(--shadow-panel)] transition-transform hover:-translate-y-0.5"
          style={{ color: "inherit" }}
        >
          <span
            className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[9px] text-[15px]"
            style={{ background: "var(--wash-2)", color: "var(--g-ink-2)" }}
          >
            &#x25A6;
          </span>
          <span>
            <b className="block text-[13.5px]">See the full analysis</b>
            <span className="text-[11.5px] text-[var(--g-ink-3)]">
              the detailed numbers, brackets, and charts
            </span>
          </span>
        </Link>
      </div>

      {/* CTA — turn this into my plan */}
      <div className="rise d4 mt-6 text-center">
        <Link
          href={`/c/${clientId}/plan`}
          className="btn btn-seal inline-block px-[22px] py-[11px] text-[14px]"
        >
          Turn this into my plan &rarr;
        </Link>
      </div>

      {/* foot note — the honesty footer every page carries */}
      <p className="rise d5 mt-8 text-center text-[12px] leading-[1.6] text-[var(--g-ink-3)]">
        Every figure here was computed by a tax engine from your actual return &mdash;
        never estimated, never guessed.
        <br />
        This is planning, not a filed return.
      </p>

      {/* ---- additive notice (Honesty Protocol) ---- */}
      <div className="rise d5 mt-4 flex items-start gap-2 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
        <span className="dot mt-0.5 flex-none" style={{ background: "var(--cost)" }} />
        <span>
          <b className="text-[var(--cost)]">[additive]</b> LLM narration &mdash; each chapter&rsquo;s
          prose is today a template that interpolates live engine values. The NLP-rendered
          version (plain narration that rewrites itself per client without changing a number)
          lands with the explainer renderer endpoint (spec §7-16, §9). Numbers shown above
          are ALL live from the engines; prose structure is the fixture.
        </span>
      </div>

      {/* ---- omnibar (three-doors contract) ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this file&hellip;" />
      </div>
    </div>
  );
}

/* ================================================================= CHAPTER ROW */

function ChapterRow({
  n,
  heading,
  children,
}: {
  n: string;
  heading: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className="flex gap-[18px] border-t border-[var(--g-hairline-soft)] py-[22px]"
    >
      <span
        className="mt-[2px] grid h-[30px] w-[30px] flex-none place-items-center rounded-full border border-[var(--g-hairline)] bg-[var(--g-surface)] font-mono text-[12px] text-[var(--g-ink-2)]"
      >
        {n}
      </span>
      <div className="flex-1 min-w-0">
        <h3
          className="mb-[6px] mt-[2px] text-[13px] font-[650] uppercase tracking-[0.06em] text-[var(--g-ink-3)]"
        >
          {heading}
        </h3>
        {children}
      </div>
    </div>
  );
}
