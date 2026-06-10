"use client";

import { useState } from "react";
import { GitCompareArrows } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { MoneyInput } from "@/components/money-input";

interface Projection {
  snapshot_id?: string;
  total_tax_cents?: number;
  marginal_rate?: string | number;
  effective_rate?: string | number;
}

export default function PlanPage() {
  const [baseTaxYearId, setBaseTaxYearId] = useState("");
  const [targetYear, setTargetYear] = useState("2026");
  const [planYearId, setPlanYearId] = useState("");
  const [wageDeltaCents, setWageDeltaCents] = useState<number | null>(null);
  const [result, setResult] = useState<Projection | null>(null);

  const createPlan = useAction(async () => {
    const response = await api.post("/plans", {
      base_tax_year_id: baseTaxYearId,
      target_tax_year: Number.parseInt(targetYear, 10),
    });
    setPlanYearId(response.data.client_tax_year_id);
    setResult(response.data);
  });

  const recompute = useAction(async () => {
    const response = await api.patch(`/plans/${planYearId}/assumptions`, {
      assumptions: { wages_cents_delta_cents: wageDeltaCents ?? 0 },
    });
    setResult(response.data);
  });

  return (
    <main className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Current vs Next-Year Projection</h1>
        <p className="text-sm text-[var(--muted)]">
          Planning estimate only. Not a filed tax return and not tax advice.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-[var(--line)] bg-white p-4">
          <h2 className="font-medium">Create Plan</h2>
          <label className="mt-4 block text-sm">Confirmed base tax year id</label>
          <input
            value={baseTaxYearId}
            onChange={(event) => setBaseTaxYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-sm"
          />
          <label className="mt-4 block text-sm">Target year</label>
          <input
            value={targetYear}
            onChange={(event) => setTargetYear(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
          />
          <button
            type="button"
            onClick={() => void createPlan.run()}
            disabled={!baseTaxYearId || createPlan.pending}
            className="mt-4 flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white disabled:opacity-50"
          >
            <GitCompareArrows className="h-4 w-4" aria-hidden />
            {createPlan.pending ? "Building…" : "Build Projection"}
          </button>
          {createPlan.error ? <p className="mt-3 text-sm text-red-600">{createPlan.error}</p> : null}
        </div>

        <div className="rounded-lg border border-[var(--line)] bg-white p-4">
          <h2 className="font-medium">Next-Year Assumptions</h2>
          <label className="mt-4 block text-sm">Plan tax year id</label>
          <input
            value={planYearId}
            onChange={(event) => setPlanYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-sm"
          />
          <label className="mt-4 block text-sm">Wage change vs base</label>
          <div className="mt-2">
            <MoneyInput valueCents={wageDeltaCents} onChangeCents={setWageDeltaCents} />
          </div>
          <button
            type="button"
            onClick={() => void recompute.run()}
            disabled={!planYearId || recompute.pending}
            className="mt-4 h-10 rounded-md border border-[var(--line)] px-3 text-sm disabled:opacity-50"
          >
            {recompute.pending ? "Recomputing…" : "Recompute"}
          </button>
          {recompute.error ? <p className="mt-3 text-sm text-red-600">{recompute.error}</p> : null}
        </div>
      </section>

      {result ? (
        <section className="mt-4 grid grid-cols-2 gap-4 rounded-lg border border-[var(--line)] bg-white p-4 md:grid-cols-3">
          <div>
            <p className="text-sm text-[var(--muted)]">Projected total tax</p>
            <p className="text-2xl font-semibold">{centsToUSD(result.total_tax_cents)}</p>
          </div>
          <div>
            <p className="text-sm text-[var(--muted)]">Marginal rate</p>
            <p className="text-2xl font-semibold">{percent(result.marginal_rate)}</p>
          </div>
          <div>
            <p className="text-sm text-[var(--muted)]">Effective rate</p>
            <p className="text-2xl font-semibold">{percent(result.effective_rate)}</p>
          </div>
        </section>
      ) : null}
    </main>
  );
}
