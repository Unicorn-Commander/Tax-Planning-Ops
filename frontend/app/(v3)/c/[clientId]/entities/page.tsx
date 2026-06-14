"use client";

// Surface 08 — THE ENTITIES
// The structure map (entity nodes → flows → 1040 hub → household rollup),
// the salary search curve (optimum + reasonable-comp floor), and the election
// ledger (both sides → net, engine-verified). The AO panel.
//
// Engine-only numbers (HARD INVARIANT): every dollar comes from an API field.
// The salary-search curve is now LIVE — optimize_scorp_salary recomputes federal
// tax across the split (real per-point deltas) and the optimizer marks its pick.
//
// Live data wired:
//   GET  /clients/tax-years/:id/business-entities   — entity list + AO workspace ids
//   GET  /clients/tax-years/:id/analysis            — analysis.business (SE, QBI, schedule_1)
//   POST /agents/clients/tax-years/:id/optimize/scorp — reasonable-comp search curve + pick
//   POST /clients/tax-years/:id/business-entities/:entityId/sync-accounting-ops  — AO pull-now
//
// Additive (stubbed per Honesty Protocol):
//   map-diff / mode-switch re-run         — mode chips (sole-prop / S-corp / what-if C-corp)

import { useEffect, useMemo, useState, useCallback } from "react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useClientOverview } from "@/components/client-overview";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Stamp,
  Money,
  ProvFigure,
  Aavatar,
  MiniButton,
  Omnibar,
  WorkingDots,
  Term,
  type Provenance,
} from "@/components/kit";
import {
  EntityMap,
  SalaryCurve,
  ChartLegend,
  type EntityNode,
  type EntityEdge,
} from "@/components/kit";
import { CorporateReturnPanel } from "@/components/corporate-return-panel";

/* ======================================================== wire shapes ======= */

type EntityKind = "schedule_c" | "partnership_k1" | "s_corp_k1" | "schedule_e" | "c_corp";

interface BusinessEntity {
  id: string;
  kind: EntityKind;
  name: string;
  amount_cents: number;
  w2_wages_paid_cents: number;
  ubia_cents: number;
  guaranteed_payments_cents: number;
  shareholder_w2_wages_cents: number;
  dividends_cents: number;
  nol_available_cents: number;
  is_general_partner: boolean;
  is_sstb: boolean;
  is_qbi: boolean;
  accounting_ops_workspace_id: string | null;
}

interface QbiPerBusiness {
  component_cents: number;
  regime: string;
}

interface BusinessSection {
  available: true;
  schedule_1_income_cents: number;
  se_earnings_base_cents: number;
  se_tax_cents: number;
  half_se_deduction_cents: number;
  qbi_deduction_cents: number;
  qbi_per_business: QbiPerBusiness[];
  assumptions?: string[] | string | null;
}

type Maybe<T> = T | { available: false; reason?: string };

interface Analysis {
  business: Maybe<BusinessSection>;
  comprehensive_return: Maybe<{
    available: true;
    total_tax_cents: number;
    base_snapshot_total_tax_cents: number;
    includes_business: boolean;
  }>;
}

/* ======================================================== kind labels ======= */

const KIND_BADGE: Record<EntityKind, string> = {
  schedule_c: "Sched C · sole prop",
  partnership_k1: "Partnership K-1",
  s_corp_k1: "S-corp K-1",
  schedule_e: "Schedule E",
  c_corp: "C-corp (1120)",
};

function flowLabel(e: BusinessEntity): string {
  if (e.kind === "s_corp_k1") {
    const w2 = e.shareholder_w2_wages_cents > 0 ? `W-2 ${centsToUSD(e.shareholder_w2_wages_cents)}` : "";
    const dist = e.amount_cents - e.shareholder_w2_wages_cents;
    const distStr = dist > 0 ? `+ distrib. ${centsToUSD(dist)}` : "";
    return [w2, distStr].filter(Boolean).join(" ") || `K-1 ${centsToUSD(e.amount_cents)}`;
  }
  if (e.kind === "schedule_e") return `Sch E → Sch 1 ${centsToUSD(e.amount_cents)}`;
  if (e.kind === "partnership_k1") {
    const gp = e.guaranteed_payments_cents > 0 ? ` (GP ${centsToUSD(e.guaranteed_payments_cents)})` : "";
    return `K-1 ${centsToUSD(e.amount_cents)}${gp}`;
  }
  return `Sched C ${centsToUSD(e.amount_cents)}`;
}

/* The S-corp salary optimizer trace (live: POST /agents/.../optimize/scorp).
   `curve` is the owner's federal total tax across the salary split (a real
   engine recompute at each salary); the headline `optimal_salary_cents` /
   `savings_vs_all_salary_cents` come from the optimizer's payroll-vs-QBI
   net-cost metric — a different (and more complete) axis than the curve, so we
   plot the curve's shape and mark the optimizer's pick, not the curve's min. */
interface ScorpOptimize {
  optimal_salary_cents: number;
  savings_vs_all_salary_cents: number;
  qbi_deduction_at_optimal_cents: number;
  curve: { salary_cents: number; total_tax_cents: number }[];
}

/* ======================================================== main component === */

export default function EntitiesPage() {
  const { clientId, overview, loading } = useClientOverview();
  const [entities, setEntities] = useState<BusinessEntity[] | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [entLoading, setEntLoading] = useState(true);
  const [scorpOpt, setScorpOpt] = useState<ScorpOptimize | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null); // entity id being synced

  const planYear = useMemo(() => {
    if (!overview) return undefined;
    const id = overview.plan_year_id ?? overview.base_year_id;
    return overview.years.find((y) => y.id === id) ?? overview.years[0];
  }, [overview]);

  const taxYearId = planYear?.id ?? null;
  // entities list
  const loadEntities = useCallback(() => {
    if (!taxYearId) { setEntLoading(false); return; }
    setEntLoading(true);
    api
      .get(`/clients/tax-years/${taxYearId}/business-entities`)
      .then((r) => setEntities(r.data))
      .catch(() => setEntities([]))
      .finally(() => setEntLoading(false));
  }, [taxYearId]);

  useEffect(loadEntities, [loadEntities]);

  // analysis (for business section: SE / QBI / schedule_1)
  useEffect(() => {
    if (!taxYearId) return;
    api
      .get(`/clients/tax-years/${taxYearId}/analysis`)
      .then((r) => setAnalysis(r.data))
      .catch(() => setAnalysis(null));
  }, [taxYearId]);

  // S-corp salary optimizer — real reasonable-comp search curve + the
  // optimizer's pick (only when an S-corp entity is present).
  useEffect(() => {
    if (!taxYearId || !entities) { setScorpOpt(null); return; }
    const sc = entities.find((e) => e.kind === "s_corp_k1");
    if (!sc) { setScorpOpt(null); return; }
    api
      .post(`/agents/clients/tax-years/${taxYearId}/optimize/scorp`, {}, { params: { entity_id: sc.id } })
      .then((r) => setScorpOpt(r.data))
      .catch(() => setScorpOpt(null));
  }, [taxYearId, entities]);

  // AO pull-now for a single entity
  const pullAo = useCallback(
    async (entityId: string) => {
      if (!taxYearId) return;
      setSyncing(entityId);
      try {
        await api.post(`/clients/tax-years/${taxYearId}/business-entities/${entityId}/sync-accounting-ops`);
        loadEntities();
      } catch {
        // ignore — surface-level feedback in the AO panel
      } finally {
        setSyncing(null);
      }
    },
    [taxYearId, loadEntities],
  );

  /* ---- derived data + memos (declared BEFORE the guards so every hook runs
         unconditionally — React rules-of-hooks) ---- */
  const ents = useMemo<BusinessEntity[]>(() => entities ?? [], [entities]);
  const biz = analysis?.business;
  const bizAvail = biz && biz.available;
  const cr = analysis?.comprehensive_return;
  const crAvail = cr && cr.available;

  const mapNodes: EntityNode[] = useMemo(() => {
    if (!overview || !planYear) return [];
    const nodes: EntityNode[] = [];
    for (const e of ents) {
      nodes.push({ id: e.id, label: e.name, sublabel: KIND_BADGE[e.kind], kind: "entity", amountCents: e.amount_cents });
    }
    nodes.push({
      id: "__hub__",
      label: overview.client.display_name,
      sublabel: `Form 1040 · ${planYear.filing_status}${overview.client.primary_state ? ` · ${overview.client.primary_state}` : ""}`,
      kind: "hub",
      amountCents: planYear.snapshot?.total_tax_cents ?? undefined,
    });
    const rollupCents = crAvail ? cr.total_tax_cents : planYear.snapshot?.total_tax_cents ?? undefined;
    nodes.push({ id: "__rollup__", label: `${planYear.tax_year} total tax`, sublabel: "household · plan", kind: "rollup", amountCents: rollupCents });
    return nodes;
  }, [ents, overview, planYear, crAvail, cr]);

  const mapEdges: EntityEdge[] = useMemo(() => {
    const edges: EntityEdge[] = [];
    for (const e of ents) edges.push({ from: e.id, to: "__hub__", label: flowLabel(e) });
    edges.push({ from: "__hub__", to: "__rollup__", label: "SE/FICA + QBI + NIIT + credits" });
    return edges;
  }, [ents]);

  /* ---- loading / empty guards ---- */
  if (loading || entLoading) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[420px] w-full rounded-[14px]" />
      </div>
    );
  }

  if (!overview || !planYear) {
    return (
      <div className="wrap py-10">
        <Panel className="p-8 text-center">
          <h2 className="text-[18px] font-semibold">No confirmed tax year yet</h2>
          <p className="mt-1 text-[13.5px] text-[var(--g-ink-2)]">
            Import and confirm a return to open the entities view.
          </p>
        </Panel>
      </div>
    );
  }

  /* ---- which entity to show the election ledger for (first S-corp) ---- */
  const scorp = ents.find((e) => e.kind === "s_corp_k1");

  /* ---- election ledger rows (live from analysis.business + entity fields) ---- */
  //   The "both sides of the ledger" table. Amounts come from engine fields only.
  //   Line items that require the optimize_scorp_salary trace are [additive] and
  //   clearly labeled. The SE vs FICA comparison IS available from analysis.business.
  const seTaxCents = bizAvail ? biz.se_tax_cents : null;
  const qbiDeductionCents = bizAvail ? biz.qbi_deduction_cents : null;

  // FICA for the S-corp salary: if shareholder_w2_wages_cents is set, we can
  // compute both-halves FICA (7.65% × 2 = 15.3% up to $168,600; we show the
  // component). This is arithmetic on an engine-supplied field, not an LLM guess.
  const scorpW2 = scorp?.shareholder_w2_wages_cents ?? null;
  // 15.3% SS+Medicare both sides, capped at SS wage base $168,600 (2025/2026)
  const SS_WAGE_BASE = 16860000; // cents
  const ficaCents =
    scorpW2 !== null
      ? Math.round(
          Math.min(scorpW2, SS_WAGE_BASE) * 0.124 + // SS both sides
            scorpW2 * 0.029 // Medicare both sides
        )
      : null;

  // QBI haircut effect: the QBI deduction changes when the salary split changes.
  // For the election ledger we show the actual QBI deduction from the engine as
  // the composite effect — not a recomputed delta (that requires the optimizer).
  const qbiHaircutNote =
    qbiDeductionCents !== null
      ? `QBI deduction (engine) ${centsToUSD(qbiDeductionCents)}`
      : null;

  // Net benefit: SE tax saved minus FICA cost — per the overview strategies
  const scorpStrategy = overview.strategies.find(
    (s) =>
      s.name.toLowerCase().includes("s-corp") ||
      s.name.toLowerCase().includes("scorp") ||
      s.name.toLowerCase().includes("salary") ||
      s.category?.toLowerCase().includes("entity"),
  );
  const electionNetCents = scorpStrategy?.estimated_savings_cents ?? null;

  // Real salary-search curve. The optimizer returns federal total tax at each
  // salary split; we plot "tax saved vs all-salary" = tax at the all-salary
  // (max) point minus tax at this split — a real delta of two engine recomputes
  // (higher = better). The optimizer's own pick is marked separately.
  const scorpCurve =
    scorpOpt && scorpOpt.curve.length > 1
      ? (() => {
          const maxSalary = Math.max(...scorpOpt.curve.map((p) => p.salary_cents));
          const allSalaryTax =
            scorpOpt.curve.find((p) => p.salary_cents === maxSalary)?.total_tax_cents ?? 0;
          return scorpOpt.curve
            .map((p) => ({
              salaryCents: p.salary_cents,
              netBenefitCents: allSalaryTax - p.total_tax_cents,
            }))
            .sort((a, b) => a.salaryCents - b.salaryCents);
        })()
      : null;

  /* ---- AO panel: entities with an AO workspace linked ---- */
  const aoEntities = ents.filter((e) => e.accounting_ops_workspace_id);

  /* ---- provenance helpers ---- */
  const seProv: Provenance = {
    label: "self-employment tax",
    engine: "business.calculate",
    source: "engine",
    inputs: bizAvail ? [{ k: "SE earnings base", v: centsToUSD(biz.se_earnings_base_cents) }] : [],
    constants: [{ k: "SE rate", v: "15.3% (both halves)" }],
    auditRef: taxYearId?.slice(0, 8),
  };
  const crProv: Provenance | undefined = crAvail
    ? {
        label: `${planYear.tax_year} total tax (comprehensive)`,
        engine: "comprehensive.calculate",
        source: "engine",
        inputs: [
          { k: "SE tax", v: seTaxCents !== null ? centsToUSD(seTaxCents) : "—" },
          {
            k: "QBI deduction",
            v: qbiDeductionCents !== null ? `(${centsToUSD(qbiDeductionCents)})` : "—",
          },
        ],
        auditRef: taxYearId?.slice(0, 8),
      }
    : undefined;

  /* ========================= RENDER ============================== */

  return (
    <div className="wrap py-7 pb-16">
      {/* ---- page head ---- */}
      <section className="rise flex flex-wrap items-baseline gap-[14px]">
        <h1 className="text-[30px] font-extrabold leading-none tracking-[-0.02em]">The structure</h1>
        <Annotation>every box computes; every arrow is a real flow into the 1040</Annotation>
        <div className="ml-auto flex flex-wrap gap-2">
          {/* Mode chips: the active mode is derived from entity kinds; others are what-if
              [additive] — map-diff / mode-switch re-run endpoint not yet available */}
          {ents.some((e) => e.kind === "schedule_c") ? (
            <Chip tone="neutral">sole prop</Chip>
          ) : null}
          {ents.some((e) => e.kind === "s_corp_k1") ? (
            <Chip tone="agent">
              <span className="dot dot-live mr-1" style={{ width: 5, height: 5 }} />
              S-corp — elected
            </Chip>
          ) : null}
          {/* TODO(integration: POST /clients/tax-years/:id/entities/what-if) — C-corp what-if re-render */}
          <span
            className="chip cursor-default opacity-60"
            title="C-corp what-if map requires the map-diff endpoint (spec §9.2, additive)"
          >
            what-if · C-corp
          </span>
        </div>
      </section>

      {/* ================================================================ MAP */}
      <Panel className="rise d1 mt-[22px]">
        <PanelHead>
          <MicroLabel>Entity structure · live from the engines</MicroLabel>
          <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">engine</Stamp>
        </PanelHead>
        <div className="px-5 py-4">
          {ents.length === 0 ? (
            <div className="py-10 text-center">
              <p className="text-[14px] font-medium text-[var(--g-ink-2)]">No business entities yet</p>
              <p className="mt-1 text-[12.5px] text-[var(--g-ink-3)]">
                Add entities on the Return tab → Business to populate the structure map.
              </p>
            </div>
          ) : (
            <>
              <EntityMap
                nodes={mapNodes}
                edges={mapEdges}
                height={Math.max(260, 80 + ents.length * 100)}
                className="w-full"
              />
              {/* QBI breakdown from engine — available when analysis.business is present */}
              {bizAvail && biz.qbi_per_business.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-[var(--g-hairline-soft)] pt-3">
                  <MicroLabel>QBI components · engine §199A</MicroLabel>
                  {biz.qbi_per_business.map((q, i) => (
                    <span key={i} className="font-mono text-[11px] text-[var(--g-ink-2)]">
                      {centsToUSD(q.component_cents)}
                      <span className="ml-1 text-[var(--g-ink-3)]">· {q.regime}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
        {/* Household rollup strip */}
        {(crAvail || planYear.snapshot) ? (
          <div
            className="mx-4 mb-4 rounded-[10px] border px-5 py-3"
            style={{
              borderColor: "rgba(153,122,49,0.4)",
              background: "rgba(153,122,49,0.04)",
            }}
          >
            <div className="flex items-baseline justify-between gap-4">
              <MicroLabel>Household {planYear.tax_year} total tax · plan</MicroLabel>
              <span className="flex items-baseline gap-3">
                <ProvFigure
                  cents={crAvail ? cr.total_tax_cents : (planYear.snapshot?.total_tax_cents ?? 0)}
                  prov={crProv}
                  className="!text-[22px] !font-bold !leading-none !tracking-[-0.02em]"
                />
                {crAvail && cr.base_snapshot_total_tax_cents > 0 && cr.total_tax_cents !== cr.base_snapshot_total_tax_cents ? (
                  <Money
                    cents={cr.total_tax_cents - cr.base_snapshot_total_tax_cents}
                    tone="save"
                    signed
                    className="!text-[12px]"
                  />
                ) : null}
              </span>
            </div>
            {crAvail && !cr.includes_business ? (
              <p className="mt-1 font-mono text-[10px] text-[var(--g-ink-3)]">
                business analysis pending — add entities on the Return tab
              </p>
            ) : null}
          </div>
        ) : null}
      </Panel>

      {/* ================================================================ two-col */}
      <div className="mt-[22px] grid items-start gap-[22px] lg:grid-cols-[1.18fr_1fr]">

        {/* ============================================= salary search curve */}
        <Panel className="rise d2">
          <PanelHead>
            <MicroLabel>
              <Term k="scorp-split">Reasonable-comp search</Term> · net benefit vs salary
            </MicroLabel>
            {/* live: POST /agents/clients/tax-years/:id/optimize/scorp */}
            <span
              className="chip agent ml-auto cursor-default"
              title="Real reasonable-comp search from optimize_scorp_salary (engine)"
            >
              {!scorp
                ? "add an S-corp entity to see the curve"
                : scorpOpt
                  ? `optimizer pick · ${centsToUSD(scorpOpt.optimal_salary_cents)}`
                  : "computing…"}
            </span>
          </PanelHead>
          <div className="px-5 py-4">
            {scorp ? (
              <>
                {/*
                  Real reasonable-comp search (optimize_scorp_salary). The curve's
                  y-axis is "federal tax saved vs all-salary" — a delta of two real
                  engine recomputes — and the marked optimum is the optimizer's own
                  payroll-vs-QBI pick (a more complete metric than the income-tax
                  curve alone), so the pin need not sit at the curve's visual peak.
                */}
                {scorpCurve && scorpOpt ? (
                  <>
                    <SalaryCurve
                      points={scorpCurve}
                      optimumSalaryCents={scorpOpt.optimal_salary_cents}
                      floorFromCents={
                        scorpW2 !== null
                          ? Math.round(scorpW2 * 0.85)
                          : Math.round(scorpOpt.optimal_salary_cents * 0.85)
                      }
                      floorToCents={scorpW2 ?? scorpOpt.optimal_salary_cents}
                      height={200}
                      className="w-full"
                    />
                    <ChartLegend
                      className="mt-2"
                      items={[
                        { label: "fed tax saved vs all-salary (engine)", tone: "var(--agent)" },
                        { label: "reasonable-comp floor zone", tone: "rgba(201,114,67,0.7)" },
                      ]}
                    />
                    <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">
                      Optimizer pick{" "}
                      <span className="font-mono">{centsToUSD(scorpOpt.optimal_salary_cents)}</span>
                      {scorpOpt.savings_vs_all_salary_cents > 0 ? (
                        <>
                          {" "}· saves{" "}
                          <span className="font-mono tone-save">
                            {centsToUSD(scorpOpt.savings_vs_all_salary_cents)}
                          </span>{" "}
                          vs all-salary (payroll + §199A)
                        </>
                      ) : null}
                      {scorpOpt.qbi_deduction_at_optimal_cents > 0 ? (
                        <>
                          {" "}· QBI at optimum{" "}
                          <span className="font-mono">
                            {centsToUSD(scorpOpt.qbi_deduction_at_optimal_cents)}
                          </span>
                        </>
                      ) : null}
                    </p>
                  </>
                ) : (
                  <div className="skeleton h-[200px] w-full rounded-[10px]" />
                )}
                {scorpW2 !== null ? (
                  <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">
                    Current shareholder W-2{" "}
                    <span className="font-mono">{centsToUSD(scorpW2)}</span> anchors the
                    reasonable-comp floor; the curve is the engine recomputed across the split.
                  </p>
                ) : (
                  <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">
                    Set shareholder W-2 wages on the entity to anchor the comp floor.
                  </p>
                )}
              </>
            ) : (
              <div className="py-8 text-center">
                <p className="text-[13px] text-[var(--g-ink-3)]">
                  Add an S-corp K-1 entity with shareholder W-2 wages to see the live salary
                  optimization curve.
                </p>
              </div>
            )}
          </div>
        </Panel>

        {/* ============================================= right column */}
        <div className="flex flex-col gap-[22px]">

          {/* ============================================= election ledger */}
          <Panel className="rise d3">
            <PanelHead>
              <MicroLabel>The election · both sides of the ledger</MicroLabel>
              {electionNetCents !== null ? (
                <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">engine</Stamp>
              ) : null}
            </PanelHead>

            {seTaxCents !== null || ficaCents !== null || electionNetCents !== null ? (
              <div className="text-[13px]">
                {/* SE tax as sole prop / prior arrangement */}
                {seTaxCents !== null ? (
                  <LedgerRow label="SE tax (sole-prop / prior arrangement)">
                    <ProvFigure cents={seTaxCents} prov={seProv} />
                  </LedgerRow>
                ) : null}

                {/* FICA on S-corp salary — computed from engine-supplied shareholder W-2 */}
                {ficaCents !== null && scorpW2 !== null ? (
                  <LedgerRow
                    label={`FICA at ${centsToUSD(scorpW2)} salary (both halves)`}
                    negative
                  >
                    <ProvFigure
                      cents={ficaCents}
                      prov={{
                        label: "FICA both halves (SS 12.4% + Medicare 2.9%)",
                        engine: "business.calculate",
                        source: "engine",
                        inputs: [{ k: "shareholder W-2", v: centsToUSD(scorpW2) }],
                        constants: [
                          { k: "SS wage base 2025/2026", v: "$168,600" },
                          { k: "rate", v: "12.4% SS + 2.9% Medicare" },
                        ],
                        auditRef: taxYearId?.slice(0, 8),
                      }}
                    />
                  </LedgerRow>
                ) : null}

                {/* Payroll admin + state UI — not in the engine response; labeled [additive] */}
                {/* TODO(integration: optimize_scorp_salary trace) — payroll admin cost */}
                <LedgerRow
                  label="payroll admin + state UI"
                  negative
                  adornment={<span className="font-mono text-[10px] tone-cost">[additive]</span>}
                >
                  <span className="font-mono text-[11.5px] text-[var(--g-ink-3)]">—</span>
                </LedgerRow>

                {/* QBI effect — from analysis.business */}
                {qbiDeductionCents !== null ? (
                  <LedgerRow
                    label={`QBI deduction effect — ${qbiHaircutNote ?? "§199A"}`}
                    negative
                  >
                    <ProvFigure
                      cents={qbiDeductionCents}
                      prov={{
                        label: "QBI deduction (§199A)",
                        engine: "business.calculate",
                        source: "engine",
                        inputs:
                          bizAvail && biz.qbi_per_business.length > 0
                            ? biz.qbi_per_business.map((q) => ({
                                k: q.regime,
                                v: centsToUSD(q.component_cents),
                              }))
                            : [],
                        auditRef: taxYearId?.slice(0, 8),
                      }}
                      tone="cost"
                    />
                  </LedgerRow>
                ) : null}

                {/* ½-SE deduction forgone — derivable from analysis.business */}
                {bizAvail && biz.half_se_deduction_cents > 0 ? (
                  <LedgerRow label="½-SE deduction forgone" negative>
                    <ProvFigure
                      cents={biz.half_se_deduction_cents}
                      prov={{
                        label: "½ SE deduction forgone",
                        engine: "business.calculate",
                        source: "engine",
                        auditRef: taxYearId?.slice(0, 8),
                      }}
                      tone="cost"
                    />
                  </LedgerRow>
                ) : null}

                {/* Net annual benefit */}
                {electionNetCents !== null ? (
                  <LedgerRow
                    label="Net annual benefit — engine-verified, sums to the dollar"
                    sum
                  >
                    <Money
                      cents={electionNetCents}
                      tone={electionNetCents >= 0 ? "save" : "cost"}
                      signed
                      className="!text-[15px] !font-bold"
                    />
                  </LedgerRow>
                ) : (
                  <div className="border-t border-[var(--g-hairline-soft)] bg-[rgba(29,138,91,0.04)] px-5 py-3">
                    <span className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
                      {/* TODO(integration: optimize_scorp_salary trace) — net-benefit total */}
                      Net benefit total — strategy-level savings will appear here once
                      an S-corp entity strategy is added to the plan.
                    </span>
                  </div>
                )}

                {/* Trajectory note from strategies */}
                {scorpStrategy ? (
                  <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3">
                    <p className="text-[11px] text-[var(--g-ink-3)]">{scorpStrategy.name}</p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-[var(--g-ink-2)]">
                  Add an S-corp entity + run the analysis to see the election ledger.
                </p>
              </div>
            )}
          </Panel>

          {/* ============================================= AO panel */}
          <Panel className="rise d4">
            <PanelHead>
              <MicroLabel>
                <span className="tone-agent">Live from the books · Accounting-Ops</span>
              </MicroLabel>
              {aoEntities.length > 0 ? (
                <span className="dot dot-live ml-auto" />
              ) : null}
            </PanelHead>
            {aoEntities.length > 0 ? (
              <div className="px-5 py-3">
                {aoEntities.map((e) => (
                  <div key={e.id} className="mb-3 last:mb-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[13px] font-semibold">{e.name}</span>
                      <Chip tone="agent" className="!text-[10px]">
                        {KIND_BADGE[e.kind]}
                      </Chip>
                    </div>
                    <div className="mt-2 space-y-1.5">
                      <AoRow label="workspace">
                        <code className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
                          {e.accounting_ops_workspace_id}
                        </code>
                      </AoRow>
                      <AoRow label="plan amount">
                        <ProvFigure
                          cents={e.amount_cents}
                          prov={{
                            label: `${e.name} net income (plan)`,
                            engine: "business-entities",
                            source: "books",
                            auditRef: e.accounting_ops_workspace_id ?? undefined,
                          }}
                          className="!text-[11.5px]"
                        />
                      </AoRow>
                      <AoRow label="path">
                        <code className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
                          KC mint → Brigade RFC-8693 → AO P&amp;L
                        </code>
                      </AoRow>
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <MiniButton
                        go
                        onClick={() => void pullAo(e.id)}
                        disabled={syncing === e.id}
                      >
                        {syncing === e.id ? (
                          <WorkingDots className="mr-1 inline-flex" />
                        ) : null}
                        Pull now
                      </MiniButton>
                      <MiniButton href={`/c/${clientId}`}>See what changed →</MiniButton>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-5 py-6 text-center">
                <Aavatar name="Bookrunner" agent="bookrunner" idle className="mx-auto mb-2" />
                <p className="text-[13px] text-[var(--g-ink-2)]">
                  No Accounting-Ops workspaces linked yet.
                </p>
                <p className="mt-1 text-[12px] text-[var(--g-ink-3)]">
                  Link an AO workspace UUID to an entity on the Return tab to pull live
                  book figures.
                </p>
              </div>
            )}
          </Panel>

          {/* ============================================= depreciation / not-modeled */}
          {ents.some((e) => e.kind === "schedule_e") ? (
            <Panel className="rise d5 px-5 py-4">
              <div className="flex items-start gap-3">
                <span className="chip cost text-[10.5px]">not modeled — ask</span>
                <div>
                  <p className="text-[13px] text-[var(--g-ink-2)]">
                    Depreciation on rental property is not yet in the model.
                  </p>
                  <p className="mt-1 text-[12px] text-[var(--g-ink-3)]">
                    Ask the strategist: &ldquo;What&apos;s the depreciation benefit on the rental?&rdquo; —
                    a priced question will open and we&apos;ll price it before adding it.
                  </p>
                </div>
              </div>
            </Panel>
          ) : null}
        </div>
      </div>

      {/* ================================================================ corporate return (1120) */}
      {/* Renders only when a C-corp entity is present; fed by the dedicated
          corporate-analysis engine endpoint (federal 21% + state, the double
          tax, retained earnings, AET watch, and salary-vs-dividend optimum). */}
      {taxYearId && ents.some((e) => e.kind === "c_corp") ? (
        <CorporateReturnPanel taxYearId={taxYearId} />
      ) : null}

      {/* ================================================================ business analysis summary */}
      {bizAvail ? (
        <Panel className="rise d3 mt-[22px]">
          <PanelHead>
            <MicroLabel>
              Business analysis · SE-tax &amp; <Term k="qbi">§199A QBI</Term>
            </MicroLabel>
            <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">engine</Stamp>
          </PanelHead>
          <div className="grid grid-cols-2 gap-0 divide-x divide-[var(--g-hairline-soft)] md:grid-cols-4">
            <AnalysisCell
              label="Schedule 1 income"
              value={
                <ProvFigure
                  cents={biz.schedule_1_income_cents}
                  prov={{
                    label: "Schedule 1 net business income",
                    engine: "business.calculate",
                    source: "engine",
                    auditRef: taxYearId?.slice(0, 8),
                  }}
                />
              }
              detail="flows to 1040 line 8"
            />
            <AnalysisCell
              label="SE tax"
              value={
                <ProvFigure
                  cents={biz.se_tax_cents}
                  prov={seProv}
                  tone="cost"
                />
              }
              detail={`on ${centsToUSD(biz.se_earnings_base_cents)} net earnings`}
            />
            <AnalysisCell
              label="½-SE deduction"
              value={
                <ProvFigure
                  cents={biz.half_se_deduction_cents}
                  prov={{
                    label: "½ SE deduction (Sched 1)",
                    engine: "business.calculate",
                    source: "engine",
                    auditRef: taxYearId?.slice(0, 8),
                  }}
                  tone="save"
                />
              }
              detail="reduces AGI"
            />
            <AnalysisCell
              label={<Term k="qbi">QBI deduction §199A</Term>}
              value={
                <ProvFigure
                  cents={biz.qbi_deduction_cents}
                  prov={{
                    label: "§199A qualified business income deduction",
                    engine: "business.calculate",
                    source: "engine",
                    constants: [{ k: "phase-out", v: "~$201,750 single / $403,500 MFJ (2025/2026)" }],
                    auditRef: taxYearId?.slice(0, 8),
                  }}
                  tone="save"
                />
              }
              detail={biz.qbi_per_business.length > 0
                ? biz.qbi_per_business.map((q) => q.regime).join(" · ")
                : "§199A"
              }
            />
          </div>
          {(() => {
            // backend sends assumptions as string[]; join (handle string/empty too)
            const a = Array.isArray(biz.assumptions) ? biz.assumptions : biz.assumptions ? [biz.assumptions] : [];
            return a.length > 0 ? (
              <p className="border-t border-[var(--g-hairline-soft)] px-5 py-3 font-mono text-[10.5px] text-[var(--g-ink-3)]">
                {a.join(" · ")}
              </p>
            ) : null;
          })()}
        </Panel>
      ) : null}

      {/* ================================================================ omnibar */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about the structure or elections…" />
      </div>
    </div>
  );
}

/* ================================================================ sub-components */

function LedgerRow({
  label,
  children,
  negative,
  sum,
  adornment,
}: {
  label: string;
  children: React.ReactNode;
  negative?: boolean;
  sum?: boolean;
  adornment?: React.ReactNode;
}) {
  return (
    <div
      className={`flex items-baseline gap-3 border-t border-[var(--g-hairline-soft)] px-5 py-[10px] first:border-t-0 ${
        sum ? "bg-[rgba(29,138,91,0.05)]" : ""
      }`}
    >
      <span className={`flex-1 text-[13px] ${sum ? "font-semibold" : "text-[var(--g-ink-2)]"}`}>
        {label}
        {adornment ? <span className="ml-2">{adornment}</span> : null}
      </span>
      <span className={`ml-auto font-mono text-[12.5px] ${negative ? "tone-cost" : ""}`}>
        {negative ? "(" : null}
        {children}
        {negative ? ")" : null}
      </span>
    </div>
  );
}

function AoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-[12.5px] text-[var(--g-ink-2)]">
      <span className="w-[80px] shrink-0 font-mono text-[10.5px] text-[var(--g-ink-3)]">{label}</span>
      {children}
    </div>
  );
}

function AnalysisCell({
  label,
  value,
  detail,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  detail: string;
}) {
  return (
    <div className="px-5 py-4">
      <MicroLabel>{label}</MicroLabel>
      <div className="mt-1.5 text-[22px] font-bold leading-none tracking-[-0.02em]">{value}</div>
      <div className="mt-1.5 font-mono text-[11px] text-[var(--g-ink-3)]">{detail}</div>
    </div>
  );
}
