"use client";

import { useState } from "react";
import Link from "next/link";
import { CalendarClock, Calculator, ShieldCheck } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { formatDateOnly } from "@/lib/time";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, Field, MoneyInput, EmptyState, Disclaimer } from "@/components/ui";

const STATUS_TONE: Record<string, "positive" | "warning" | "negative" | "neutral"> = {
  paid: "positive", projected: "neutral", partial: "warning", missed: "negative",
};
const BASIS_LABEL: Record<string, string> = {
  "90_current": "90% of current-year tax", "100_prior": "100% of prior-year tax", "110_prior_high_agi": "110% of prior-year (high AGI)",
};

export default function QuarterlyTab() {
  const { overview, loading, reload } = useClientOverview();
  const [projected, setProjected] = useState<number | null>(null);
  const [prior, setPrior] = useState<number | null>(null);
  const [priorAgi, setPriorAgi] = useState<number | null>(null);
  const [withholding, setWithholding] = useState<number | null>(null);

  const planId = overview?.plan_year_id ?? null;
  const quarters = overview?.quarterly ?? [];
  const basis = quarters[0]?.safe_harbor_basis;
  const totalRequired = quarters.reduce((s, q) => s + q.required_payment_cents, 0);

  const compute = useAction(async () => {
    if (!planId) return;
    await api.post(`/quarterly/${planId}/compute`, {
      projected_current_year_tax_cents: projected ?? 0,
      prior_year_tax_cents: prior ?? 0,
      prior_year_agi_cents: priorAgi ?? 0,
      annual_withholding_cents: withholding ?? 0,
      period_income_cents: [0, 0, 0, 0], payments_made_cents: [0, 0, 0, 0], method: "even",
    });
    reload();
  });

  if (loading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;
  if (!planId) {
    return <EmptyState icon={<Calculator className="h-5 w-5" />} title="No plan year yet"
      body="Create a plan on the Overview tab to compute quarterly estimates."
      action={<Link href={`/clients/${overview?.client.id}`}><Button>Go to overview</Button></Link>} />;
  }

  return (
    <div className="space-y-6">
      {quarters.length > 0 ? (
        <Card>
          <CardHeader
            title="Quarterly estimated tax"
            subtitle={basis ? `Safe harbor basis · ${BASIS_LABEL[basis] ?? basis}` : undefined}
            action={<div className="text-right"><div className="text-[16px] font-semibold text-ink tabular">{centsToUSD(totalRequired)}</div><div className="text-[11px] text-muted">total required</div></div>}
          />
          <div className="grid grid-cols-1 gap-px bg-line-2 sm:grid-cols-2 lg:grid-cols-4">
            {quarters.map((q) => (
              <div key={q.quarter} className="bg-surface p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-soft text-[12px] font-semibold text-primary-strong">Q{q.quarter}</span>
                  <Badge tone={STATUS_TONE[q.status] ?? "neutral"}>{q.status}</Badge>
                </div>
                <div className="mt-3 flex items-center gap-1.5 text-[12px] text-muted"><CalendarClock className="h-3.5 w-3.5" /> {formatDateOnly(q.due_date)}</div>
                <div className="mt-1 text-[22px] font-semibold text-ink tabular">{centsToUSD(q.required_payment_cents)}</div>
                {q.unpaid_rollforward_cents > 0 ? <div className="mt-1 text-[12px] text-warning">+{centsToUSD(q.unpaid_rollforward_cents)} rolled forward</div> : null}
              </div>
            ))}
          </div>
          <p className="flex items-center gap-1.5 border-t border-line-2 px-5 py-3 text-[12px] text-muted">
            <ShieldCheck className="h-3.5 w-3.5 text-positive" /> Informational planning estimate — not an official Form 2210 penalty computation.
          </p>
        </Card>
      ) : (
        <EmptyState icon={<Calculator className="h-5 w-5" />} title="Not computed yet" body="Enter the figures below to compute the safe-harbor schedule." />
      )}

      <Card className="self-start">
        <CardHeader title="Compute schedule" subtitle="Safe harbor is the minimum of the bases the client qualifies for" />
        <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2">
          <Field label="Projected current-year tax"><MoneyInput valueCents={projected} onChangeCents={setProjected} /></Field>
          <Field label="Prior-year tax"><MoneyInput valueCents={prior} onChangeCents={setPrior} /></Field>
          <Field label="Prior-year AGI"><MoneyInput valueCents={priorAgi} onChangeCents={setPriorAgi} /></Field>
          <Field label="Annual withholding"><MoneyInput valueCents={withholding} onChangeCents={setWithholding} /></Field>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-line-2 px-5 py-4">
          {compute.error ? <p className="text-[13px] text-negative">{compute.error}</p> : <span />}
          <Button icon={<Calculator className="h-4 w-4" />} loading={compute.pending} onClick={() => void compute.run()}>Compute quarterlies</Button>
        </div>
      </Card>

      <Disclaimer />
    </div>
  );
}
