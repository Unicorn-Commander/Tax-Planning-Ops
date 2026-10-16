"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  FileUp, GitCompareArrows, TrendingDown, TrendingUp, Sparkles, ArrowRight, CalendarClock, Lightbulb,
} from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { formatDateOnly } from "@/lib/time";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, Skeleton, EmptyState, Disclaimer } from "@/components/ui";

const STATUS_TONE: Record<string, "positive" | "primary" | "warning" | "neutral"> = {
  use_next_year: "positive", explore: "primary", declined: "neutral",
};

function MetricRow({ label, current, next }: { label: string; current: string; next?: string }) {
  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-5 py-2.5">
      <span className="text-[13px] text-muted">{label}</span>
      <span className="w-28 text-right text-[13.5px] font-medium text-ink-2 tabular">{current}</span>
      {next !== undefined ? <span className="w-28 text-right text-[13.5px] font-semibold text-ink tabular">{next}</span> : <span className="w-28" />}
    </div>
  );
}

export default function ClientOverviewPage() {
  const { clientId, overview, loading, reload } = useClientOverview();

  const base = overview?.years.find((y) => y.role === "base") ?? null;
  const plan = overview?.years.find((y) => y.role === "plan") ?? null;
  const totalSavings = useMemo(
    () => (overview?.strategies ?? []).reduce((s, x) => s + x.estimated_savings_cents, 0),
    [overview],
  );

  const createPlan = useAction(async () => {
    if (!base) return;
    await api.post("/plans", { base_tax_year_id: base.id, target_tax_year: base.tax_year + 1 });
    reload();
  });

  if (loading) {
    return <div className="space-y-4"><Skeleton className="h-64 w-full" /><Skeleton className="h-40 w-full" /></div>;
  }

  // No confirmed baseline yet
  if (!base) {
    return (
      <EmptyState
        icon={<FileUp className="h-5 w-5" />}
        title="No confirmed return yet"
        body="Upload this client's filed 1040 and confirm the baseline to unlock projections, strategies, and quarterly estimates."
        action={<Link href={`/clients/${clientId}/returns`}><Button icon={<FileUp className="h-4 w-4" />}>Import 1040</Button></Link>}
      />
    );
  }

  const bs = base.snapshot;
  const ps = plan?.snapshot;
  const deltaTax = bs && ps ? ps.total_tax_cents - bs.total_tax_cents : 0;

  return (
    <div className="space-y-6">
      {/* Hero: Current vs Next-Year */}
      <Card>
        <CardHeader
          title="Current vs next-year projection"
          subtitle={plan ? `${base.tax_year} filed baseline compared to your ${plan.tax_year} plan` : `${base.tax_year} filed baseline`}
          action={
            !plan ? (
              <Button icon={<GitCompareArrows className="h-4 w-4" />} loading={createPlan.pending} onClick={() => void createPlan.run()}>
                Build {base.tax_year + 1} plan
              </Button>
            ) : (
              <Link href={`/clients/${clientId}/strategies`}>
                <Button variant="secondary" icon={<Lightbulb className="h-4 w-4" />}>Plan strategies</Button>
              </Link>
            )
          }
        />

        {/* Big totals */}
        <div className="grid grid-cols-1 gap-px bg-line-2 md:grid-cols-[1fr_auto_1fr]">
          <div className="bg-surface p-6">
            <div className="text-[12px] font-semibold uppercase tracking-wide text-muted">{base.tax_year} · Filed</div>
            <div className="mt-2 text-[34px] font-semibold leading-none tracking-tight text-ink tabular">{centsToUSD(bs?.total_tax_cents)}</div>
            <div className="mt-1.5 text-[13px] text-muted">total tax · {percent(bs?.effective_rate ?? 0)} effective</div>
          </div>

          <div className="flex items-center justify-center bg-surface px-6">
            {plan && bs && ps ? (
              <div className={`flex flex-col items-center rounded-[var(--radius-lg)] px-4 py-3 ${deltaTax <= 0 ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative"}`}>
                {deltaTax <= 0 ? <TrendingDown className="h-5 w-5" /> : <TrendingUp className="h-5 w-5" />}
                <span className="mt-1 text-[17px] font-semibold tabular">{deltaTax <= 0 ? "−" : "+"}{centsToUSD(Math.abs(deltaTax))}</span>
                <span className="text-[11px] font-medium uppercase tracking-wide opacity-80">YoY</span>
              </div>
            ) : (
              <ArrowRight className="h-5 w-5 text-line" />
            )}
          </div>

          <div className="bg-surface p-6">
            <div className="text-[12px] font-semibold uppercase tracking-wide text-primary">{plan ? `${plan.tax_year} · Projected` : "Next year"}</div>
            {plan && ps ? (
              <>
                <div className="mt-2 text-[34px] font-semibold leading-none tracking-tight text-ink tabular">{centsToUSD(ps.total_tax_cents)}</div>
                <div className="mt-1.5 text-[13px] text-muted">projected tax · {percent(ps.effective_rate)} effective</div>
              </>
            ) : (
              <div className="mt-2 text-[14px] text-muted">Build a plan to project next year, compute quarterlies, and model strategies.</div>
            )}
          </div>
        </div>

        {/* Metric breakdown */}
        {plan && bs && ps ? (
          <div className="border-t border-line-2">
            <div className="grid grid-cols-[1fr_auto_auto] gap-4 px-5 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted">
              <span />
              <span className="w-28 text-right">{base.tax_year}</span>
              <span className="w-28 text-right text-primary">{plan.tax_year}</span>
            </div>
            <MetricRow label="Total income" current={centsToUSD(bs.total_income_cents)} next={centsToUSD(ps.total_income_cents)} />
            <MetricRow label="Adjusted gross income" current={centsToUSD(bs.agi_cents)} next={centsToUSD(ps.agi_cents)} />
            <MetricRow label="Taxable income" current={centsToUSD(bs.taxable_income_cents)} next={centsToUSD(ps.taxable_income_cents)} />
            <MetricRow label="Marginal bracket" current={percent(bs.marginal_rate)} next={percent(ps.marginal_rate)} />
            <MetricRow label="Effective rate" current={percent(bs.effective_rate)} next={percent(ps.effective_rate)} />
          </div>
        ) : null}
      </Card>

      {plan ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Strategies */}
          <Card>
            <CardHeader
              title="Recommended strategies"
              subtitle={`${overview?.strategies.length ?? 0} selected`}
              action={
                totalSavings > 0 ? (
                  <div className="text-right">
                    <div className="text-[15px] font-semibold text-positive tabular">{centsToUSD(totalSavings)}</div>
                    <div className="text-[11px] text-muted">projected savings</div>
                  </div>
                ) : null
              }
            />
            <div className="divide-y divide-line-2">
              {(overview?.strategies ?? []).length === 0 ? (
                <div className="px-5 py-8 text-center">
                  <Link href={`/clients/${clientId}/strategies`} className="text-[13.5px] font-medium text-primary hover:underline">+ Add a strategy</Link>
                </div>
              ) : (
                overview!.strategies.map((s) => (
                  <div key={s.id} className="px-5 py-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-[14px] font-medium text-ink">{s.name}</div>
                        <div className="mt-0.5 text-[12.5px] text-muted">{centsToUSD(s.amount_cents)} × {percent(s.effective_rate_used)}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[14px] font-semibold text-positive tabular">{centsToUSD(s.estimated_savings_cents)}</div>
                        <Badge tone={STATUS_TONE[s.status_flag] ?? "neutral"} className="mt-1">{s.status_flag.replace(/_/g, " ")}</Badge>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>

          {/* Quarterly */}
          <Card>
            <CardHeader
              title="Quarterly estimates"
              subtitle={overview?.quarterly[0]?.safe_harbor_basis ? `Safe harbor: ${overview.quarterly[0].safe_harbor_basis.replace(/_/g, " ")}` : "Not computed"}
              action={<Link href={`/clients/${clientId}/quarterly`} className="text-[13px] font-medium text-primary hover:underline">Manage</Link>}
            />
            {(overview?.quarterly ?? []).length === 0 ? (
              <div className="px-5 py-8 text-center text-[13.5px] text-muted">Not yet computed.</div>
            ) : (
              <div className="grid grid-cols-2 gap-px bg-line-2">
                {overview!.quarterly.map((q) => (
                  <div key={q.quarter} className="bg-surface p-4">
                    <div className="flex items-center gap-2 text-[12px] text-muted">
                      <CalendarClock className="h-3.5 w-3.5" /> Q{q.quarter} · {formatDateOnly(q.due_date)}
                    </div>
                    <div className="mt-1.5 text-[18px] font-semibold text-ink tabular">{centsToUSD(q.required_payment_cents)}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      ) : null}

      {plan ? (
        <Card className="overflow-hidden">
          <Link href={`/clients/${clientId}/pdf`} className="flex items-center justify-between gap-4 p-5 transition-colors hover:bg-surface-2">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] bg-primary-soft text-primary"><Sparkles className="h-5 w-5" /></span>
              <div>
                <div className="text-[14.5px] font-semibold text-ink">Generate the client tax-plan PDF</div>
                <div className="text-[13px] text-muted">Branded, with strategies, quarterlies, and the planning disclaimer.</div>
              </div>
            </div>
            <ArrowRight className="h-5 w-5 text-muted" />
          </Link>
        </Card>
      ) : null}

      <Disclaimer />
    </div>
  );
}
