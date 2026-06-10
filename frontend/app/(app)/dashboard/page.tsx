"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Users, Wallet, Percent, Library, ArrowUpRight, CalendarClock, Plus, TrendingDown,
} from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { Card, CardHeader, Stat, Meter, Skeleton, PageHeader, Button, Disclaimer } from "@/components/ui";

interface Client { id: string; display_name: string; filing_status_default: string; primary_state: string | null; status: string }
interface ScanRow { client_id: string; client_name: string; tax_year: number; total_tax_cents: number; effective_rate: string }

const Q_DATES = ["Apr 15, 2026", "Jun 15, 2026", "Sep 15, 2026", "Jan 15, 2027"];

export default function DashboardPage() {
  const [clients, setClients] = useState<Client[] | null>(null);
  const [scan, setScan] = useState<ScanRow[] | null>(null);
  const [strategies, setStrategies] = useState<number | null>(null);

  useEffect(() => {
    api.get("/clients").then((r) => setClients(r.data)).catch(() => setClients([]));
    api.get("/agents/scan-book").then((r) => setScan(r.data)).catch(() => setScan([]));
    api.get("/strategy-library").then((r) => setStrategies(r.data.length)).catch(() => setStrategies(0));
  }, []);

  const base = useMemo(() => (scan ?? []).filter((r) => r.tax_year === 2025), [scan]);
  const plans = useMemo(() => new Set((scan ?? []).filter((r) => r.tax_year === 2026).map((r) => r.client_id)), [scan]);
  const totalTax = base.reduce((s, r) => s + r.total_tax_cents, 0);
  const avgEff = base.length ? base.reduce((s, r) => s + Number(r.effective_rate), 0) / base.length : 0;
  const opportunities = useMemo(() => [...base].sort((a, b) => b.total_tax_cents - a.total_tax_cents).slice(0, 6), [base]);
  const loading = clients === null || scan === null;

  return (
    <div className="animate-in">
      <PageHeader
        eyebrow="Northstar Tax Advisory"
        title="Planning dashboard"
        subtitle="Your book at a glance — opportunities, projections, and upcoming deadlines."
        actions={
          <Link href="/clients"><Button icon={<Plus className="h-4 w-4" />}>New client</Button></Link>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {loading ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[116px]" />)
        ) : (
          <>
            <Stat label="Clients" value={clients!.length} icon={<Users className="h-4 w-4" />} sub={`${plans.size} active plan${plans.size === 1 ? "" : "s"}`} />
            <Stat label="Tax under mgmt" value={centsToUSD(totalTax)} icon={<Wallet className="h-4 w-4" />} sub={`${base.length} confirmed return${base.length === 1 ? "" : "s"}`} />
            <Stat label="Avg effective rate" value={percent(avgEff)} icon={<Percent className="h-4 w-4" />} tone="warning" sub="across confirmed baselines" />
            <Stat label="Strategy library" value={strategies ?? "—"} icon={<Library className="h-4 w-4" />} tone="primary" sub="curated, firm-editable" />
          </>
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.7fr_1fr]">
        {/* Opportunities */}
        <Card>
          <CardHeader
            title="Planning opportunities"
            subtitle="Clients ranked by current-year tax — your highest-leverage conversations."
            action={<Link href="/clients" className="text-[13px] font-medium text-primary hover:underline">View all</Link>}
          />
          <div className="divide-y divide-line-2">
            {loading ? (
              [0, 1, 2, 3].map((i) => <div key={i} className="px-5 py-4"><Skeleton className="h-10 w-full" /></div>)
            ) : opportunities.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13.5px] text-muted">No confirmed returns yet.</div>
            ) : (
              opportunities.map((r) => (
                <Link
                  key={r.client_id}
                  href={`/clients/${r.client_id}`}
                  className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-surface-2"
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-soft text-[12.5px] font-semibold text-primary-strong">
                    {r.client_name.split(" ").map((s) => s[0]).slice(0, 2).join("")}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium text-ink">{r.client_name}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <Meter value={Number(r.effective_rate)} tone="warning" />
                      <span className="shrink-0 text-[11.5px] text-muted tabular">{percent(r.effective_rate)} eff</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[14px] font-semibold text-ink tabular">{centsToUSD(r.total_tax_cents)}</div>
                    <div className="text-[11px] text-muted">2025 tax</div>
                  </div>
                  <ArrowUpRight className="h-4 w-4 text-muted" aria-hidden />
                </Link>
              ))
            )}
          </div>
        </Card>

        {/* Right column */}
        <div className="space-y-6">
          <Card>
            <CardHeader title="2026 quarterly estimates" subtitle="Federal due dates" />
            <div className="space-y-1 p-3">
              {Q_DATES.map((d, i) => (
                <div key={d} className="flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2 hover:bg-surface-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-ink-2">Q{i + 1}</span>
                  <CalendarClock className="h-4 w-4 text-muted" aria-hidden />
                  <span className="text-[13.5px] text-ink">{d}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="bg-gradient-to-br from-primary to-accent p-5 text-white">
              <TrendingDown className="h-6 w-6" aria-hidden />
              <div className="mt-3 text-[15px] font-semibold">Plan on the firm&apos;s ledger</div>
              <p className="mt-1 text-[13px] leading-relaxed text-white/85">
                Every projection is auditable and sovereign — client returns never leave your tenant.
              </p>
            </div>
          </Card>
        </div>
      </div>

      <Disclaimer className="mt-8" />
    </div>
  );
}
