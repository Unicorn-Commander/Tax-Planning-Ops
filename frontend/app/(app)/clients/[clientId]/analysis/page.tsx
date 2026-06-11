"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Calculator, HeartPulse, LineChart, Lightbulb, Sparkles } from "lucide-react";
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

interface Analysis {
  client_name: string;
  tax_year: number;
  filing_status: string;
  amt: AmtSection | Unavailable;
  irmaa: IrmaaSection | Unavailable;
  multi_year: MultiYearSection | Unavailable;
  opportunities: OpportunitiesSection | Unavailable;
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

  const { amt, irmaa, multi_year, opportunities } = analysis;
  const maxYearTax =
    multi_year.available && multi_year.years.length > 0
      ? Math.max(...multi_year.years.map((y) => y.total_tax_cents), 1)
      : 1;

  return (
    <div className="space-y-6">
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
