"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Brain, Briefcase, Building2, Calculator, FileText, HeartPulse, Landmark, LineChart, Lightbulb, Receipt, Sparkles, Target } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, Stat, Meter, EmptyState, Disclaimer } from "@/components/ui";

interface Unavailable {
  available: false;
  reason?: string;
}
interface AmtSection {
  available: true;
  amt_applies: boolean;
  amt_cents: number;
  tentative_minimum_tax_cents: number;
  regular_total_tax_cents: number;
  total_tax_cents: number;
  assumptions?: string | null;
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
interface MultiYearRow {
  tax_year: number;
  total_income_cents: number;
  taxable_income_cents: number;
  total_tax_cents: number;
  marginal_rate: string;
  config_source: string;
}
interface MultiYearSection {
  available: true;
  years: MultiYearRow[];
  cumulative_tax_cents: number;
  assumptions?: string | null;
}
interface OpportunityItem {
  code: string;
  name: string;
  category: string;
  citation: string;
  illustrative_amount_cents: number;
  estimated_tax_savings_cents: number;
  marginal_rate_used: string;
  eligibility_note: string;
}
interface OpportunitiesSection {
  available: true;
  total_illustrative_savings_cents: number;
  items: OpportunityItem[];
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
  assumptions?: string | null;
}

interface ComprehensiveReturnSection {
  available: true;
  base_snapshot_total_tax_cents: number;
  total_tax_cents: number;
  regular_total_tax_cents: number;
  se_tax_cents: number;
  amt_cents: number;
  qbi_deduction_cents: number;
  refundable_credits_cents: number;
  balance_due_cents: number;
  includes_business: boolean;
  // Present only when the client has a C-corp entity.
  corporate_tax_cents?: number;
  integrated_total_tax_cents?: number;
  has_c_corp?: boolean;
}

interface StateTaxSection {
  available: true;
  state: string;
  has_income_tax: boolean;
  state_tax_cents: number;
  state_marginal_rate: string;
  federal_plus_state_total_cents: number;
  assumptions: string[];
}

interface StrategistFinding {
  title: string;
  category: string;
  recommended_action: string;
  estimated_impact_cents: number;
  impact_kind: "savings" | "cost" | "info";
  citation: string;
  caveat: string;
}
interface TrajectoryPoint {
  tax_year: number;
  total_income_cents: number;
  taxable_income_cents: number;
  total_tax_cents: number;
  marginal_rate: string;
}
interface Trajectory {
  available: boolean;
  points: TrajectoryPoint[];
  summary?: string;
  income_direction?: string;
  irmaa_crossing?: boolean;
}
interface Strategist {
  client_name: string;
  tax_year: number;
  current_total_tax_cents: number;
  marginal_rate: string;
  findings: StrategistFinding[];
  total_savings_identified_cents: number;
  memo: string | null;
  memo_available: boolean;
  has_profile: boolean;
  objectives_summary: string | null;
  trajectory: Trajectory;
  disclaimer: string;
}

interface Analysis {
  client_name: string;
  tax_year: number;
  filing_status: string;
  comprehensive_return: ComprehensiveReturnSection | Unavailable;
  amt: AmtSection | Unavailable;
  irmaa: IrmaaSection | Unavailable;
  multi_year: MultiYearSection | Unavailable;
  opportunities: OpportunitiesSection | Unavailable;
  business: BusinessSection | Unavailable;
  state_tax: StateTaxSection | Unavailable;
}

interface Proposal {
  narrative: string | null;
  disclaimer: string;
}

function NotAvailable({ reason }: { reason?: string }) {
  return (
    <p className="px-5 py-4 text-[13px] text-muted">
      {reason ?? "Not available for this tax year."}
    </p>
  );
}

export default function AnalysisTab() {
  const { overview, loading } = useClientOverview();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [strategist, setStrategist] = useState<Strategist | null>(null);

  // The analysis endpoint is keyed by a client tax year id, not the client id.
  // Prefer the active plan year (same id strategies/quarterly use), fall back to
  // the confirmed base year.
  const taxYearId = overview?.plan_year_id ?? overview?.base_year_id ?? null;

  useEffect(() => {
    if (!taxYearId) {
      setAnalysisLoading(false);
      return;
    }
    setAnalysisLoading(true);
    setAnalysisError(null);
    api
      .get(`/clients/tax-years/${taxYearId}/analysis`)
      .then((r) => setAnalysis(r.data))
      .catch(() => setAnalysisError("Could not load planning analysis."))
      .finally(() => setAnalysisLoading(false));
  }, [taxYearId]);

  const propose = useAction(async () => {
    if (!taxYearId) return;
    const r = await api.post(`/agents/clients/${taxYearId}/propose-plan`, {});
    setProposal(r.data);
  });

  const runStrategist = useAction(async () => {
    if (!taxYearId) return;
    const r = await api.get(`/agents/clients/tax-years/${taxYearId}/strategist`);
    setStrategist(r.data);
  });

  if (loading || analysisLoading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;

  if (!taxYearId) {
    return (
      <EmptyState
        icon={<Activity className="h-5 w-5" />}
        title="No tax year yet"
        body="Import and confirm a return on the Return tab to run planning analysis."
        action={<Link href={`/clients/${overview?.client.id}`}><Button>Go to overview</Button></Link>}
      />
    );
  }

  if (analysisError || !analysis) {
    return (
      <EmptyState
        icon={<Activity className="h-5 w-5" />}
        title="Analysis unavailable"
        body={analysisError ?? "No analysis could be computed for this tax year."}
      />
    );
  }

  const { comprehensive_return, amt, irmaa, multi_year, opportunities, business, state_tax } = analysis;
  const maxYearTax =
    multi_year.available && multi_year.years.length > 0
      ? Math.max(...multi_year.years.map((y) => y.total_tax_cents), 1)
      : 1;

  return (
    <div className="space-y-6">
      {/* Comprehensive return — the full picture */}
      <Card>
        <CardHeader
          title="Comprehensive return"
          subtitle="Federal + Social Security + credits + AMT + self-employment & QBI"
        />
        {comprehensive_return.available ? (
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Total tax"
                value={centsToUSD(comprehensive_return.total_tax_cents)}
                icon={<Calculator className="h-4 w-4" />}
                sub={
                  comprehensive_return.includes_business
                    ? `Base 1040 ${centsToUSD(comprehensive_return.base_snapshot_total_tax_cents)} + business`
                    : "No business entities"
                }
              />
              <Stat
                label="Self-employment tax"
                value={centsToUSD(comprehensive_return.se_tax_cents)}
                icon={<Briefcase className="h-4 w-4" />}
              />
              <Stat
                label="§199A QBI deduction"
                value={centsToUSD(comprehensive_return.qbi_deduction_cents)}
                icon={<Receipt className="h-4 w-4" />}
              />
              <Stat
                label="Balance due"
                value={centsToUSD(comprehensive_return.balance_due_cents)}
                icon={<Activity className="h-4 w-4" />}
                sub={`AMT ${centsToUSD(comprehensive_return.amt_cents)} · refundable ${centsToUSD(comprehensive_return.refundable_credits_cents)}`}
              />
            </div>
            {comprehensive_return.has_c_corp ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Stat
                  label="Corporate tax (21%)"
                  value={centsToUSD(comprehensive_return.corporate_tax_cents)}
                  icon={<Building2 className="h-4 w-4" />}
                />
                <Stat
                  label="Integrated total tax"
                  value={centsToUSD(comprehensive_return.integrated_total_tax_cents)}
                  icon={<Calculator className="h-4 w-4" />}
                  sub="corporate + personal — the C-corp double tax"
                />
              </div>
            ) : null}
            {state_tax.available ? (
              state_tax.has_income_tax ? (
                <>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Stat
                      label={`State income tax (${state_tax.state})`}
                      value={centsToUSD(state_tax.state_tax_cents)}
                      icon={<Landmark className="h-4 w-4" />}
                      sub={`${percent(state_tax.state_marginal_rate)} marginal`}
                    />
                    <Stat
                      label="Federal + state total"
                      value={centsToUSD(state_tax.federal_plus_state_total_cents)}
                      icon={<Calculator className="h-4 w-4" />}
                    />
                  </div>
                  {state_tax.assumptions.length > 0 ? (
                    <p className="text-[12px] text-muted">{state_tax.assumptions.join(" · ")}</p>
                  ) : null}
                </>
              ) : (
                <>
                  <p className="text-[12.5px] text-muted">{state_tax.state} — no state income tax.</p>
                  {state_tax.assumptions.length > 0 ? (
                    <p className="text-[12px] text-muted">{state_tax.assumptions.join(" · ")}</p>
                  ) : null}
                </>
              )
            ) : (
              <p className="text-[12px] text-muted">
                {state_tax.reason ?? "State income tax not yet modeled for this client."}
              </p>
            )}
          </div>
        ) : (
          <NotAvailable reason={comprehensive_return.reason} />
        )}
      </Card>

      {/* AI Strategist — the headline "real analysis" feature */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-primary" />
              AI Strategist
            </span>
          }
          subtitle="Agent-drafted CPA memo — findings, citations, and a savings estimate"
          action={
            strategist ? (
              <div className="text-right">
                <div className="text-[16px] font-semibold text-positive tabular">
                  {centsToUSD(strategist.total_savings_identified_cents)}
                </div>
                <div className="text-[11px] text-muted">savings identified</div>
              </div>
            ) : null
          }
        />
        {strategist ? (
          <div className="space-y-5 p-5">
            <Stat
              label="Savings identified"
              tone="positive"
              value={centsToUSD(strategist.total_savings_identified_cents)}
              icon={<Sparkles className="h-4 w-4" />}
              sub={`${strategist.client_name} · ${strategist.tax_year} · current tax ${centsToUSD(
                strategist.current_total_tax_cents,
              )} · ${percent(strategist.marginal_rate)} marginal`}
            />

            {/* Objectives + trajectory — the context the memo reasons over */}
            {strategist.has_profile || strategist.trajectory.available ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2/40 px-4 py-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted">
                    <Target className="h-3.5 w-3.5" /> Client objectives
                  </div>
                  {strategist.objectives_summary ? (
                    <p className="text-[13px] leading-relaxed text-ink-2">{strategist.objectives_summary}</p>
                  ) : (
                    <p className="text-[13px] text-muted">
                      No objectives captured yet —{" "}
                      <Link href={`/clients/${overview?.client.id}/profile`} className="text-primary hover:underline">
                        set the client&apos;s goals
                      </Link>{" "}
                      to sharpen the analysis.
                    </p>
                  )}
                </div>
                <div className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2/40 px-4 py-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted">
                    <LineChart className="h-3.5 w-3.5" /> Income trajectory
                  </div>
                  {strategist.trajectory.available ? (
                    <>
                      <p className="text-[13px] leading-relaxed text-ink-2">{strategist.trajectory.summary}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {strategist.trajectory.points.map((pt) => (
                          <Badge key={pt.tax_year} tone="neutral">
                            {pt.tax_year}: {centsToUSD(pt.total_income_cents)}
                          </Badge>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-[13px] text-muted">
                      Need two or more years on file to chart a trajectory.
                    </p>
                  )}
                </div>
              </div>
            ) : null}

            {/* CPA-style memo */}
            <div className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2/50 px-4 py-4">
              <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted">
                <FileText className="h-3.5 w-3.5" />
                Strategist memo
              </div>
              {strategist.memo ? (
                <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">{strategist.memo}</p>
              ) : (
                <p className="text-[13.5px] text-muted">Memo unavailable — showing findings.</p>
              )}
            </div>

            {/* Findings */}
            {strategist.findings.length > 0 ? (
              <div className="overflow-hidden rounded-[var(--radius-md)] border border-line-2">
                <div className="divide-y divide-line-2">
                  {strategist.findings.map((f, i) => (
                    <div key={i} className="px-4 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[14.5px] font-medium text-ink">{f.title}</span>
                            <Badge tone="neutral">{f.category}</Badge>
                          </div>
                          <p className="mt-1 text-[13px] text-ink-2">{f.recommended_action}</p>
                          <p className="mt-1 text-[12px] text-muted">
                            {f.citation}
                            {f.caveat ? ` · ${f.caveat}` : ""}
                          </p>
                        </div>
                        <div className="shrink-0 text-right">
                          <div
                            className={
                              "text-[15px] font-semibold tabular " +
                              (f.impact_kind === "savings"
                                ? "text-positive"
                                : f.impact_kind === "cost"
                                  ? "text-warning"
                                  : "text-ink")
                            }
                          >
                            {centsToUSD(f.estimated_impact_cents)}
                          </div>
                          <div className="text-[11px] text-muted">
                            {f.impact_kind === "savings"
                              ? "est. savings"
                              : f.impact_kind === "cost"
                                ? "est. cost"
                                : "informational"}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-[13.5px] text-muted">No findings identified.</p>
            )}

            <p className="border-t border-line-2 pt-4 text-[12px] leading-relaxed text-muted">{strategist.disclaimer}</p>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3 p-5">
            <p className="max-w-md text-[13.5px] text-muted">
              Run the strategist to draft a CPA-style memo with prioritized, cited findings for this tax year.
            </p>
            <div className="shrink-0 text-right">
              {runStrategist.error ? (
                <p className="mb-1.5 text-[13px] text-negative">{runStrategist.error}</p>
              ) : null}
              <Button
                icon={<Brain className="h-4 w-4" />}
                loading={runStrategist.pending}
                onClick={() => void runStrategist.run()}
              >
                Run strategist analysis
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* AMT exposure */}
      <Card>
        <CardHeader title="AMT exposure" subtitle="Alternative minimum tax vs. regular tax" />
        {amt.available ? (
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Stat
                label="Total tax"
                value={centsToUSD(amt.total_tax_cents)}
                icon={<Calculator className="h-4 w-4" />}
                sub={`Regular tax ${centsToUSD(amt.regular_total_tax_cents)} · TMT ${centsToUSD(amt.tentative_minimum_tax_cents)}`}
              />
              <Stat
                label="AMT add-on"
                tone={amt.amt_applies ? "warning" : "positive"}
                value={
                  <span className="flex items-center gap-3">
                    {amt.amt_applies ? centsToUSD(amt.amt_cents) : centsToUSD(0)}
                    <Badge tone={amt.amt_applies ? "warning" : "positive"}>
                      {amt.amt_applies ? "AMT applies" : "No AMT"}
                    </Badge>
                  </span>
                }
                icon={<Activity className="h-4 w-4" />}
              />
            </div>
            {amt.assumptions ? <p className="text-[12px] text-muted">{amt.assumptions}</p> : null}
          </div>
        ) : (
          <NotAvailable reason={amt.reason} />
        )}
      </Card>

      {/* IRMAA */}
      <Card>
        <CardHeader
          title="IRMAA (Medicare surcharge)"
          subtitle="Income-related monthly adjustment amount"
          action={irmaa.available ? <Badge tone="primary">Tier {irmaa.tier}</Badge> : null}
        />
        {irmaa.available ? (
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Stat
                label="Annual surcharge"
                value={centsToUSD(irmaa.total_irmaa_annual_cents)}
                icon={<HeartPulse className="h-4 w-4" />}
              />
              <Stat
                label="Next cliff threshold"
                value={centsToUSD(irmaa.next_cliff_threshold_cents)}
                icon={<LineChart className="h-4 w-4" />}
              />
            </div>
            <div className="rounded-[var(--radius-md)] border border-warning-soft bg-warning-soft/40 px-4 py-3">
              <p className="text-[13.5px] text-ink">
                <span className="font-semibold tabular">{centsToUSD(irmaa.distance_to_next_cliff_cents)}</span> to the
                next IRMAA cliff{" "}
                <span className="text-muted">
                  (costs <span className="tabular">{centsToUSD(irmaa.cliff_cost_annual_cents)}</span>/yr)
                </span>
              </p>
              {irmaa.room_to_drop_one_tier_cents != null ? (
                <p className="mt-1 text-[12.5px] text-muted">
                  Room to drop one tier: <span className="tabular">{centsToUSD(irmaa.room_to_drop_one_tier_cents)}</span>
                </p>
              ) : null}
            </div>
            {irmaa.note ? <p className="text-[12px] text-muted">{irmaa.note}</p> : null}
          </div>
        ) : (
          <NotAvailable reason={irmaa.reason} />
        )}
      </Card>

      {/* Business — SE tax & QBI */}
      <Card>
        <CardHeader
          title="Business (SE tax & QBI)"
          subtitle="Self-employment tax & §199A qualified business income deduction"
          action={
            business.available ? (
              <div className="text-right">
                <div className="text-[16px] font-semibold text-ink tabular">{centsToUSD(business.se_tax_cents)}</div>
                <div className="text-[11px] text-muted">SE tax</div>
              </div>
            ) : null
          }
        />
        {business.available ? (
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Stat
                label="SE tax"
                value={centsToUSD(business.se_tax_cents)}
                icon={<Receipt className="h-4 w-4" />}
                sub={`On ${centsToUSD(business.se_earnings_base_cents)} net earnings`}
              />
              <Stat
                label="½ SE deduction"
                tone="positive"
                value={centsToUSD(business.half_se_deduction_cents)}
                icon={<Calculator className="h-4 w-4" />}
              />
              <Stat
                label="QBI deduction"
                tone="positive"
                value={centsToUSD(business.qbi_deduction_cents)}
                icon={<Briefcase className="h-4 w-4" />}
                sub={
                  business.qbi_per_business.length > 0
                    ? business.qbi_per_business.map((b) => `${centsToUSD(b.component_cents)} (${b.regime})`).join(" · ")
                    : undefined
                }
              />
              <Stat
                label="Schedule-1 income"
                value={centsToUSD(business.schedule_1_income_cents)}
                icon={<LineChart className="h-4 w-4" />}
              />
            </div>
            {business.assumptions ? <p className="text-[12px] text-muted">{business.assumptions}</p> : null}
          </div>
        ) : (
          <NotAvailable reason={business.reason ?? "Add business entities to see SE-tax & QBI planning."} />
        )}
      </Card>

      {/* Multi-year projection */}
      <Card>
        <CardHeader
          title="Multi-year projection"
          subtitle="Projected total tax across the planning horizon"
          action={
            multi_year.available ? (
              <div className="text-right">
                <div className="text-[16px] font-semibold text-ink tabular">{centsToUSD(multi_year.cumulative_tax_cents)}</div>
                <div className="text-[11px] text-muted">cumulative tax</div>
              </div>
            ) : null
          }
        />
        {multi_year.available ? (
          <>
            <div className="divide-y divide-line-2">
              {multi_year.years.map((y) => (
                <div key={y.tax_year} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[14.5px] font-medium text-ink">{y.tax_year}</span>
                        <Badge tone="neutral">{percent(y.marginal_rate)} marginal</Badge>
                      </div>
                      <p className="mt-1 text-[12.5px] text-muted tabular">
                        Taxable income {centsToUSD(y.taxable_income_cents)}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-[15px] font-semibold text-ink tabular">{centsToUSD(y.total_tax_cents)}</div>
                    </div>
                  </div>
                  <div className="mt-2.5">
                    <Meter value={y.total_tax_cents} max={maxYearTax} tone="primary" />
                  </div>
                </div>
              ))}
            </div>
            {multi_year.assumptions ? (
              <p className="border-t border-line-2 px-5 py-3 text-[12px] text-muted">{multi_year.assumptions}</p>
            ) : null}
          </>
        ) : (
          <NotAvailable reason={multi_year.reason} />
        )}
      </Card>

      {/* Opportunities */}
      <Card>
        <CardHeader
          title="Opportunities"
          subtitle="Illustrative planning moves, prioritized"
          action={
            opportunities.available ? (
              <div className="text-right">
                <div className="text-[16px] font-semibold text-positive tabular">
                  {centsToUSD(opportunities.total_illustrative_savings_cents)}
                </div>
                <div className="text-[11px] text-muted">illustrative savings</div>
              </div>
            ) : null
          }
        />
        {opportunities.available ? (
          <>
            <div className="divide-y divide-line-2">
              {opportunities.items.length === 0 ? (
                <div className="px-5 py-10 text-center text-[13.5px] text-muted">No opportunities identified.</div>
              ) : (
                opportunities.items.map((it) => (
                  <div key={it.code} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[14.5px] font-medium text-ink">{it.name}</span>
                          <Badge tone="neutral">{it.category}</Badge>
                        </div>
                        <p className="mt-1 text-[12.5px] text-muted">
                          {it.citation} · {it.eligibility_note}
                        </p>
                        <p className="mt-1 text-[12px] text-muted tabular">
                          {centsToUSD(it.illustrative_amount_cents)} × {percent(it.marginal_rate_used)}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-[15px] font-semibold text-positive tabular">
                          {centsToUSD(it.estimated_tax_savings_cents)}
                        </div>
                        <div className="text-[11px] text-muted">est. savings</div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-line-2 px-5 py-4">
              {propose.error ? <p className="text-[13px] text-negative">{propose.error}</p> : <span />}
              <Button
                icon={<Sparkles className="h-4 w-4" />}
                loading={propose.pending}
                onClick={() => void propose.run()}
              >
                Generate plan proposal
              </Button>
            </div>
          </>
        ) : (
          <NotAvailable reason={opportunities.reason} />
        )}
      </Card>

      {/* Proposal narrative */}
      {proposal ? (
        <Card>
          <CardHeader title="Plan proposal" subtitle="Engine-computed savings, advisor-reviewable narrative" />
          <div className="space-y-4 p-5">
            {proposal.narrative ? (
              <p className="flex items-start gap-2 whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">
                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span>{proposal.narrative}</span>
              </p>
            ) : (
              <p className="text-[13.5px] text-muted">Narrative unavailable.</p>
            )}
            <p className="border-t border-line-2 pt-4 text-[12px] leading-relaxed text-muted">{proposal.disclaimer}</p>
          </div>
        </Card>
      ) : null}

      <Disclaimer />
    </div>
  );
}
