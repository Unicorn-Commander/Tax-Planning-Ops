"use client";

// Corporate Return (1120) planning panel — Surface 08 (Entities) C-corp section.
//
// Renders the integrated double-tax picture for the C-corp(s) on a tax year,
// fed entirely by GET /clients/tax-years/:id/corporate-analysis. The corporate
// stack (federal 21% + state), the double tax (corp tax + owner salary/dividend
// tax), retained earnings, the accumulated-earnings-tax watch, and the
// salary-vs-dividend optimization (the SalaryCurve primitive, fed the endpoint's
// engine-computed integrated-total curve + optimal split).
//
// HARD INVARIANT (Honesty Protocol): every dollar comes from an API field; this
// component NEVER computes tax client-side. The curve, the optimum, and the
// savings are the engine's output rendered verbatim.

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Stamp,
  Money,
  ProvFigure,
  SalaryCurve,
  ChartLegend,
  Term,
  type Provenance,
} from "@/components/kit";

/* ======================================================== wire shapes ======= */

interface CorporateReturn {
  pre_nol_taxable_income_cents: number;
  book_to_tax_adjustment_cents: number;
  nol_applied_cents: number;
  nol_carryforward_remaining_cents: number;
  corporate_taxable_income_cents: number;
  federal_corporate_tax_cents: number;
  state: string | null;
  state_has_corporate_tax: boolean;
  state_corporate_tax_cents: number;
  state_marginal_rate: string | null;
  total_corporate_tax_cents: number;
  effective_corporate_rate: string;
}

interface AETWatch {
  accumulated_taxable_income_cents: number;
  credit_cents: number;
  amount_over_credit_cents: number;
  estimated_aet_cents: number;
  exposed: boolean;
  is_psc: boolean;
  note: string;
}

interface DoubleTax {
  owner_salary_cents: number;
  owner_dividends_cents: number;
  corporate_tax_cents: number;
  owner_personal_tax_cents: number;
  owner_payroll_tax_cents: number;
  integrated_total_tax_cents: number;
  retained_earnings_cents: number;
}

interface SplitPoint {
  salary_cents: number;
  dividends_cents: number;
  corporate_taxable_income_cents: number;
  corporate_tax_cents: number;
  owner_personal_tax_cents: number;
  owner_payroll_tax_cents: number;
  integrated_total_tax_cents: number;
}

interface Optimization {
  comp_pool_cents: number;
  current_salary_cents: number;
  current_dividends_cents: number;
  optimal_salary_cents: number;
  optimal_dividends_cents: number;
  optimal_integrated_total_tax_cents: number;
  current_integrated_total_tax_cents: number;
  savings_vs_current_cents: number;
  step_cents: number;
  curve: SplitPoint[];
  assumptions: string[];
}

interface CorporateSource {
  from_accounting_ops: boolean;
  synced_at: string | null;
  period: string | null;
  book_net_income_cents: number | null;
}

interface CorporateAnalysis {
  available: boolean;
  reason?: string | null;
  client_tax_year_id: string;
  client_name: string | null;
  tax_year: number;
  state: string | null;
  entity_count: number;
  entities: string[];
  corporate_return: CorporateReturn | null;
  aet: AETWatch | null;
  double_tax: DoubleTax | null;
  optimization: Optimization | null;
  source?: CorporateSource | null;
  assumptions: string[];
}

/* ======================================================== component ========= */

export function CorporateReturnPanel({ taxYearId }: { taxYearId: string }) {
  const [data, setData] = useState<CorporateAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setErrored(false);
    api
      .get(`/clients/tax-years/${taxYearId}/corporate-analysis`)
      .then((r) => {
        if (live) setData(r.data);
      })
      .catch(() => {
        if (live) setErrored(true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [taxYearId]);

  if (loading) {
    return (
      <Panel className="rise mt-[22px] p-5">
        <div className="skeleton h-[360px] w-full rounded-[10px]" />
      </Panel>
    );
  }

  if (errored) {
    return (
      <Panel className="rise mt-[22px] px-5 py-8 text-center">
        <p className="text-[13px] text-[var(--g-ink-2)]">
          Couldn&apos;t load the corporate return analysis.
        </p>
        <p className="mt-1 text-[12px] text-[var(--g-ink-3)]">
          The 1120 engine endpoint didn&apos;t respond — retry from the Return tab.
        </p>
      </Panel>
    );
  }

  // No C-corp on this year (or no analysis): render nothing so the panel only
  // appears when there's a C-corp to plan — the page already shows pass-through
  // entities above.
  if (!data || !data.available || !data.corporate_return) {
    return null;
  }

  const cr = data.corporate_return;
  const dt = data.double_tax;
  const aet = data.aet;
  const opt = data.optimization;

  const auditRef = taxYearId.slice(0, 8);
  const stateLabel = cr.state ?? "—";

  // The corporate-tax stack figures, each interrogable, engine-sourced.
  const fedProv: Provenance = {
    label: "federal corporate tax (Form 1120, 21%)",
    engine: "corporate.calculate",
    source: "engine",
    inputs: [
      { k: "corporate taxable income", v: centsToUSD(cr.corporate_taxable_income_cents) },
    ],
    constants: [{ k: "federal rate", v: "21% flat (§11)" }],
    auditRef,
  };
  const stateProv: Provenance = {
    label: `state corporate tax (${stateLabel})`,
    engine: "corporate.calculate_state",
    source: "engine",
    inputs: [
      { k: "state taxable income", v: centsToUSD(cr.corporate_taxable_income_cents) },
    ],
    constants: [
      { k: `${stateLabel} rate`, v: cr.state_marginal_rate ? percent(cr.state_marginal_rate) : "—" },
    ],
    auditRef,
  };

  /* The optimization curve → SalaryCurve points. The chart's "net benefit" axis
     is savings relative to the WORST (max integrated tax) split on the curve, so
     higher = better and the optimum pins at the engine's chosen split. Every
     value is the endpoint's engine output; we only re-base for the visual. */
  const curvePoints =
    opt && opt.curve.length > 1
      ? (() => {
          const worst = Math.max(...opt.curve.map((p) => p.integrated_total_tax_cents));
          return opt.curve
            .map((p) => ({
              salaryCents: p.salary_cents,
              netBenefitCents: worst - p.integrated_total_tax_cents,
            }))
            .sort((a, b) => a.salaryCents - b.salaryCents);
        })()
      : null;

  return (
    <Panel className="rise mt-[22px]">
      <PanelHead>
        <MicroLabel>
          <Term k="c-corp-1120">Corporate Return (1120)</Term> · the double tax, engine-computed
        </MicroLabel>
        <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">
          engine
        </Stamp>
      </PanelHead>

      <div className="px-5 py-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Annotation>
            {data.entity_count === 1
              ? data.entities[0]
              : `${data.entity_count} C-corps`}{" "}
            · {data.tax_year}
            {cr.state ? ` · ${cr.state}` : ""}
          </Annotation>
          <span className="ml-auto font-mono text-[11px] text-[var(--g-ink-3)]">
            effective corporate rate {percent(cr.effective_corporate_rate)}
          </span>
        </div>

        {/* source provenance — the "honest notes": a synced figure is BOOK net
            income (a snapshot), reconciled to taxable income by the M-1 adjustment */}
        {data.source?.from_accounting_ops ? (
          <div className="mt-2 rounded-[8px] border border-[var(--g-hairline-soft)] bg-[var(--wash)] px-3 py-2 text-[11px] leading-relaxed text-[var(--g-ink-2)]">
            <span className="font-medium text-[var(--g-ink)]">Sourced from Accounting-Ops</span>
            {data.source.book_net_income_cents != null ? (
              <> · book net income {centsToUSD(data.source.book_net_income_cents)}</>
            ) : null}
            {cr.book_to_tax_adjustment_cents ? (
              <>
                {" "}
                {cr.book_to_tax_adjustment_cents > 0 ? "+" : "−"} M-1 adj{" "}
                {centsToUSD(Math.abs(cr.book_to_tax_adjustment_cents))} = taxable{" "}
                {centsToUSD(cr.pre_nol_taxable_income_cents)}
              </>
            ) : (
              <> · used as-is — no M-1 book-to-tax adjustment set (book income ≠ taxable income)</>
            )}
            {data.source.synced_at ? (
              <span className="text-[var(--g-ink-3)]">
                {" "}
                · synced {data.source.synced_at.slice(0, 10)}
                {data.source.period ? ` · period ${data.source.period}` : ""}
              </span>
            ) : null}
          </div>
        ) : null}

        {/* ===================================================== corporate stack */}
        <div className="mt-3 grid grid-cols-2 gap-0 divide-x divide-[var(--g-hairline-soft)] rounded-[10px] border border-[var(--g-hairline-soft)] md:grid-cols-4">
          <StackCell label="Pre-NOL taxable income">
            <ProvFigure
              cents={cr.pre_nol_taxable_income_cents}
              prov={{
                label: "corporate taxable income before NOL",
                engine: "corporate.calculate",
                source: "engine",
                auditRef,
              }}
            />
          </StackCell>
          <StackCell label="NOL applied (§172)">
            <ProvFigure
              cents={cr.nol_applied_cents}
              prov={{
                label: "NOL deduction (80% of pre-NOL income limit)",
                engine: "corporate.calculate",
                source: "engine",
                constants: [{ k: "limit", v: "80% of pre-NOL taxable income" }],
                auditRef,
              }}
              tone="save"
            />
          </StackCell>
          <StackCell label="Federal corp tax · 21%">
            <ProvFigure cents={cr.federal_corporate_tax_cents} prov={fedProv} tone="cost" />
          </StackCell>
          <StackCell
            label={cr.state_has_corporate_tax ? `State corp tax · ${stateLabel}` : "State corp tax"}
          >
            {cr.state_has_corporate_tax ? (
              <ProvFigure
                cents={cr.state_corporate_tax_cents}
                prov={stateProv}
                tone="cost"
              />
            ) : (
              <span className="font-mono text-[12px] text-[var(--g-ink-3)]">
                {cr.state ? "no state corp tax" : "—"}
              </span>
            )}
          </StackCell>
        </div>

        {/* total corporate tax strip */}
        <div
          className="mt-3 flex items-baseline justify-between gap-4 rounded-[10px] border px-5 py-3"
          style={{ borderColor: "rgba(153,122,49,0.4)", background: "rgba(153,122,49,0.04)" }}
        >
          <MicroLabel>Total corporate tax · federal + state</MicroLabel>
          <ProvFigure
            cents={cr.total_corporate_tax_cents}
            prov={{
              label: "total corporate tax (federal + state)",
              engine: "corporate.calculate",
              source: "engine",
              inputs: [
                { k: "federal", v: centsToUSD(cr.federal_corporate_tax_cents) },
                { k: "state", v: centsToUSD(cr.state_corporate_tax_cents) },
              ],
              auditRef,
            }}
            tone="cost"
            className="!text-[22px] !font-bold !leading-none !tracking-[-0.02em]"
          />
        </div>
      </div>

      {/* ===================================================== two-col: double tax + AET */}
      <div className="grid items-start gap-0 border-t border-[var(--g-hairline-soft)] md:grid-cols-2 md:divide-x md:divide-[var(--g-hairline-soft)]">
        {/* the double tax */}
        {dt ? (
          <div className="px-5 py-4">
            <MicroLabel>The double tax · at the current salary / dividend split</MicroLabel>
            <div className="mt-2 text-[13px]">
              <TaxRow label={`Owner salary (deductible to corp) ${centsToUSD(dt.owner_salary_cents)}`}>
                <ProvFigure
                  cents={dt.owner_personal_tax_cents}
                  prov={{
                    label: "owner personal income tax on salary + dividends (Form 1040)",
                    engine: "form1040.calculate",
                    source: "engine",
                    inputs: [
                      { k: "salary → wages", v: centsToUSD(dt.owner_salary_cents) },
                      { k: "dividends → qualified", v: centsToUSD(dt.owner_dividends_cents) },
                    ],
                    auditRef,
                  }}
                  tone="cost"
                />
              </TaxRow>
              <TaxRow label="Owner payroll · employee-side FICA on the salary">
                <ProvFigure
                  cents={dt.owner_payroll_tax_cents}
                  prov={{
                    label: "employee-side FICA on the owner's W-2 salary",
                    engine: "corporate_analysis",
                    source: "engine",
                    constants: [{ k: "rate", v: "7.65% to wage base + 1.45% + 0.9% addl" }],
                    auditRef,
                  }}
                  tone="cost"
                />
              </TaxRow>
              <TaxRow label={`Dividends (not deductible) ${centsToUSD(dt.owner_dividends_cents)} · corp tax`}>
                <ProvFigure
                  cents={dt.corporate_tax_cents}
                  prov={{
                    label: "corporate tax (federal + state)",
                    engine: "corporate.calculate",
                    source: "engine",
                    auditRef,
                  }}
                  tone="cost"
                />
              </TaxRow>
              <div className="mt-1 flex items-baseline gap-3 border-t border-[var(--g-hairline-soft)] bg-[rgba(201,114,67,0.05)] px-0 pt-2">
                <span className="flex-1 text-[13px] font-semibold">
                  Integrated total tax · corp + owner
                </span>
                <Money
                  cents={dt.integrated_total_tax_cents}
                  tone="cost"
                  className="!text-[16px] !font-bold"
                />
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="flex-1 text-[12.5px] text-[var(--g-ink-2)]">
                  Retained earnings · the distribute-vs-retain alternative
                  <span className="ml-1 block font-mono text-[10px] text-[var(--g-ink-3)]">
                    corporate taxable income − corp tax − dividends
                  </span>
                </span>
                <ProvFigure
                  cents={dt.retained_earnings_cents}
                  prov={{
                    label: "retained earnings (corporate taxable income − corp tax − dividends)",
                    engine: "corporate_analysis",
                    source: "engine",
                    auditRef,
                  }}
                />
              </div>
            </div>
          </div>
        ) : null}

        {/* AET watch */}
        {aet ? (
          <div className="px-5 py-4">
            <div className="flex items-center gap-2">
              <MicroLabel>
                <Term k="acc-earnings-tax">Accumulated-earnings tax</Term> watch
              </MicroLabel>
              {aet.exposed ? (
                <Chip tone="cost" className="!text-[10px]">
                  exposed
                </Chip>
              ) : (
                <Chip tone="neutral" className="!text-[10px]">
                  within credit
                </Chip>
              )}
            </div>
            <div className="mt-2 text-[13px]">
              <TaxRow label="Accumulated taxable income (proxy)">
                <ProvFigure
                  cents={aet.accumulated_taxable_income_cents}
                  prov={{
                    label: "accumulated taxable income proxy",
                    engine: "corporate.calculate_aet",
                    source: "engine",
                    auditRef,
                  }}
                />
              </TaxRow>
              <TaxRow label={`Accumulated-earnings credit${aet.is_psc ? " (PSC)" : ""}`}>
                <ProvFigure
                  cents={aet.credit_cents}
                  prov={{
                    label: "accumulated-earnings credit",
                    engine: "corporate.calculate_aet",
                    source: "engine",
                    constants: [{ k: "credit", v: aet.is_psc ? "$150,000 (PSC)" : "$250,000" }],
                    auditRef,
                  }}
                  tone="save"
                />
              </TaxRow>
              <TaxRow label="Estimated AET · 20% over the credit">
                <ProvFigure
                  cents={aet.estimated_aet_cents}
                  prov={{
                    label: "estimated accumulated-earnings tax (20%)",
                    engine: "corporate.calculate_aet",
                    source: "engine",
                    inputs: [{ k: "over credit", v: centsToUSD(aet.amount_over_credit_cents) }],
                    constants: [{ k: "rate", v: "20% (§531)" }],
                    auditRef,
                  }}
                  tone={aet.exposed ? "cost" : undefined}
                />
              </TaxRow>
            </div>
            <p className="mt-2 font-mono text-[10px] leading-relaxed text-[var(--g-ink-3)]">
              {aet.note}
            </p>
          </div>
        ) : null}
      </div>

      {/* ===================================================== salary vs dividend optimization */}
      {opt && curvePoints ? (
        <div className="border-t border-[var(--g-hairline-soft)] px-5 py-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <MicroLabel>
              <Term k="salary-dividend">Salary vs dividend</Term> · minimise the integrated tax
            </MicroLabel>
            <span className="chip agent ml-auto cursor-default" title="Engine-swept split (corporate engine + Form 1040)">
              optimum salary · {centsToUSD(opt.optimal_salary_cents)}
            </span>
          </div>

          <div className="mt-3">
            <SalaryCurve
              points={curvePoints}
              optimumSalaryCents={opt.optimal_salary_cents}
              floorFromCents={opt.current_salary_cents}
              floorToCents={opt.current_salary_cents}
              height={210}
              className="w-full"
            />
            <ChartLegend
              className="mt-2"
              items={[
                { label: "integrated tax saved vs the worst split (engine)", tone: "var(--save)" },
                { label: "current salary", tone: "rgba(201,114,67,0.7)" },
              ]}
            />
          </div>

          {/* optimum vs current summary */}
          <div className="mt-3 grid grid-cols-2 gap-0 divide-x divide-[var(--g-hairline-soft)] rounded-[10px] border border-[var(--g-hairline-soft)] md:grid-cols-4">
            <StackCell label="Optimal salary">
              <ProvFigure
                cents={opt.optimal_salary_cents}
                prov={{
                  label: "integrated-tax-minimising salary",
                  engine: "corporate_analysis.optimize",
                  source: "engine",
                  auditRef,
                }}
              />
            </StackCell>
            <StackCell label="Optimal dividends">
              <ProvFigure
                cents={opt.optimal_dividends_cents}
                prov={{
                  label: "integrated-tax-minimising dividends",
                  engine: "corporate_analysis.optimize",
                  source: "engine",
                  auditRef,
                }}
              />
            </StackCell>
            <StackCell label="Integrated tax at optimum">
              <ProvFigure
                cents={opt.optimal_integrated_total_tax_cents}
                prov={{
                  label: "minimum integrated total tax (corp + owner)",
                  engine: "corporate_analysis.optimize",
                  source: "engine",
                  auditRef,
                }}
                tone="cost"
              />
            </StackCell>
            <StackCell label="Savings vs current split">
              <Money
                cents={opt.savings_vs_current_cents}
                tone={opt.savings_vs_current_cents > 0 ? "save" : undefined}
                signed
              />
            </StackCell>
          </div>

          <p className="mt-2 text-[12px] text-[var(--g-ink-3)]">
            The compensation pool ({centsToUSD(opt.comp_pool_cents)}) is held constant; the engine
            sweeps how much is paid as deductible salary (ordinary + payroll to the owner) vs
            non-deductible dividends (double-taxed, no payroll) and reports the real minimum of the
            combined corporate + owner tax.
          </p>

          {opt.assumptions.length > 0 ? (
            <details className="mt-2">
              <summary className="cursor-pointer font-mono text-[10.5px] text-[var(--g-ink-3)]">
                assumptions ({opt.assumptions.length})
              </summary>
              <ul className="mt-1 list-disc space-y-1 pl-5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
                {opt.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}

      {/* engine-level assumptions */}
      {data.assumptions.length > 0 ? (
        <p className="border-t border-[var(--g-hairline-soft)] px-5 py-3 font-mono text-[10.5px] text-[var(--g-ink-3)]">
          {data.assumptions.join(" · ")}
        </p>
      ) : null}
    </Panel>
  );
}

/* ================================================================ sub-components */

function StackCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3">
      <MicroLabel>{label}</MicroLabel>
      <div className="mt-1.5 text-[18px] font-bold leading-none tracking-[-0.02em]">{children}</div>
    </div>
  );
}

function TaxRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 border-t border-[var(--g-hairline-soft)] py-[9px] first:border-t-0">
      <span className="flex-1 text-[12.5px] text-[var(--g-ink-2)]">{label}</span>
      <span className="ml-auto font-mono text-[12.5px]">{children}</span>
    </div>
  );
}
