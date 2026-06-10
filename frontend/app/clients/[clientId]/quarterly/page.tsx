"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { MoneyInput } from "@/components/money-input";

interface Quarter {
  quarter: number;
  due_date: string;
  required_payment_cents: number;
  payment_made_cents: number;
  unpaid_rollforward_cents: number;
  status: string;
}

export default function QuarterlyPage() {
  const [planYearId, setPlanYearId] = useState("");
  const [projectedTax, setProjectedTax] = useState<number | null>(null);
  const [priorTax, setPriorTax] = useState<number | null>(null);
  const [priorAgi, setPriorAgi] = useState<number | null>(null);
  const [quarters, setQuarters] = useState<Quarter[]>([]);
  const [basis, setBasis] = useState("");

  const compute = useAction(async () => {
    const response = await api.post(`/quarterly/${planYearId}/compute`, {
      projected_current_year_tax_cents: projectedTax ?? 0,
      prior_year_tax_cents: priorTax ?? 0,
      prior_year_agi_cents: priorAgi ?? 0,
      period_income_cents: [0, 0, 0, 0],
      payments_made_cents: [0, 0, 0, 0],
      method: "even",
    });
    setBasis(response.data.safe_harbor_basis);
    setQuarters(response.data.quarters);
  });

  const moneyFields: [string, number | null, (n: number | null) => void][] = [
    ["Projected current-year tax", projectedTax, setProjectedTax],
    ["Prior-year tax", priorTax, setPriorTax],
    ["Prior-year AGI", priorAgi, setPriorAgi],
  ];

  return (
    <main className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Quarterly Estimated Tax</h1>
        <p className="text-sm text-[var(--muted)]">
          Informational planning estimate only. Not an official Form 2210 penalty computation.
        </p>
      </header>
      <section className="grid gap-4 rounded-lg border border-[var(--line)] bg-white p-4 md:grid-cols-4">
        <label className="text-sm">
          Plan tax year id
          <input
            value={planYearId}
            onChange={(event) => setPlanYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-xs"
          />
        </label>
        {moneyFields.map(([label, value, setter]) => (
          <label key={label} className="text-sm">
            {label}
            <div className="mt-2">
              <MoneyInput valueCents={value} onChangeCents={setter} />
            </div>
          </label>
        ))}
        <button
          type="button"
          onClick={() => void compute.run()}
          disabled={!planYearId || compute.pending}
          className="flex h-10 items-center justify-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white disabled:opacity-50 md:col-span-4"
        >
          <CalendarClock className="h-4 w-4" aria-hidden />
          {compute.pending ? "Computing…" : "Compute Quarterlies"}
        </button>
        {compute.error ? (
          <p className="text-sm text-red-600 md:col-span-4">{compute.error}</p>
        ) : null}
      </section>
      {quarters.length > 0 ? (
        <section className="mt-4 rounded-lg border border-[var(--line)] bg-white">
          <div className="border-b border-[var(--line)] p-4 text-sm text-[var(--muted)]">
            Safe harbor basis: <span className="font-medium text-[var(--ink)]">{basis}</span>
          </div>
          <div className="grid grid-cols-2 gap-0 text-sm md:grid-cols-4">
            {quarters.map((quarter) => (
              <div key={quarter.quarter} className="border-b border-r border-[var(--line)] p-4">
                <p className="font-semibold">Q{quarter.quarter}</p>
                <p className="text-[var(--muted)]">{quarter.due_date}</p>
                <p className="mt-3">Required: {centsToUSD(quarter.required_payment_cents)}</p>
                <p>Roll-forward: {centsToUSD(quarter.unpaid_rollforward_cents)}</p>
                <p className="mt-2 text-[var(--muted)]">{quarter.status}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
