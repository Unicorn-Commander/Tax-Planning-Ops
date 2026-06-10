"use client";

import { useEffect, useState } from "react";
import { BadgeDollarSign } from "lucide-react";
import api from "@/lib/api";

interface Strategy {
  id: string;
  name: string;
  category: string;
  default_amount_cents: number | null;
}

export default function StrategiesPage() {
  const [planYearId, setPlanYearId] = useState("");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [amount, setAmount] = useState("");
  const [result, setResult] = useState<Record<string, string | number> | null>(null);

  useEffect(() => {
    api.get("/strategy-library").then((response) => setStrategies(response.data));
  }, []);

  async function addStrategy() {
    const response = await api.post(`/plans/${planYearId}/strategies`, {
      strategy_id: selectedStrategyId,
      amount_cents: Number.parseInt(amount || "0", 10),
      disposition: "recommended",
      status_flag: "explore",
    });
    setResult(response.data);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Tax Strategies</h1>
        <p className="text-sm text-[var(--muted)]">
          Manual overrides and selected rates are snapshotted for plan provenance.
        </p>
      </header>
      <section className="rounded-lg border border-[var(--line)] bg-white p-4">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="text-sm">
            Plan tax year id
            <input
              value={planYearId}
              onChange={(event) => setPlanYearId(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-xs"
            />
          </label>
          <label className="text-sm">
            Strategy
            <select
              value={selectedStrategyId}
              onChange={(event) => setSelectedStrategyId(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
            >
              <option value="">Select</option>
              {strategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  {strategy.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Amount, cents
            <input
              type="number"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
            />
          </label>
        </div>
        <button
          type="button"
          onClick={addStrategy}
          className="mt-4 flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
        >
          <BadgeDollarSign className="h-4 w-4" aria-hidden />
          Add Recommended Strategy
        </button>
      </section>
      {result ? (
        <section className="mt-4 rounded-lg border border-[var(--line)] bg-white p-4">
          <p className="text-sm text-[var(--muted)]">Estimated savings</p>
          <p className="text-2xl font-semibold">
            ${((Number(result.estimated_savings_cents) || 0) / 100).toFixed(0)}
          </p>
          <pre className="mt-3 overflow-auto rounded-md bg-[#f2f4ef] p-3 text-xs">
            {JSON.stringify(result, null, 2)}
          </pre>
        </section>
      ) : null}
    </main>
  );
}
