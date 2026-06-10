"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";
import api from "@/lib/api";

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
  const [projectedTax, setProjectedTax] = useState("");
  const [priorTax, setPriorTax] = useState("");
  const [priorAgi, setPriorAgi] = useState("");
  const [quarters, setQuarters] = useState<Quarter[]>([]);
  const [basis, setBasis] = useState("");

  async function compute() {
    const response = await api.post(`/quarterly/${planYearId}/compute`, {
      projected_current_year_tax_cents: Number.parseInt(projectedTax || "0", 10),
      prior_year_tax_cents: Number.parseInt(priorTax || "0", 10),
      prior_year_agi_cents: Number.parseInt(priorAgi || "0", 10),
      period_income_cents: [0, 0, 0, 0],
      payments_made_cents: [0, 0, 0, 0],
      method: "even",
    });
    setBasis(response.data.safe_harbor_basis);
    setQuarters(response.data.quarters);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Quarterly Estimated Tax</h1>
        <p className="text-sm text-[var(--muted)]">
          Informational planning estimate only. Not an official Form 2210 penalty computation.
        </p>
      </header>
      <section className="grid gap-4 rounded-lg border border-[var(--line)] bg-white p-4 md:grid-cols-4">
        {[
          ["Plan tax year id", planYearId, setPlanYearId],
          ["Projected tax, cents", projectedTax, setProjectedTax],
          ["Prior tax, cents", priorTax, setPriorTax],
          ["Prior AGI, cents", priorAgi, setPriorAgi],
        ].map(([label, value, setter]) => (
          <label key={label as string} className="text-sm">
            {label as string}
            <input
              value={value as string}
              onChange={(event) => (setter as (next: string) => void)(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
            />
          </label>
        ))}
        <button
          type="button"
          onClick={compute}
          className="flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white md:col-span-4"
        >
          <CalendarClock className="h-4 w-4" aria-hidden />
          Compute Quarterlies
        </button>
      </section>
      {quarters.length > 0 ? (
        <section className="mt-4 rounded-lg border border-[var(--line)] bg-white">
          <div className="border-b border-[var(--line)] p-4 text-sm text-[var(--muted)]">
            Safe harbor basis: {basis}
          </div>
          <div className="grid grid-cols-4 gap-0 text-sm">
            {quarters.map((quarter) => (
              <div key={quarter.quarter} className="border-r border-[var(--line)] p-4 last:border-r-0">
                <p className="font-semibold">Q{quarter.quarter}</p>
                <p className="text-[var(--muted)]">{quarter.due_date}</p>
                <p className="mt-3">
                  Required: ${(quarter.required_payment_cents / 100).toFixed(0)}
                </p>
                <p>Roll-forward: ${(quarter.unpaid_rollforward_cents / 100).toFixed(0)}</p>
                <p className="mt-2 text-[var(--muted)]">{quarter.status}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
