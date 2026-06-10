"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Lightbulb, Plus, GitCompareArrows } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, Field, MoneyInput, EmptyState, Disclaimer } from "@/components/ui";

interface LibStrategy { id: string; name: string; category: string; client_facing_copy: string }
const STATUS_TONE: Record<string, "positive" | "primary" | "neutral"> = { use_next_year: "positive", explore: "primary", declined: "neutral" };

export default function StrategiesTab() {
  const { overview, loading, reload } = useClientOverview();
  const [library, setLibrary] = useState<LibStrategy[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [amountCents, setAmountCents] = useState<number | null>(null);
  const [statusFlag, setStatusFlag] = useState("use_next_year");

  useEffect(() => { api.get("/strategy-library").then((r) => setLibrary(r.data)).catch(() => setLibrary([])); }, []);

  const planId = overview?.plan_year_id ?? null;
  const strategies = overview?.strategies ?? [];
  const total = strategies.reduce((s, x) => s + x.estimated_savings_cents, 0);

  const add = useAction(async () => {
    if (!planId) return;
    await api.post(`/plans/${planId}/strategies`, {
      strategy_id: strategyId, amount_cents: amountCents ?? 0,
      disposition: "recommended", status_flag: statusFlag,
    });
    setStrategyId(""); setAmountCents(null);
    reload();
  });

  if (loading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;

  if (!planId) {
    return (
      <EmptyState
        icon={<GitCompareArrows className="h-5 w-5" />}
        title="No plan year yet"
        body="Create a plan from the confirmed baseline on the Overview tab to model strategies."
        action={<Link href={`/clients/${overview?.client.id}`}><Button>Go to overview</Button></Link>}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
      <Card>
        <CardHeader
          title="Selected strategies"
          subtitle={`${strategies.length} recommended`}
          action={total > 0 ? <div className="text-right"><div className="text-[16px] font-semibold text-positive tabular">{centsToUSD(total)}</div><div className="text-[11px] text-muted">projected savings</div></div> : null}
        />
        <div className="divide-y divide-line-2">
          {strategies.length === 0 ? (
            <div className="px-5 py-10 text-center text-[13.5px] text-muted">No strategies selected yet — add one →</div>
          ) : strategies.map((s) => (
            <div key={s.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[14.5px] font-medium text-ink">{s.name}</span>
                    <Badge tone="neutral">{s.category}</Badge>
                  </div>
                  <p className="mt-1 text-[13px] text-muted">{s.client_facing_copy}</p>
                  <p className="mt-1.5 text-[12.5px] text-muted tabular">{centsToUSD(s.amount_cents)} × {percent(s.effective_rate_used)} effective</p>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[15px] font-semibold text-positive tabular">{centsToUSD(s.estimated_savings_cents)}</div>
                  <Badge tone={STATUS_TONE[s.status_flag] ?? "neutral"} className="mt-1.5">{s.status_flag.replace(/_/g, " ")}</Badge>
                </div>
              </div>
            </div>
          ))}
        </div>
        <Disclaimer className="border-t border-line-2 px-5 py-4" />
      </Card>

      <Card className="self-start">
        <CardHeader title="Add a strategy" subtitle="From your firm's curated library" />
        <div className="space-y-4 p-5">
          <Field label="Strategy">
            <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}
              className="h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-primary">
              <option value="">Select a strategy…</option>
              {library.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </Field>
          <Field label="Contribution / amount"><MoneyInput valueCents={amountCents} onChangeCents={setAmountCents} /></Field>
          <Field label="Status">
            <select value={statusFlag} onChange={(e) => setStatusFlag(e.target.value)}
              className="h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-primary">
              <option value="use_next_year">Use next year</option>
              <option value="explore">Explore</option>
              <option value="declined">Declined</option>
            </select>
          </Field>
          <Button className="w-full" icon={<Plus className="h-4 w-4" />} loading={add.pending}
            disabled={!strategyId || amountCents === null} onClick={() => void add.run()}>Add strategy</Button>
          {add.error ? <p className="text-[13px] text-negative">{add.error}</p> : null}
          <p className="flex items-center gap-1.5 text-[12px] text-muted"><Lightbulb className="h-3.5 w-3.5" /> Savings = amount × the plan&apos;s effective rate, snapshotted for provenance.</p>
        </div>
      </Card>
    </div>
  );
}
