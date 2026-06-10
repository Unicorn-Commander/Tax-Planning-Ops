"use client";

import { useState } from "react";
import { GitCompareArrows } from "lucide-react";
import api from "@/lib/api";

const disclaimer =
  "Planning estimate only. Not a filed tax return and not tax advice. Figures are projections based on advisor-entered assumptions and editable bracket tables.";

export default function PlanPage() {
  const [baseTaxYearId, setBaseTaxYearId] = useState("");
  const [targetYear, setTargetYear] = useState("2026");
  const [planYearId, setPlanYearId] = useState("");
  const [wageDelta, setWageDelta] = useState("");
  const [result, setResult] = useState<Record<string, string | number> | null>(null);

  async function createPlan() {
    const response = await api.post("/plans", {
      base_tax_year_id: baseTaxYearId,
      target_tax_year: Number.parseInt(targetYear, 10),
    });
    setPlanYearId(response.data.client_tax_year_id);
    setResult(response.data);
  }

  async function updateAssumptions() {
    if (!planYearId) return;
    const response = await api.patch(`/plans/${planYearId}/assumptions`, {
      assumptions: {
        wages_cents_delta_cents: Number.parseInt(wageDelta || "0", 10),
      },
    });
    setResult(response.data);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Current vs Next-Year Projection</h1>
        <p className="text-sm text-[var(--muted)]">{disclaimer}</p>
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
            onClick={createPlan}
            className="mt-4 flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
          >
            <GitCompareArrows className="h-4 w-4" aria-hidden />
            Build Projection
          </button>
        </div>

        <div className="rounded-lg border border-[var(--line)] bg-white p-4">
          <h2 className="font-medium">Next-Year Assumptions</h2>
          <label className="mt-4 block text-sm">Plan tax year id</label>
          <input
            value={planYearId}
            onChange={(event) => setPlanYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-sm"
          />
          <label className="mt-4 block text-sm">Wage delta, cents</label>
          <input
            type="number"
            value={wageDelta}
            onChange={(event) => setWageDelta(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
          />
          <button
            type="button"
            onClick={updateAssumptions}
            className="mt-4 h-10 rounded-md border border-[var(--line)] px-3 text-sm"
          >
            Recompute
          </button>
        </div>
      </section>

      {result ? (
        <section className="mt-4 rounded-lg border border-[var(--line)] bg-white p-4">
          <h2 className="font-medium">Projection Result</h2>
          <pre className="mt-3 overflow-auto rounded-md bg-[#f2f4ef] p-3 text-xs">
            {JSON.stringify(result, null, 2)}
          </pre>
        </section>
      ) : null}
    </main>
  );
}
