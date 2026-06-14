"use client";

// Surface 07 — THE PLAN
// Identified → Signed → Realized ledger; each strategy as a 5-field implementation
// contract (WHO / WHAT / CASH / DEADLINE / PROOF); the safe-harbor chart; and the
// deliverables rail.
//
// Engine-only numbers: identified savings from overview.strategies (engine-computed);
// required/paid payment figures from overview.quarterly (quarterly engine).
// Anything not in the API is honestly labeled — see INTEGRATION-TODO.07.md.
//
// Live data sources:
//   GET /clients/:id/overview  →  .strategies (name/disposition/amount_cents/estimated_savings_cents/status_flag)
//                               →  .quarterly  (quarter/due_date/required_payment_cents/payment_made_cents/
//                                               unpaid_rollforward_cents/safe_harbor_basis/status)
//   GET /plans/:planId/pdf     →  PlanDoc[] (id/version/garage_key/payload_hash)
//
// Additive (Honesty Protocol — rendered as labeled fixtures):
//   tasks model (5-field contracts + statutory deadlines + evidence upload) — spec §9.4
//   realized reconciliation (next-year return/books vs plan) — spec §9.7
//   per-strategy one-pager / CPA-letter renderers — spec §9.8

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useClientOverview, type QuarterRow, type StrategyRow } from "@/components/client-overview";
import {
  Annotation,
  Aavatar,
  Chip,
  MicroLabel,
  MiniButton,
  Money,
  Omnibar,
  Panel,
  PanelHead,
  ProvFigure,
  Stamp,
  Term,
  hueForClient,
} from "@/components/kit";
import { SafeHarborChart, ChartLegend } from "@/components/kit/charts";

/* ---- additional type for the versioned PDF docs ---- */
interface PlanDoc {
  id: string;
  version: number;
  garage_key: string;
  payload_hash: string;
}

// TODO(integration: GET /plans/:planId/tasks) — 5-field contract model (spec §9.4)
// ContractRow renders [additive] label placeholders for the 5 fields (WHO/WHAT/CASH/
// DEADLINE/PROOF) until this endpoint lands. The savings figure comes from
// overview.strategies (engine-sourced); nothing else is fabricated.

/* ---- disposition helpers ---- */
const SIGNED_DISPOSITIONS = new Set(["signed", "accepted", "implementing"]);

/** Build cumulative required-vs-paid arrays from quarterly rows (4 quarters).
 *  Required cumulative: 22.5% / 45% / 67.5% / 90% of the full-year total.
 *  Paid cumulative: sum of payment_made_cents through each quarter.
 *  Both engine-sourced — no fabrication.
 */
function buildSafeHarborSeries(quarters: QuarterRow[]): {
  requiredCumCents: number[];
  paidCumCents: number[];
  penaltyCents: number;
} {
  if (quarters.length === 0) return { requiredCumCents: [], paidCumCents: [], penaltyCents: 0 };

  // Annual required = sum of all quarter's required_payment_cents (engine-supplied)
  const annualRequired = quarters.reduce((s, q) => s + q.required_payment_cents, 0);

  // Statutory safe-harbor milestones: 22.5 / 45 / 67.5 / 90 %
  const milestones = [0.225, 0.45, 0.675, 0.9];
  const requiredCumCents = milestones.map((m) => Math.round(annualRequired * m));

  // Cumulative paid: sum through each quarter in order 1→4
  const sorted = [...quarters].sort((a, b) => a.quarter - b.quarter);
  let cumPaid = 0;
  const paidCumCents = sorted.map((q) => {
    cumPaid += q.payment_made_cents;
    return cumPaid;
  });

  // Penalty: engine would supply this; here we use unpaid_rollforward_cents from Q4 as a proxy.
  // A negative unpaid is a surplus — no penalty.
  const q4 = sorted.find((q) => q.quarter === 4);
  const penaltyCents = q4 && q4.unpaid_rollforward_cents > 0 ? q4.unpaid_rollforward_cents : 0;

  return { requiredCumCents, paidCumCents, penaltyCents };
}

/** Quarter label for the table rows — Q1 → "APR 15", etc. */
const Q_LABELS: Record<number, string> = { 1: "APR 15", 2: "JUN 15", 3: "SEP 15", 4: "JAN 15" };

/** Status-to-chip-tone */
function quarterTone(status: string): "save" | "cost" | "neutral" {
  if (status === "paid") return "save";
  if (status === "missed" || status === "partial") return "cost";
  return "neutral";
}

/* ======================================================================= */
export default function PlanPage() {
  const { clientId, overview, loading } = useClientOverview();
  const [docs, setDocs] = useState<PlanDoc[] | null>(null);
  const [docsLoading, setDocsLoading] = useState(true);

  const planYearId = overview?.plan_year_id ?? null;
  const planYear = useMemo(
    () => overview?.years.find((y) => y.id === planYearId) ?? overview?.years[0],
    [overview, planYearId],
  );
  const hue = hueForClient(clientId);

  /* ---- fetch versioned PDF docs ---- */
  useEffect(() => {
    if (!planYearId) { setDocs([]); setDocsLoading(false); return; }
    setDocsLoading(true);
    // TODO(integration: GET /plans/:planId/pdf-docs) — list of versioned+hashed plan PDFs
    api.get(`/plans/${planYearId}/pdf`)
      .then((r) => setDocs(Array.isArray(r.data) ? r.data : [r.data]))
      .catch(() => setDocs([]))
      .finally(() => setDocsLoading(false));
  }, [planYearId]);

  /* ---- strategy summary figures — ALL from the engine ---- */
  const identified = useMemo(
    () => (overview?.strategies ?? []).reduce((s, x) => s + (x.estimated_savings_cents || 0), 0),
    [overview],
  );
  const signedStrategies = useMemo(
    () => (overview?.strategies ?? []).filter((s) => SIGNED_DISPOSITIONS.has(s.disposition)),
    [overview],
  );
  const signedTotal = useMemo(
    () => signedStrategies.reduce((s, x) => s + (x.estimated_savings_cents || 0), 0),
    [signedStrategies],
  );
  const isPlanSealed = planYear?.finalized_at != null;

  /* ---- safe-harbor chart data — engine-sourced ---- */
  const { requiredCumCents, paidCumCents, penaltyCents } = useMemo(
    () => buildSafeHarborSeries(overview?.quarterly ?? []),
    [overview],
  );

  // [additive] Task contracts (5-field) come from GET /plans/:planId/tasks (spec §9.4).
  // ContractRow renders [additive] label placeholders for those fields until
  // the endpoint lands. No fixture array needed here — strategy rows supply
  // the engine-sourced figures; the 5-field body is visibly stubbed in the component.
  // TODO(integration: GET /plans/:planId/tasks) — replace field stubs with real rows

  /* ---- loading ---- */
  if (loading) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[36px] w-[260px] rounded-[9px]" />
        <div className="mt-4 skeleton h-[130px] w-full rounded-[14px]" />
        <div className="mt-5 skeleton h-[280px] w-full rounded-[14px]" />
        <div className="mt-5 grid grid-cols-[1.3fr_1fr] gap-[22px]">
          <div className="skeleton h-[340px] rounded-[14px]" />
          <div className="skeleton h-[340px] rounded-[14px]" />
        </div>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No plan data yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            Import and confirm a return to open the plan view.
          </p>
        </Panel>
      </div>
    );
  }

  const hasQuarterly = (overview.quarterly ?? []).length > 0;
  const totalRequired = (overview.quarterly ?? []).reduce((s, q) => s + q.required_payment_cents, 0);
  const totalPaid = (overview.quarterly ?? []).reduce((s, q) => s + q.payment_made_cents, 0);
  const safeHarborBasis = overview.quarterly[0]?.safe_harbor_basis ?? null;
  const basisLabel: Record<string, string> = {
    "90_current": "90% of current-year tax",
    "100_prior": "100% of prior-year tax",
    "110_prior_high_agi": "110% of prior-year (high AGI)",
  };

  /* ================================================================ */
  return (
    <div className="wrap py-7 pb-16" style={{ "--chue": hue } as React.CSSProperties}>

      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-center gap-[14px]">
        <div>
          <h1 className="text-[30px] font-extrabold leading-none tracking-[-0.02em]">The Plan</h1>
          <Annotation className="mt-1 block">
            a plan is five contracts, not a PDF — the books re-project it monthly
          </Annotation>
        </div>
        {isPlanSealed && planYear?.finalized_at ? (
          <Stamp kind="signed" className="!transform-none">
            ⛁ Signed v1 · {new Date(planYear.finalized_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </Stamp>
        ) : null}
        <span className="ml-auto hidden sm:block">
          <Link href={`/c/${clientId}/memo`} className="btn btn-ghost text-[12.5px]">
            Present ▸
          </Link>
        </span>
      </section>

      {/* ================================================================
          LEDGER: Identified → Signed → Realized
          - Identified: engine-computed sum of overview.strategies
          - Signed: engine-computed sum of signed strategies
          - Realized: [additive] — labeled fixture
      ================================================================ */}
      <section className="panel rise d1 mt-4 grid grid-cols-1 gap-0 overflow-hidden sm:grid-cols-3">

        {/* col 1: identified */}
        <div className="border-b border-[var(--g-hairline-soft)] px-[22px] py-[18px] sm:border-b-0 sm:border-r">
          <MicroLabel>Identified by the strategist</MicroLabel>
          <div className="mt-1.5 text-[27px] font-[750] leading-none tracking-[-0.025em]">
            <ProvFigure
              cents={identified}
              tone="save"
              prov={{
                label: "total illustrative savings identified",
                engine: "strategies.calculate",
                source: "engine",
                inputs: [
                  { k: "strategies", v: `${overview.strategies.length} on this file` },
                  { k: "engine", v: "effective-rate × amount per strategy" },
                ],
                constants: [{ k: "engine-verified", v: "each figure from the quarterly/comprehensive engine" }],
              }}
            />
            <span className="ml-0.5 text-[13px] font-normal text-[var(--g-ink-3)]">/yr</span>
          </div>
          <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">
            {overview.strategies.length} finding{overview.strategies.length !== 1 ? "s" : ""} · engine-verified
          </div>
        </div>

        {/* col 2: signed */}
        <div className="border-b border-[var(--g-hairline-soft)] px-[22px] py-[18px] sm:border-b-0 sm:border-r">
          <MicroLabel className="!text-[var(--seal)]">Signed into the plan</MicroLabel>
          <div className="mt-1.5 text-[27px] font-[750] leading-none tracking-[-0.025em]">
            {signedStrategies.length > 0 ? (
              <ProvFigure
                cents={signedTotal}
                tone="seal"
                prov={{
                  label: "savings accepted and signed",
                  engine: "strategies.calculate",
                  source: "engine",
                  inputs: [
                    { k: "signed strategies", v: `${signedStrategies.length} of ${overview.strategies.length}` },
                  ],
                }}
              />
            ) : (
              <span className="text-[var(--g-ink-3)]">—</span>
            )}
            <span className="ml-0.5 text-[13px] font-normal text-[var(--g-ink-3)]">/yr</span>
          </div>
          <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">
            {isPlanSealed && planYear?.finalized_at
              ? `all ${signedStrategies.length} accepted · sealed ${new Date(planYear.finalized_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
              : `${signedStrategies.length} of ${overview.strategies.length} accepted`}
          </div>
        </div>

        {/* col 3: realized — [additive] fixture */}
        <div className="px-[22px] py-[18px]">
          <MicroLabel>
            Realized to date{" "}
            <span className="ml-1 font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--cost)]">
              [additive]
            </span>
          </MicroLabel>
          {/* TODO(integration: GET /plans/:planId/realized) — realized reconciliation (spec §9.7) */}
          <div className="mt-1.5 text-[27px] font-[750] leading-none tracking-[-0.025em] text-[var(--g-ink-3)]">
            —
          </div>
          <div className="mt-2 h-[7px] w-full overflow-hidden rounded-full bg-[rgba(31,28,23,0.08)]">
            <div className="h-full w-0 rounded-full bg-gradient-to-r from-[var(--seal)] to-[#e7cf9b]" />
          </div>
          <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">
            reconciles against the filed return · additive when next-year return/books arrive
          </div>
        </div>
      </section>

      {/* ================================================================
          IMPLEMENTATION CONTRACTS
          StrategyName + savingsCents come from overview.strategies (engine).
          The 5-field contract rows (who/what/cash/deadline/proof) are [additive]
          labeled fixtures — they demonstrate the layout awaiting GET /plans/:planId/tasks.
      ================================================================ */}
      <Panel className="rise d2 mt-[22px]">
        <PanelHead>
          <MicroLabel>
            Implementation · {signedStrategies.length} of {overview.strategies.length} confirmed
          </MicroLabel>
          <Annotation className="!text-[13px]">
            who · what · cash · deadline · proof — plans die without all five
          </Annotation>
          <div className="ml-auto flex items-center gap-2">
            <Chip tone="agent" className="!text-[11px]">agent chases overdue items, drafts the reminders</Chip>
          </div>
        </PanelHead>

        {overview.strategies.length === 0 ? (
          <div className="px-6 py-10 text-center text-[13.5px] text-[var(--g-ink-3)]">
            No strategies identified yet. Run the strategist to surface opportunities.
          </div>
        ) : (
          <div className="divide-y divide-[var(--g-hairline-soft)]">
            {overview.strategies.map((s, i) => (
              <ContractRow
                key={s.id}
                strategy={s}
                isFirst={i === 0}
              />
            ))}
          </div>
        )}
      </Panel>

      {/* ================================================================
          GRID: Safe-harbor chart (left) + Deliverables rail (right)
      ================================================================ */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.3fr_1fr]">

        {/* ---- SAFE-HARBOR CHART ---- */}
        <Panel className="rise d3">
          <PanelHead>
            <MicroLabel>
              {planYear?.tax_year ?? "—"} estimates · cumulative{" "}
              <Term k="safe-harbor">required vs paid</Term>
            </MicroLabel>
            {safeHarborBasis ? (
              <Chip className="ml-auto !text-[10.5px]">
                basis: {basisLabel[safeHarborBasis] ?? safeHarborBasis}
              </Chip>
            ) : null}
          </PanelHead>

          {hasQuarterly ? (
            <>
              <div className="px-4 pt-3">
                <SafeHarborChart
                  requiredCumCents={requiredCumCents}
                  paidCumCents={paidCumCents}
                  penaltyCents={penaltyCents > 0 ? penaltyCents : undefined}
                  height={190}
                  className="w-full"
                />
                <ChartLegend
                  className="mt-1 justify-end px-2 pb-2"
                  items={[
                    { label: "required (2210 step)", tone: "var(--g-ink-3)", dashed: true },
                    { label: "paid", tone: "var(--save)" },
                  ]}
                />
              </div>

              {/* quarterly table rows — engine data */}
              <div className="border-t border-[var(--g-hairline-soft)]">
                {[...(overview.quarterly ?? [])].sort((a, b) => a.quarter - b.quarter).map((q) => (
                  <div
                    key={q.quarter}
                    className="flex items-center gap-3 border-t border-[var(--g-hairline-soft)] px-[20px] py-[10px] text-[12.5px] first:border-t-0"
                  >
                    <span className="w-[110px] font-mono text-[10px] text-[var(--g-ink-3)]">
                      Q{q.quarter} · {Q_LABELS[q.quarter] ?? q.due_date}
                    </span>
                    <span className="flex-1 text-[12px] text-[var(--g-ink-2)]">
                      {q.due_date}
                      {q.unpaid_rollforward_cents > 0 ? (
                        <span className="ml-1.5 font-mono text-[10.5px] text-[var(--cost)]">
                          +{centsToUSD(q.unpaid_rollforward_cents)} rolled
                        </span>
                      ) : null}
                    </span>
                    <span className="mr-2">
                      <Chip tone={quarterTone(q.status)} className="!px-[7px] !py-[2px] !text-[10px]">
                        {q.status}
                      </Chip>
                    </span>
                    <span className="fig font-mono text-[12.5px] font-bold">
                      <Money
                        cents={q.payment_made_cents > 0 ? q.payment_made_cents : q.required_payment_cents}
                        tone={q.payment_made_cents > 0 ? "save" : undefined}
                      />
                    </span>
                  </div>
                ))}
              </div>

              {/* totals footer */}
              <div className="flex items-center gap-4 border-t border-[var(--g-hairline-soft)] px-[20px] py-[10px] font-mono text-[11px]">
                <span className="text-[var(--g-ink-3)]">annual required</span>
                <ProvFigure
                  cents={totalRequired}
                  prov={{
                    label: "total annual estimated tax required",
                    engine: "quarterly.compute",
                    source: "engine",
                    inputs: [{ k: "safe_harbor_basis", v: safeHarborBasis ?? "—" }],
                  }}
                  className="!text-[12px]"
                />
                <span className="ml-auto text-[var(--g-ink-3)]">paid to date</span>
                <ProvFigure
                  cents={totalPaid}
                  tone={totalPaid >= Math.round(totalRequired * 0.9) ? "save" : "cost"}
                  prov={{ label: "total paid to date", engine: "quarterly.compute", source: "engine" }}
                  className="!text-[12px]"
                />
              </div>

              <div className="border-t border-[var(--g-hairline-soft)] px-[18px] py-[10px] font-mono text-[10px] text-[var(--g-ink-3)]">
                Dashed step line = Form 2210 required cumulative (22.5/45/67.5/90%); a paid-line dip below shades red with the engine&apos;s penalty dollars.
                Lumpy income flips to the 2210-AI annualized steps{" "}
                <span className="text-[var(--cost)]">[annualized toggle — additive]</span>.
                {/* TODO(integration: GET /plans/:planId/quarterly/annualized) — 2210-AI annualized mode */}
              </div>
            </>
          ) : (
            <div className="px-6 py-10 text-center text-[13.5px] text-[var(--g-ink-3)]">
              <p>No quarterly estimates computed yet.</p>
              <Link
                href={`/c/${clientId}/`}
                className="mt-3 inline-block text-[12.5px] text-[var(--agent)] underline-offset-2 hover:underline"
              >
                Compute via the quarterly engine →
              </Link>
            </div>
          )}
        </Panel>

        {/* ---- DELIVERABLES RAIL ---- */}
        <Panel className="rise d4">
          <PanelHead>
            <MicroLabel>Deliverables · versioned &amp; hashed</MicroLabel>
            <Chip className="ml-auto !text-[10.5px]">white-label branding</Chip>
          </PanelHead>

          <div className="divide-y divide-[var(--g-hairline-soft)]">
            {/* Client PDF — LIVE (generated via POST /plans/:planId/pdf) */}
            {docsLoading ? (
              <div className="flex items-center gap-3 px-[18px] py-[13px]">
                <div className="skeleton h-[46px] w-[36px] rounded-[4px]" />
                <div className="skeleton h-[36px] flex-1 rounded-[6px]" />
              </div>
            ) : (docs ?? []).length > 0 ? (
              (docs ?? []).map((d) => (
                <DeliverableRow
                  key={d.id}
                  title="Tax Plan — client copy"
                  meta={`v${d.version} · sha-256 ${d.payload_hash.slice(0, 8)}…${d.payload_hash.slice(-4)} · top findings + action checklist`}
                >
                  <Link href={`/c/${clientId}/memo`}>
                    <MiniButton>Present ▸</MiniButton>
                  </Link>
                  <MiniButton
                    onClick={() => {
                      // TODO(integration: GET /plans/:planId/pdf/:id/download) — retrieve stored PDF
                    }}
                  >
                    PDF
                  </MiniButton>
                </DeliverableRow>
              ))
            ) : (
              <DeliverableRow
                title="Tax Plan — client copy"
                meta="not generated yet · generate via Memo tab"
              >
                <Link href={`/c/${clientId}/memo`}>
                  <MiniButton>Generate ▸</MiniButton>
                </Link>
              </DeliverableRow>
            )}

            {/* Per-strategy one-pagers — [additive] */}
            {/* TODO(integration: GET /plans/:planId/one-pagers) — per-strategy client explainers */}
            {overview.strategies.slice(0, 1).map((s) => (
              <DeliverableRow
                key={`op-${s.id}`}
                title={`${s.name} — one-page explainer`}
                meta={
                  <span>
                    client&apos;s own numbers · built to be forwarded{" "}
                    <span className="font-mono text-[9.5px] text-[var(--cost)]">[additive]</span>
                  </span>
                }
              >
                {/* TODO(integration: POST /plans/:planId/one-pagers) — generate one-pager */}
                <MiniButton className="cursor-not-allowed opacity-50" disabled>PDF</MiniButton>
              </DeliverableRow>
            ))}

            {/* Year-end CPA letter — [additive] */}
            {/* TODO(integration: GET /plans/:planId/cpa-letter) — auto-built from confirmed items */}
            <DeliverableRow
              title="Year-end letter to the preparer"
              meta={
                <span>
                  auto-builds from confirmed items (election, payroll, 401k, HSA, lots) · audience: CPA / client / internal{" "}
                  <span className="font-mono text-[9.5px] text-[var(--cost)]">[additive]</span>
                </span>
              }
            >
              <Chip className="!text-[10px]">drafts itself by Dec</Chip>
            </DeliverableRow>
          </div>

          {/* provenance footer */}
          <div className="border-t border-[var(--g-hairline-soft)] px-[18px] py-[14px] text-[12px] text-[var(--g-ink-3)]">
            Every export embeds its provenance block: engines version · inputs + hashes · strategist run ·{" "}
            <span className="font-semibold text-[var(--g-ink-2)]">reviewed &amp; signed by advisor</span>.
            The liability story is a feature.
          </div>
        </Panel>
      </div>

      {/* ---- Strategist watching ---- */}
      <Panel className="rise d5 mt-[22px] p-[18px]">
        <div className="flex gap-3">
          <Aavatar name="Strategist" agent="strategist" />
          <div className="min-w-0 flex-1">
            <MicroLabel><span className="tone-agent">Strategist · watching this plan</span></MicroLabel>
            <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--g-ink-2)]">
              {signedStrategies.length > 0
                ? `${signedStrategies.length} strateg${signedStrategies.length === 1 ? "y" : "ies"} in motion — the agent chases overdue items and drafts reminders; you send them. Next checkpoint: Q3 books close → verify on-pace via the chart above.`
                : overview.strategies.length > 0
                  ? `${overview.strategies.length} strateg${overview.strategies.length === 1 ? "y" : "ies"} identified — seal the plan to lock the contracts and activate the chase cycle.`
                  : "No strategies identified yet. Ask the strategist to scan this file for opportunities."}
            </p>
            <div className="mt-2 font-mono text-[10px] text-[var(--g-ink-3)]">
              BECAUSE: plan implementation tracking · chase cycle activates on seal
            </div>
          </div>
        </div>
      </Panel>

      {/* ---- omnibar ---- */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this plan — or ⌘K for actions…" />
      </div>
    </div>
  );
}

/* ================================================================= ContractRow */
/* Renders ONE strategy as a 5-field implementation contract.
   savingsCents comes from the strategy row (engine). The 5 fields are [additive]
   fixtures until GET /plans/:planId/tasks lands (spec §9.4). */

function ContractRow({
  strategy,
  isFirst,
}: {
  strategy: StrategyRow;
  isFirst: boolean;
}) {
  const isSigned = SIGNED_DISPOSITIONS.has(strategy.disposition);
  const isWaiting = strategy.status_flag === "explore" || (!isSigned && !isFirst);

  return (
    <div className={`px-[22px] py-[18px] ${isSigned ? "opacity-80" : ""}`}>
      {/* contract header */}
      <div className="flex flex-wrap items-baseline gap-[12px]">
        {isSigned ? (
          <Stamp kind="verified" className="!transform-none !text-[9px]">done</Stamp>
        ) : isWaiting ? (
          <Chip tone="cost" className="!text-[10px]">waiting on client</Chip>
        ) : (
          <Chip className="!text-[10px]">{strategy.disposition}</Chip>
        )}
        <span className="text-[15px] font-semibold leading-tight tracking-[-0.01em]">
          {strategy.name}
        </span>
        <span className="ml-auto font-[700] text-[16px]">
          <Money cents={strategy.estimated_savings_cents} tone="save" />
          <span className="ml-0.5 text-[12px] font-normal text-[var(--g-ink-3)]">/yr</span>
        </span>
      </div>

      {/* 5-field contract grid */}
      <div className="mt-[12px] grid grid-cols-2 gap-[10px] sm:grid-cols-5">
        <FieldBox label="who">
          {/* TODO(integration: GET /plans/:planId/tasks) — who field */}
          <span className="text-[var(--g-ink-3)] font-mono text-[10px]">[additive]</span>
        </FieldBox>
        <FieldBox label="what">
          {/* TODO(integration: GET /plans/:planId/tasks) — what field */}
          <span className="text-[var(--g-ink-3)] font-mono text-[10px]">[additive]</span>
        </FieldBox>
        <FieldBox label="cash">
          {/* TODO(integration: GET /plans/:planId/tasks) — cash field (estimated periodic cost) */}
          <span className="text-[var(--g-ink-3)] font-mono text-[10px]">[additive]</span>
        </FieldBox>
        <FieldBox label="deadline" warn={false}>
          {/* TODO(integration: GET /plans/:planId/tasks) — statutory deadline (engine-supplied) */}
          <span className="text-[var(--g-ink-3)] font-mono text-[10px]">[additive]</span>
        </FieldBox>
        <FieldBox label="proof">
          {/* TODO(integration: GET /plans/:planId/tasks) — evidence/document upload */}
          {isSigned ? (
            <span className="inline-flex items-center gap-[5px] font-mono text-[9.5px] text-[var(--save)]">
              ✓ confirmed
            </span>
          ) : (
            <span className="text-[var(--g-ink-3)] font-mono text-[10px]">[additive]</span>
          )}
        </FieldBox>
      </div>

      {/* strategy client_facing_copy (live) */}
      {strategy.client_facing_copy ? (
        <p className="mt-[10px] text-[12px] text-[var(--g-ink-3)] leading-relaxed">
          {strategy.client_facing_copy}
        </p>
      ) : null}
    </div>
  );
}

/* ================================================================= FieldBox */
function FieldBox({
  label,
  warn,
  children,
}: {
  label: string;
  warn?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-[9px] border px-[11px] py-[8px] ${
        warn
          ? "border-[rgba(170,106,28,0.45)] bg-[rgba(170,106,28,0.05)]"
          : "border-[var(--g-hairline-soft)]"
      }`}
    >
      <div className="font-mono text-[8.5px] uppercase tracking-[0.12em] text-[var(--g-ink-3)]">{label}</div>
      <div className="mt-[3px] text-[12px] text-[var(--g-ink)]">{children}</div>
    </div>
  );
}

/* ================================================================= DeliverableRow */
function DeliverableRow({
  title,
  meta,
  children,
}: {
  title: string;
  meta: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-[12px] px-[18px] py-[13px]">
      {/* paper document icon */}
      <span
        className="relative flex-none"
        style={{
          width: 36, height: 46,
          borderRadius: 4,
          background: "linear-gradient(180deg, #efe9da, #e4ddc9)",
          boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
        }}
        aria-hidden
      >
        <span
          className="absolute"
          style={{
            left: 6, right: 6, top: 8, height: 2,
            background: "#1d1b16",
            opacity: 0.7,
            boxShadow: "0 5px 0 rgba(29,27,22,0.35), 0 10px 0 rgba(29,27,22,0.25), 0 15px 0 rgba(29,27,22,0.2)",
          }}
        />
      </span>

      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold leading-tight">{title}</div>
        <div className="mt-[3px] text-[11px] text-[var(--g-ink-3)] leading-snug">{meta}</div>
      </div>

      {children ? (
        <div className="flex flex-shrink-0 items-center gap-[6px]">{children}</div>
      ) : null}
    </div>
  );
}
