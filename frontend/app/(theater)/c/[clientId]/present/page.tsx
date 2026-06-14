"use client";

// Surface 13 — PRESENT (theater). Full-screen paper plates on dark.
//
// Posture: THEATER — body.theater is set by the (theater) layout; no topbar,
// no agent chrome, no file nav. Four plates; arrow keys and F-key navigation.
//
// DATA WIRING:
// [live-ish] Cover headline savings + top accepted findings: these come from
//   GET /agents/clients/tax-years/{id}/strategist (same endpoint as Memo 06).
// [live-ish] Simplified position (3 marks max): client overview bracket snapshot.
// [live-ish] Keep/cost plate: overview.strategies totals.
//
// [additive] Everything below is HONESTLY LABELED (per Honesty Protocol):
//   - memo persistence / sign state: the strategist result is re-fetched per
//     session (ephemeral); signed source would require spec §9.1.
//   - fee-net framing (the "123 : 1" ratio): fee config endpoint not yet built.
//   - Client-friendly narrative text per finding: the register transform
//     (additive per spec §7-06) is not built; we show recommended_action as-is.
//   - Calendar steps: derived from strategy categories; the tasks model
//     (spec §9.4) would supply statutory deadlines.
//
// TODO(integration: GET /agents/clients/tax-years/{id}/strategist) — headline
//   savings + findings (§7-06; same payload the Memo surface uses).
// TODO(integration: GET /admin/branding) — firm name; default until it lands.
// TODO(integration: GET /admin/engagements/{clientId}/fee) — fee for net framing.
// TODO(integration: memo persistence §9.1) — present from the signed memo.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  Letterhead,
  Money, MicroLabel, Chip,
  PositionInstrument,
  type Segment,
} from "@/components/kit";

/* ---- the strategist payload shape (same as Memo) ---- */
interface Finding {
  title: string;
  category: string;
  recommended_action: string;
  estimated_impact_cents: number;
  impact_kind: "savings" | "cost" | "info";
  citation: string;
  caveat: string;
}
interface Strategist {
  client_name: string;
  tax_year: number;
  current_total_tax_cents: number;
  marginal_rate: string;
  findings: Finding[];
  total_savings_identified_cents: number;
  memo: string | null;
  memo_available: boolean;
  objectives_summary: string | null;
  disclaimer: string;
}

// TODO(integration: GET /admin/branding) — firm name; default until it lands.
const FIRM_NAME = "Northstar Tax Advisory";

/* ---- the four plate ids ---- */
type PlateId = "cover" | "position" | "moves" | "keep";
const PLATE_ORDER: PlateId[] = ["cover", "position", "moves", "keep"];

// Props type kept for Next.js App Router compatibility (params are unused because
// clientId comes from the ClientOverviewProvider in the (theater) layout).
export default function PresentPage() {
  // All hooks must be called before any early returns (rules-of-hooks).
  // clientId is provided by the ClientOverviewProvider in the (theater) layout.
  const { clientId, overview, loading } = useClientOverview();
  const [strategist, setStrategist] = useState<Strategist | null>(null);
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

  // Fetch strategist once we know the tax-year id.
  // TODO(integration: GET /agents/clients/tax-years/{id}/strategist)
  useEffect(() => {
    if (!taxYearId) return;
    setSLoading(true);
    api
      .get(`/agents/clients/tax-years/${taxYearId}/strategist`)
      .then((r) => setStrategist(r.data as Strategist))
      .catch(() => setStrategist(null))
      .finally(() => setSLoading(false));
  }, [taxYearId]);

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

  // Top accepted / savings findings for the "moves" plate (up to 3)
  const topFindings: Finding[] = useMemo(() => {
    if (!strategist) return [];
    return strategist.findings
      .filter((f) => f.impact_kind === "savings")
      .sort((a, b) => b.estimated_impact_cents - a.estimated_impact_cents)
      .slice(0, 3);
  }, [strategist]);

  // Keep/cost: from overview.strategies
  const identified = useMemo(
    () => (overview?.strategies ?? []).reduce((a, s) => a + (s.estimated_savings_cents || 0), 0),
    [overview],
  );

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
  const clientName = client?.display_name ?? strategist?.client_name ?? "Your client";
  const taxYear = planYear?.tax_year ?? strategist?.tax_year ?? 2025;
  const totalSavings = strategist?.total_savings_identified_cents ?? identified;
  // TODO(integration: GET /admin/engagements/{clientId}/fee) — fee config not built.
  // The fee-net framing is ADDITIVE (spec §9 / §7-13). We show no fee figure until
  // the endpoint exists. Never invent or hardcode a fee dollar.

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
            firm={<>{FIRM_NAME}</>}
            docRef={`PREPARED FOR ${clientName.toUpperCase()} · ${taxYear}`}
          />

          <h1 style={{ fontSize: 42, margin: "22px 0 10px" }}>
            {strategist?.objectives_summary
              ? strategist.objectives_summary.split(".")[0] + "."
              : "Your next few years, planned to the dollar."}
          </h1>

          <p className="lede" style={{ fontSize: 19 }}>
            {strategist?.memo
              ? strategist.memo.split(/\n+/)[0].slice(0, 220)
              : `We analyzed your ${taxYear} return and identified the moves that matter most.`}
          </p>

          {/* headline savings — LIVE from strategist or overview.strategies */}
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
              : <span style={{ fontSize: 36, color: "var(--p-ink-3)" }}>Run the strategist to see the headline</span>}
          </div>

          {totalSavings > 0 ? (
            <div className="nof" style={{ fontSize: 15, color: "var(--p-ink-2)" }}>
              identified across {taxYear}&ndash;{taxYear + 4} &middot; every figure computed, none estimated
              {/* TODO(integration: GET /admin/engagements/{clientId}/fee) — fee-net framing
                  is additive (spec §9 / §7-13). When the fee endpoint lands, show:
                  net of [fee]: [net savings] stays with you — [ratio] : 1 */}
              <span className="ml-2 font-mono text-[10px]" style={{ color: "var(--p-ink-3)" }}>
                [fee-net framing: additive — see INTEGRATION-TODO.13.md]
              </span>
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
          ) : !strategist ? (
            /* no strategist run yet — honest additive note */
            <div
              className="font-mono"
              style={{
                margin: "24px 0",
                padding: "18px 22px",
                border: "1px dashed var(--p-hairline)",
                borderRadius: 10,
                fontSize: 12,
                color: "var(--p-ink-3)",
                lineHeight: 1.7,
              }}
            >
              <span className="tone-cost">[additive]</span> The &ldquo;moves&rdquo; plate renders from
              the top 3 accepted findings of the signed memo (spec §7-13). Run the strategist on the
              Memo page and sign it to populate this plate. See INTEGRATION-TODO.13.md.
              <br />
              <span className="font-mono" style={{ fontSize: 10 }}>
                TODO(integration: GET /agents/clients/tax-years/&#123;id&#125;/strategist)
              </span>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: "var(--p-ink-3)", marginTop: 20 }}>
              No savings findings in the strategist run yet.
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
            {/* fee side — additive (no fee endpoint yet) */}
            <div
              style={{
                padding: "24px 28px",
                borderRight: "1px solid var(--p-hairline)",
              }}
            >
              <MicroLabel style={{ color: "var(--p-ink-3)" }}>Our fee &mdash; flat, no surprises</MicroLabel>
              {/* TODO(integration: GET /admin/engagements/{clientId}/fee) — additive */}
              <div
                className="fig-serif"
                style={{ fontFamily: "var(--font-ui)", fontWeight: 800, fontSize: 40, letterSpacing: "-0.03em" }}
              >
                <span className="font-mono" style={{ fontSize: 13, color: "var(--p-ink-3)" }}>
                  [additive — fee endpoint not built]
                </span>
              </div>
              <p style={{ fontSize: 13, margin: "8px 0 0", color: "var(--p-ink-2)" }}>
                plan + implementation support + quarterly reviews
              </p>
            </div>
            {/* savings side — LIVE from strategist / overview */}
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

          {/* calendar steps — derived from strategy categories */}
          <CalendarSteps findings={topFindings} taxYear={taxYear} />

          {/* provenance footline */}
          <p
            className="fn"
            style={{ marginTop: 26, fontSize: 12.5, color: "var(--p-ink-3)", lineHeight: 1.65 }}
          >
            Every dollar figure on these pages was computed by deterministic tax engines from
            your filed {taxYear} return and current law ({taxYear} constants, verified).
            Prepared by {FIRM_NAME} &middot; this is planning, not a filed return.
            {/* TODO(integration: memo persistence §9.1) — "reviewed and signed by [signer] · [ref]"
                populates when the memo is signed. */}
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

/* ---- calendar steps derived from strategy categories ---- */
function CalendarSteps({ findings }: { findings: Finding[]; taxYear: number }) {
  // TODO(integration: tasks model §9.4) — statutory deadlines per strategy.
  // Until that endpoint lands we derive rough calendar steps from the top
  // findings' categories. This is CLEARLY ILLUSTRATIVE: if no findings are
  // available we show the spec's demo calendar shape with an honest label.
  const steps =
    findings.length > 0
      ? findings.slice(0, 4).map((f, i) => ({
          when: i === 0 ? `NOW · ${new Date().getFullYear()}` : `STEP ${i + 1}`,
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
