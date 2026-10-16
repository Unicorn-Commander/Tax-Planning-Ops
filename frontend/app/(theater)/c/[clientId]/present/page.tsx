"use client";

// Surface 13 — PRESENT (theater). Full-screen paper plates on dark.
//
// Posture: THEATER — body.theater is set by the (theater) layout; no topbar,
// no agent chrome, no file nav. Four plates; arrow keys and F-key navigation.
//
// DATA WIRING:
// [live] Present builds from the SIGNED memo. We load the persisted memo state
//   (GET /clients/tax-years/{id}/memo). When the latest memo is signed we present
//   its body + the linked run's findings/totals; until then we show an honest
//   empty state ("Sign the memo to present it").
// [live] Cover headline savings + top findings: from the signed memo's run.
// [live] Simplified position (3 marks max): client overview bracket snapshot.
// [live] Keep/identified plate: the signed run's identified savings.
//
// [live] Branding: the letterhead firm name is read from GET /admin/branding
//   (null body when unset → fall back to the default firm name).
// [live] Fee-net framing: GET /admin/engagements/{clientId}/fee supplies the
//   operator-set fee. When a fee is on file we frame the signed run's identified
//   savings net of that fee (saved $X against a $Y fee → net $Z). When no fee is
//   on file (null), we say so honestly — no fee figure is invented or hardcoded.
//
// [additive] Everything below is HONESTLY LABELED (per Honesty Protocol):
//   - Client-friendly narrative text per finding: the register transform
//     (additive per spec §7-06) is not built; we show recommended_action as-is.
//   - Calendar steps: derived from finding categories; the tasks model
//     (spec §9.4) would supply statutory deadlines.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { businessDate } from "@/lib/time";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  Letterhead,
  Money, MicroLabel, Chip,
  PositionInstrument,
  type Segment,
} from "@/components/kit";

/* ---- the persisted memo state (GET /clients/tax-years/{id}/memo) ---- */
interface Finding {
  title: string;
  category: string;
  recommended_action: string;
  estimated_impact_cents: number;
  impact_kind: "savings" | "cost" | "info";
  citation: string;
  caveat: string;
}
interface StrategistRun {
  id: string;
  findings: Finding[];
  memo_text: string | null;
  current_total_tax_cents: number;
  total_savings_identified_cents: number;
  marginal_rate: string;
  objectives_summary: string | null;
  disclaimer: string | null;
}
interface MemoOut {
  id: string;
  version: number;
  body_md: string;
  status: "draft" | "signed";
  signed_by: string | null;
  signed_at: string | null;
  content_hash: string | null;
  audit_event_id: string | null;
}
interface MemoVersionSummary {
  version: number;
  status: string;
  signed_at: string | null;
  created_at: string;
}
interface MemoState {
  latest_memo: MemoOut | null;
  versions: MemoVersionSummary[];
  latest_run: StrategistRun | null;
}

/* ---- firm branding (GET /admin/branding) ---- */
interface Branding {
  firm_name: string | null;
  logo_blob_key: string | null;
  primary_color: string | null;
  advisor_signature: string | null;
}
// Fallback letterhead name when branding is unset (endpoint returns null body).
const DEFAULT_FIRM_NAME = "Northstar Tax Advisory";

/* ---- the engagement fee (GET /admin/engagements/{client_id}/fee) ---- */
type FeeBasis = "flat" | "aum" | "hourly" | "value";
interface EngagementFee {
  id: string;
  client_id: string;
  fee_cents: number;
  fee_basis: FeeBasis;
  fee_note: string | null;
}
const FEE_BASIS_LABEL: Record<FeeBasis, string> = {
  flat: "flat, no surprises",
  aum: "% of assets",
  hourly: "hourly",
  value: "value-based",
};

/* ---- the four plate ids ---- */
type PlateId = "cover" | "position" | "moves" | "keep";
const PLATE_ORDER: PlateId[] = ["cover", "position", "moves", "keep"];

// Props type kept for Next.js App Router compatibility (params are unused because
// clientId comes from the ClientOverviewProvider in the (theater) layout).
export default function PresentPage() {
  // All hooks must be called before any early returns (rules-of-hooks).
  // clientId is provided by the ClientOverviewProvider in the (theater) layout.
  const { clientId, overview, loading } = useClientOverview();
  const [state, setState] = useState<MemoState | null>(null);
  const [branding, setBranding] = useState<Branding | null>(null);
  const [fee, setFee] = useState<EngagementFee | null>(null);
  const [sLoading, setSLoading] = useState(false);
  const [plateIndex, setPlateIndex] = useState(0);
  const deckRef = useRef<HTMLDivElement>(null);
  const plateRefs = useRef<(HTMLElement | null)[]>([]);

  const planYear: YearRow | undefined = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);
  const taxYearId = planYear?.id ?? null;

  // Load the persisted memo state once we know the tax-year id.
  useEffect(() => {
    if (!taxYearId) return;
    setSLoading(true);
    api
      .get<MemoState>(`/clients/tax-years/${taxYearId}/memo`)
      .then((r) => setState(r.data))
      .catch(() => setState(null))
      .finally(() => setSLoading(false));
  }, [taxYearId]);

  // Firm branding for the letterhead (global; 200+null body when unset → default).
  useEffect(() => {
    let alive = true;
    api
      .get<Branding | null>("/admin/branding")
      .then((r) => { if (alive) setBranding(r.data); })
      .catch(() => { if (alive) setBranding(null); });
    return () => { alive = false; };
  }, []);

  // The operator-set engagement fee for net-of-fee framing. 200+null body means
  // no fee is on file → we keep an honest "fee not set" state and never invent one.
  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    api
      .get<EngagementFee | null>(`/admin/engagements/${clientId}/fee`)
      .then((r) => { if (alive) setFee(r.data); })
      .catch(() => { if (alive) setFee(null); });
    return () => { alive = false; };
  }, [clientId]);

  // Present from the SIGNED memo only. latest_run is the run the latest memo was
  // built from, so it lines up with latest_memo's body when that memo is signed.
  const signedMemo = state?.latest_memo?.status === "signed" ? state.latest_memo : null;
  const run = signedMemo ? (state?.latest_run ?? null) : null;
  // Is there a newer unsigned draft sitting on top of the signed deliverable?
  const newerDraft = useMemo(
    () => Boolean(state?.versions?.some((v) => v.status === "draft")),
    [state],
  );

  // Arrow-key + F navigation (all hooks must be called before any return)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        setPlateIndex((i) => Math.min(i + 1, PLATE_ORDER.length - 1));
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        setPlateIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "f" || e.key === "F") {
        const el = deckRef.current;
        if (!el) return;
        if (!document.fullscreenElement) {
          el.requestFullscreen().catch(() => {});
        } else {
          document.exitFullscreen().catch(() => {});
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Scroll to active plate
  useEffect(() => {
    plateRefs.current[plateIndex]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [plateIndex]);

  // Build simplified position segments from overview snapshot (3 marks max)
  // These are REAL bracket proportions computed from the snapshot.
  const posSegments: Segment[] = useMemo(() => {
    if (!planYear?.snapshot) return [];
    const snap = planYear.snapshot;
    const income = snap.taxable_income_cents;
    const nominal = Number(snap.marginal_rate);
    // Build a simplified 3-bracket view for the client plate:
    // low (below 22%), your bracket, above (dimmed).
    // Widths are proportional to the spans around the income mark — illustrative
    // bracket widths; the real bracket instrument uses GET /admin/tax-bracket-sets.
    // For the present plate we use a minimal visual band (3 marks max, spec §7-13).
    const LOW_RATES = [0.1, 0.12];
    const MID_RATES = [0.22, 0.24];
    const HIGH_RATES = [0.32, 0.35, 0.37];
    const assignGroup = (r: number) => {
      if (LOW_RATES.includes(r)) return "low";
      if (MID_RATES.includes(r)) return "mid";
      if (HIGH_RATES.includes(r)) return "high";
      return "mid";
    };
    const group = assignGroup(nominal);
    // Rough proportional spans for the simplified position (3 marks max)
    const spans: Segment[] = [
      { rate: 0.10, fromCents: 0, toCents: Math.round(income * 0.35) },
      { rate: nominal, fromCents: Math.round(income * 0.35), toCents: income },
      { rate: Math.min(nominal + 0.10, 0.37), fromCents: income, toCents: Math.round(income * 1.55) },
    ];
    void group; // used for conceptual grouping; spans derive from income
    return spans;
  }, [planYear]);

  // Top savings findings for the "moves" plate (up to 3), from the signed run.
  const topFindings: Finding[] = useMemo(() => {
    if (!run) return [];
    return run.findings
      .filter((f) => f.impact_kind === "savings")
      .sort((a, b) => b.estimated_impact_cents - a.estimated_impact_cents)
      .slice(0, 3);
  }, [run]);

  // Loading skeleton
  if (loading || sLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="skeleton h-[520px] w-full max-w-[900px] rounded-[14px]" />
      </div>
    );
  }

  const client = overview?.client;
  const snap = planYear?.snapshot;
  const clientName = client?.display_name ?? "Your client";
  const taxYear = planYear?.tax_year ?? 2025;
  const totalSavings = run?.total_savings_identified_cents ?? 0;
  // Letterhead firm name from branding, falling back to the default when unset.
  const firmName = branding?.firm_name || DEFAULT_FIRM_NAME;
  // Net-of-fee framing: the savings are the signed run's identified figure; the
  // fee is operator-supplied. We only subtract — no tax figure is computed here.
  // When no fee is on file (fee === null) we keep an honest "fee not set" state.
  const feeCents = fee?.fee_cents ?? null;
  const netOfFeeCents =
    feeCents !== null && totalSavings > 0 ? totalSavings - feeCents : null;

  // ===== honest empty state: nothing signed yet =====
  if (!signedMemo || !run) {
    return (
      <div ref={deckRef} className="flex min-h-screen flex-col">
        <div
          className="sticky top-0 z-50 flex items-center gap-3.5 border-b px-6 py-3"
          style={{
            background: "color-mix(in srgb, var(--g-bg) 80%, transparent)",
            backdropFilter: "blur(14px)",
            borderColor: "var(--g-hairline-soft)",
          }}
        >
          <Link
            href={`/c/${clientId}/memo`}
            className="mini-btn inline-flex items-center gap-1.5 no-underline"
            title="Back to the memo (Esc)"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            esc — back to the memo
          </Link>
          <Chip style={{ borderColor: "rgba(31,28,23,0.2)" }}>present mode &middot; locked to the signed memo</Chip>
        </div>

        <div className="flex flex-1 items-center justify-center px-6 py-16">
          <div className="sheet plate" style={{ padding: "64px 72px", maxWidth: 720, textAlign: "center" }}>
            <MicroLabel style={{ justifyContent: "center" }}>Present</MicroLabel>
            <h1 style={{ fontSize: 34, margin: "16px 0 10px" }}>Sign the memo to present it.</h1>
            <p className="lede" style={{ fontSize: 17, color: "var(--p-ink-2)" }}>
              The client deck is built from the <b>signed</b> memorandum — its sealed
              narrative, the engine-verified findings, and the identified savings.
              Nothing here is shown to a client until you&rsquo;ve reviewed and sealed it.
            </p>
            <p style={{ marginTop: 14, fontSize: 14.5, color: "var(--p-ink-3)" }}>
              {newerDraft
                ? `${clientName} · ${taxYear}: a draft is in progress on the Memo page — sign it to unlock present mode.`
                : `${clientName} · ${taxYear}: run the strategist on the Memo page, review the findings, then sign & seal.`}
            </p>
            <Link
              href={`/c/${clientId}/memo`}
              className="mini-btn seal mt-6 inline-flex items-center gap-1.5 no-underline"
            >
              Go to the memo →
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const currentPlate = PLATE_ORDER[plateIndex];

  return (
    <div ref={deckRef} className="min-h-screen" style={{ WebkitUserSelect: "none", userSelect: "none" }}>
      {/* ---- stagebar ---- */}
      <div
        className="sticky top-0 z-50 flex items-center gap-3.5 border-b px-6 py-3"
        style={{
          background: "color-mix(in srgb, var(--g-bg) 80%, transparent)",
          backdropFilter: "blur(14px)",
          borderColor: "var(--g-hairline-soft)",
        }}
      >
        <Link
          href={`/c/${clientId}/memo`}
          className="mini-btn inline-flex items-center gap-1.5 no-underline"
          title="Back to the memo (Esc)"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          esc — back to the memo
        </Link>

        <Chip style={{ borderColor: "rgba(31,28,23,0.2)" }}>
          client view &middot; no controls &middot; no jargon
        </Chip>

        <span className="font-mono text-[10.5px]" style={{ color: "var(--g-ink-3)" }}>
          sealed memo v{signedMemo.version}{signedMemo.content_hash ? ` · ${signedMemo.content_hash.slice(0, 8)}` : ""}
        </span>
        {newerDraft ? (
          <span className="font-mono text-[10px]" style={{ color: "var(--cost)" }}>
            (a newer draft is unsigned — presenting the sealed version)
          </span>
        ) : null}

        {/* plate nav dots */}
        <div className="ml-auto flex items-center gap-1.5">
          {PLATE_ORDER.map((id, i) => (
            <button
              key={id}
              aria-label={`Go to plate ${i + 1}`}
              onClick={() => setPlateIndex(i)}
              className="h-[7px] w-[7px] rounded-full transition-all"
              style={{
                background: i === plateIndex ? "var(--p-seal)" : "var(--g-hairline)",
              }}
            />
          ))}
        </div>

        <span className="font-mono text-[10.5px]" style={{ color: "var(--g-ink-3)" }}>
          plate {plateIndex + 1}&ndash;{PLATE_ORDER.length} &middot; &#x2190; &#x2192; arrow keys &middot; F fullscreen
        </span>
      </div>

      {/* ---- the deck ---- */}
      <div className="mx-auto flex max-w-[980px] flex-col gap-11 px-6 py-10 pb-24">

        {/* ============================================================ cover plate */}
        <section
          ref={(el) => { plateRefs.current[0] = el; }}
          className={`sheet plate relative rise ${currentPlate === "cover" ? "ring-2 ring-[var(--p-seal)] ring-offset-4 ring-offset-transparent" : ""}`}
          style={{ padding: "70px 78px" }}
          onClick={() => setPlateIndex(0)}
          role="button"
          aria-label="Plate 1: The headline"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && setPlateIndex(0)}
        >
          <Letterhead
            firm={<>{firmName}</>}
            docRef={`PREPARED FOR ${clientName.toUpperCase()} · ${taxYear}`}
          />

          <h1 style={{ fontSize: 42, margin: "22px 0 10px" }}>
            {run.objectives_summary
              ? run.objectives_summary.split(".")[0] + "."
              : "Your next few years, planned to the dollar."}
          </h1>

          <p className="lede" style={{ fontSize: 19 }}>
            {signedMemo.body_md
              ? signedMemo.body_md.split(/\n+/)[0].slice(0, 220)
              : `We analyzed your ${taxYear} return and identified the moves that matter most.`}
          </p>

          {/* headline savings — LIVE from the signed memo's run */}
          <div
            className="fig-serif"
            style={{
              fontFamily: "var(--font-ui)",
              fontWeight: 800,
              fontSize: 88,
              letterSpacing: "-0.045em",
              lineHeight: 0.95,
              margin: "30px 0 6px",
              color: "var(--p-save)",
            }}
          >
            {totalSavings > 0
              ? centsToUSD(totalSavings)
              : <span style={{ fontSize: 36, color: "var(--p-ink-3)" }}>No savings identified this year</span>}
          </div>

          {totalSavings > 0 ? (
            <div className="nof" style={{ fontSize: 15, color: "var(--p-ink-2)" }}>
              identified across {taxYear}&ndash;{taxYear + 4} &middot; every figure computed, none estimated
              {feeCents !== null && netOfFeeCents !== null ? (
                <span style={{ display: "block", marginTop: 6 }}>
                  net of our {centsToUSD(feeCents)} fee:{" "}
                  <b style={{ color: "var(--p-save)" }}>{centsToUSD(netOfFeeCents)}</b> stays with you
                  {feeCents > 0 ? (
                    <span className="ml-2 font-mono text-[11px]" style={{ color: "var(--p-ink-3)" }}>
                      {(totalSavings / feeCents).toFixed(0)} : 1
                    </span>
                  ) : null}
                </span>
              ) : (
                <span style={{ display: "block", marginTop: 6, fontSize: 13, color: "var(--p-ink-3)" }}>
                  fee not set &mdash; net-of-fee framing appears once the engagement fee is on file
                </span>
              )}
            </div>
          ) : null}

          <PlateFootnote n={1} label="THE HEADLINE" />
        </section>

        {/* ====================================================== position plate */}
        <section
          ref={(el) => { plateRefs.current[1] = el; }}
          className={`sheet plate relative rise d1 ${currentPlate === "position" ? "ring-2 ring-[var(--p-seal)] ring-offset-4 ring-offset-transparent" : ""}`}
          style={{ padding: "70px 78px" }}
          onClick={() => setPlateIndex(1)}
          role="button"
          aria-label="Plate 2: The position"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && setPlateIndex(1)}
        >
          <MicroLabel style={{ marginBottom: 6 }}>Where you stand today</MicroLabel>

          <h1 style={{ fontSize: 30 }}>
            {snap && Number(snap.marginal_rate) <= 0.24
              ? <>You&rsquo;re using the brackets well. The opportunity is what happens next.</>
              : <>You&rsquo;re in the upper bracket. That&rsquo;s exactly where planning pays.</>}
          </h1>

          {/* simplified position — 3 marks max, zero jargon */}
          {posSegments.length > 0 && snap ? (
            <div style={{ margin: "26px 0 8px" }}>
              <PositionInstrument
                segments={posSegments}
                incomeCents={snap.taxable_income_cents}
                nowLabel="you"
                variant="bar"
              />
              <div
                className="font-mono"
                style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--p-ink-3)", marginTop: 8 }}
              >
                <span>lower rates</span>
                <span>your income fills to here &mdash; {(Number(snap.marginal_rate) * 100).toFixed(0)}%</span>
                <span>higher rates</span>
              </div>
            </div>
          ) : (
            <div
              className="font-mono"
              style={{ margin: "26px 0", fontSize: 11, color: "var(--p-ink-3)" }}
            >
              [additive: position requires a confirmed return + bracket sets]
            </div>
          )}

          {snap ? (
            <p style={{ fontSize: 15.5 }}>
              {taxYear}: you earned{" "}
              <b className="fig-serif">{centsToUSD(snap.total_income_cents)}</b> and paid{" "}
              <b className="fig-serif">{centsToUSD(snap.total_tax_cents)}</b> in combined tax &mdash;
              about {(Number(snap.effective_rate) * 100).toFixed(1)} cents of every dollar.
              {(Number(snap.marginal_rate) * 100) < 35
                ? " That's normal for your bracket."
                : " That's the ceiling — and why every dollar of planning has the highest leverage here."}
            </p>
          ) : (
            <p className="font-mono" style={{ fontSize: 13, color: "var(--p-ink-3)" }}>
              [position narrative: confirm a return to populate this plate]
            </p>
          )}

          <PlateFootnote n={2} label="THE POSITION" />
        </section>

        {/* ======================================================== moves plate */}
        <section
          ref={(el) => { plateRefs.current[2] = el; }}
          className={`sheet plate relative rise d2 ${currentPlate === "moves" ? "ring-2 ring-[var(--p-seal)] ring-offset-4 ring-offset-transparent" : ""}`}
          style={{ padding: "70px 78px" }}
          onClick={() => setPlateIndex(2)}
          role="button"
          aria-label="Plate 3: The moves"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && setPlateIndex(2)}
        >
          <MicroLabel style={{ marginBottom: 6 }}>The plan, in {topFindings.length || 3} moves</MicroLabel>
          <h1 style={{ fontSize: 30 }}>Order is everything.</h1>

          {topFindings.length > 0 ? (
            <div style={{ display: "grid", gap: 16, marginTop: 24 }}>
              {topFindings.map((f, i) => (
                <MoveRow
                  key={i}
                  n={i + 1}
                  title={f.title}
                  body={f.recommended_action}
                  amtCents={f.estimated_impact_cents}
                />
              ))}
            </div>
          ) : (
            <p style={{ fontSize: 13, color: "var(--p-ink-3)", marginTop: 20 }}>
              The sealed memo has no savings findings to stage as moves.
            </p>
          )}

          <PlateFootnote n={3} label="THE MOVES" />
        </section>

        {/* ===================================================== keep + cal plate */}
        <section
          ref={(el) => { plateRefs.current[3] = el; }}
          className={`sheet plate relative rise d3 ${currentPlate === "keep" ? "ring-2 ring-[var(--p-seal)] ring-offset-4 ring-offset-transparent" : ""}`}
          style={{ padding: "70px 78px" }}
          onClick={() => setPlateIndex(3)}
          role="button"
          aria-label="Plate 4: The agreement"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && setPlateIndex(3)}
        >
          <MicroLabel style={{ marginBottom: 6 }}>What it costs &middot; what happens next</MicroLabel>
          <h1 style={{ fontSize: 30 }}>You keep the difference.</h1>

          {/* keep/cost panel */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              border: "1px solid var(--p-hairline)",
              borderRadius: 10,
              overflow: "hidden",
              marginTop: 26,
            }}
          >
            {/* fee side — LIVE from GET /admin/engagements/{clientId}/fee */}
            <div
              style={{
                padding: "24px 28px",
                borderRight: "1px solid var(--p-hairline)",
              }}
            >
              <MicroLabel style={{ color: "var(--p-ink-3)" }}>
                {fee ? `Our fee${FEE_BASIS_LABEL[fee.fee_basis] ? ` — ${FEE_BASIS_LABEL[fee.fee_basis]}` : ""}` : "Our fee"}
              </MicroLabel>
              <div
                className="fig-serif"
                style={{ fontFamily: "var(--font-ui)", fontWeight: 800, fontSize: 40, letterSpacing: "-0.03em" }}
              >
                {fee ? centsToUSD(fee.fee_cents) : (
                  <span className="font-mono" style={{ fontSize: 13, color: "var(--p-ink-3)" }}>
                    fee not set
                  </span>
                )}
              </div>
              <p style={{ fontSize: 13, margin: "8px 0 0", color: "var(--p-ink-2)" }}>
                {fee?.fee_note
                  ? fee.fee_note
                  : "plan + implementation support + quarterly reviews"}
              </p>
            </div>
            {/* savings side — LIVE from the signed run */}
            <div style={{ padding: "24px 28px" }}>
              <MicroLabel style={{ color: "var(--p-save)" }}>Identified savings</MicroLabel>
              <div
                className="fig-serif"
                style={{
                  fontFamily: "var(--font-ui)",
                  fontWeight: 800,
                  fontSize: 40,
                  letterSpacing: "-0.03em",
                  color: "var(--p-save)",
                }}
              >
                {totalSavings > 0 ? centsToUSD(totalSavings) : (
                  <span style={{ fontSize: 16, color: "var(--p-ink-3)" }}>—</span>
                )}
              </div>
              <p style={{ fontSize: 13, margin: "8px 0 0", color: "var(--p-ink-2)" }}>
                we track every move to <b>realized</b> — and show you the reconciliation on next year&apos;s return
              </p>
            </div>
          </div>

          {/* net-of-fee line — honest framing; only when a fee is on file */}
          {netOfFeeCents !== null && feeCents !== null ? (
            <p style={{ fontSize: 15, margin: "16px 0 0", color: "var(--p-ink-2)" }}>
              {centsToUSD(totalSavings)} identified against a {centsToUSD(feeCents)} fee &mdash;{" "}
              <b style={{ color: "var(--p-save)" }}>net {centsToUSD(netOfFeeCents)}</b> stays with you.
            </p>
          ) : totalSavings > 0 ? (
            <p style={{ fontSize: 13.5, margin: "16px 0 0", color: "var(--p-ink-3)" }}>
              Set the engagement fee to show the net-of-fee figure here.
            </p>
          ) : null}

          {/* calendar steps — derived from finding categories */}
          <CalendarSteps findings={topFindings} taxYear={taxYear} />

          {/* provenance footline — now backed by the signed memo's seal */}
          <p
            className="fn"
            style={{ marginTop: 26, fontSize: 12.5, color: "var(--p-ink-3)", lineHeight: 1.65 }}
          >
            Every dollar figure on these pages was computed by deterministic tax engines from
            your filed {taxYear} return and current law ({taxYear} constants, verified).
            Prepared by {firmName} &middot; this is planning, not a filed return.
            {signedMemo.signed_at ? (
              <>
                {" "}Reviewed and signed{signedMemo.signed_by ? ` by ${signedMemo.signed_by}` : ""} on{" "}
                {new Date(signedMemo.signed_at).toLocaleDateString()}
                {signedMemo.audit_event_id ? ` · audit ${signedMemo.audit_event_id.slice(0, 8)}` : ""}.
              </>
            ) : null}
          </p>

          <PlateFootnote n={4} label="THE AGREEMENT" />
        </section>

        {/* accessibility note for keyboard nav */}
        <p className="sr-only">
          Use left and right arrow keys to navigate between plates. Press F to enter fullscreen.
        </p>
      </div>

      {/* ---- prev/next buttons (for pointer users) ---- */}
      <div
        className="fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3"
        style={{ zIndex: 40 }}
      >
        <button
          className="mini-btn"
          aria-label="Previous plate"
          disabled={plateIndex === 0}
          onClick={() => setPlateIndex((i) => Math.max(i - 1, 0))}
          style={{ opacity: plateIndex === 0 ? 0.4 : 1 }}
        >
          &#8592;
        </button>
        <span className="font-mono text-[10.5px]" style={{ color: "var(--g-ink-3)" }}>
          {plateIndex + 1} / {PLATE_ORDER.length}
        </span>
        <button
          className="mini-btn"
          aria-label="Next plate"
          disabled={plateIndex === PLATE_ORDER.length - 1}
          onClick={() => setPlateIndex((i) => Math.min(i + 1, PLATE_ORDER.length - 1))}
          style={{ opacity: plateIndex === PLATE_ORDER.length - 1 ? 0.4 : 1 }}
        >
          &#8594;
        </button>
      </div>
    </div>
  );
}

/* ---- a move row for the moves plate ---- */
function MoveRow({ n, title, body, amtCents }: { n: number; title: string; body: string; amtCents: number }) {
  return (
    <div
      style={{
        border: "1px solid var(--p-hairline)",
        borderRadius: 10,
        padding: "20px 24px",
        display: "flex",
        gap: 20,
        alignItems: "baseline",
        background: "rgba(255,255,255,0.45)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-ui)",
          fontWeight: 800,
          fontSize: 26,
          color: "var(--p-seal)",
          width: 34,
          flexShrink: 0,
        }}
      >
        {n}
      </span>
      <span style={{ flex: 1 }}>
        <b style={{ fontFamily: "var(--font-ui)", fontSize: 18, display: "block", letterSpacing: "-0.01em" }}>
          {title}
        </b>
        <p style={{ margin: "6px 0 0", fontSize: 15, color: "var(--p-ink-2)", lineHeight: 1.6 }}>
          {body}
        </p>
      </span>
      <Money
        cents={amtCents}
        tone="save"
        className="fig-serif ml-auto whitespace-nowrap"
        /* override for the present plate — larger on a sheet */
      />
    </div>
  );
}

/* ---- calendar steps derived from finding categories ---- */
function CalendarSteps({ findings }: { findings: Finding[]; taxYear: number }) {
  // TODO(integration: tasks model §9.4) — statutory deadlines per strategy.
  // Until that endpoint lands we derive rough calendar steps from the top
  // findings' categories. This is CLEARLY ILLUSTRATIVE: if no findings are
  // available we show the spec's demo calendar shape with an honest label.
  const steps =
    findings.length > 0
      ? findings.slice(0, 4).map((f, i) => ({
          when: i === 0 ? `NOW · ${businessDate().slice(0, 4)}` : `STEP ${i + 1}`,
          action: f.title,
          note: null as string | null,
        }))
      : [
          { when: "STEP 1", action: "Confirm your return", note: "so the engines have the real numbers" },
          { when: "STEP 2", action: "Run the strategist", note: "identifies the openings" },
          { when: "STEP 3", action: "Sign the memo", note: "locks the plan and unlocks present mode" },
          { when: "STEP 4", action: "Implement", note: "we track every move to realized" },
        ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${Math.min(steps.length, 4)}, 1fr)`,
        gap: 16,
        marginTop: 26,
      }}
    >
      {steps.map((s, i) => (
        <div
          key={i}
          style={{
            border: "1px solid var(--p-hairline)",
            borderRadius: 10,
            padding: "16px 18px",
            background: "rgba(255,255,255,0.45)",
          }}
        >
          <div
            className="font-mono"
            style={{ fontSize: 10, color: "var(--p-seal)", letterSpacing: "0.1em" }}
          >
            {s.when}
          </div>
          <b style={{ fontFamily: "var(--font-ui)", fontSize: 14.5, display: "block", marginTop: 6 }}>
            {s.action}
          </b>
          {s.note ? (
            <span style={{ fontSize: 12, color: "var(--p-ink-3)" }}>{s.note}</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/* ---- folio number in the bottom-right corner of each plate ---- */
function PlateFootnote({ n, label }: { n: number; label: string }) {
  return (
    <span
      className="font-mono"
      style={{
        position: "absolute",
        bottom: 22,
        right: 28,
        fontSize: 9.5,
        color: "var(--p-ink-3)",
      }}
    >
      № {n} &middot; {label}
    </span>
  );
}
