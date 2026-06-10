"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, SlidersHorizontal } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { Card, CardHeader, Badge, Skeleton, PageHeader } from "@/components/ui";

interface Row { lower_bound_cents: number; upper_bound_cents: number | null; rate: string; ordinal: number }
interface BracketSet { id: string; tax_year: number; jurisdiction: string; filing_status: string; standard_deduction_cents: number; rows: Row[] }
const FILING: Record<string, string> = { single: "Single", mfj: "MFJ", mfs: "MFS", hoh: "HoH", qss: "QSS" };

export default function BracketsPage() {
  const [sets, setSets] = useState<BracketSet[] | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [status, setStatus] = useState("single");

  useEffect(() => { api.get("/admin/tax-bracket-sets").then((r) => setSets(r.data)).catch(() => setSets([])); }, []);

  const years = useMemo(() => [...new Set((sets ?? []).map((s) => s.tax_year))].sort(), [sets]);
  const activeYear = year ?? years[0] ?? null;
  const current = useMemo(
    () => (sets ?? []).find((s) => s.tax_year === activeYear && s.filing_status === status) ?? null,
    [sets, activeYear, status],
  );

  return (
    <div className="animate-in">
      <Link href="/admin" className="mb-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted hover:text-ink"><ArrowLeft className="h-4 w-4" /> Admin</Link>
      <PageHeader eyebrow="Admin" title="Tax tables" subtitle="Federal brackets, deductions, and thresholds — table-driven and editable per year. No hard-coded constants." />

      {sets === null ? (
        <Skeleton className="h-72 w-full" />
      ) : (
        <Card>
          <CardHeader
            title="Ordinary income brackets"
            subtitle={current ? `Standard deduction ${centsToUSD(current.standard_deduction_cents)}` : "Select a year / status"}
            action={<Badge tone="primary"><SlidersHorizontal className="h-3 w-3" /> suite seed</Badge>}
          />
          <div className="flex flex-wrap items-center gap-2 border-b border-line-2 px-5 py-3">
            <div className="flex gap-1">
              {years.map((y) => (
                <button key={y} onClick={() => setYear(y)} className={`rounded-[var(--radius-md)] px-3 py-1.5 text-[13px] font-medium ${activeYear === y ? "bg-primary-soft text-primary-strong" : "text-muted hover:bg-surface-2"}`}>{y}</button>
              ))}
            </div>
            <div className="mx-2 h-5 w-px bg-line" />
            <div className="flex gap-1">
              {Object.keys(FILING).map((f) => (
                <button key={f} onClick={() => setStatus(f)} className={`rounded-[var(--radius-md)] px-3 py-1.5 text-[13px] font-medium ${status === f ? "bg-primary-soft text-primary-strong" : "text-muted hover:bg-surface-2"}`}>{FILING[f]}</button>
              ))}
            </div>
          </div>
          {current ? (
            <div className="divide-y divide-line-2">
              <div className="grid grid-cols-[80px_1fr_1fr] gap-4 px-5 py-2.5 text-[11.5px] font-semibold uppercase tracking-wide text-muted">
                <span>Rate</span><span>From</span><span>To</span>
              </div>
              {[...current.rows].sort((a, b) => a.lower_bound_cents - b.lower_bound_cents).map((r) => (
                <div key={r.ordinal} className="grid grid-cols-[80px_1fr_1fr] items-center gap-4 px-5 py-2.5">
                  <span><Badge tone="primary">{percent(r.rate)}</Badge></span>
                  <span className="text-[13.5px] text-ink-2 tabular">{centsToUSD(r.lower_bound_cents)}</span>
                  <span className="text-[13.5px] text-ink-2 tabular">{r.upper_bound_cents === null ? "and up" : centsToUSD(r.upper_bound_cents)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="px-5 py-10 text-center text-[13.5px] text-muted">No bracket set for this selection.</div>
          )}
        </Card>
      )}
    </div>
  );
}
