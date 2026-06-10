"use client";

import { useEffect, useState } from "react";
import { BadgeDollarSign } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { MoneyInput } from "@/components/money-input";

interface Strategy {
  id: string;
  name: string;
  category: string;
  default_amount_cents: number | null;
}

interface StrategyResult {
  estimated_savings_cents?: number;
  effective_rate_used?: string;
  [key: string]: string | number | undefined;
}

export default function StrategiesPage() {
  const [planYearId, setPlanYearId] = useState("");
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [amountCents, setAmountCents] = useState<number | null>(null);
  const [result, setResult] = useState<StrategyResult | null>(null);

  const load = useAction(async () => {
    const response = await api.get("/strategy-library");
    setStrategies(response.data);
  });
  const add = useAction(async () => {
    const response = await api.post(`/plans/${planYearId}/strategies`, {
      strategy_id: selectedStrategyId,
      amount_cents: amountCents ?? 0,
      disposition: "recommended",
      status_flag: "explore",
    });
    setResult(response.data);
  });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void load.run(), []);

  const canAdd = Boolean(planYearId && selectedStrategyId && amountCents !== null);

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
            {load.pending && strategies.length === 0 ? (
              <p className="mt-2 text-xs text-[var(--muted)]">Loading library…</p>
            ) : (
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
            )}
          </label>
          <label className="text-sm">
            Amount
            <div className="mt-2">
              <MoneyInput valueCents={amountCents} onChangeCents={setAmountCents} />
            </div>
          </label>
        </div>
        <button
          type="button"
          onClick={() => void add.run()}
          disabled={!canAdd || add.pending}
          className="mt-4 flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white disabled:opacity-50"
        >
          <BadgeDollarSign className="h-4 w-4" aria-hidden />
          {add.pending ? "Adding…" : "Add Recommended Strategy"}
        </button>
        {add.error ? <p className="mt-3 text-sm text-red-600">{add.error}</p> : null}
      </section>
      {result ? (
        <section className="mt-4 rounded-lg border border-[var(--line)] bg-white p-4">
          <p className="text-sm text-[var(--muted)]">Estimated savings</p>
          <p className="text-2xl font-semibold">{centsToUSD(Number(result.estimated_savings_cents) || 0)}</p>
          {result.effective_rate_used ? (
            <p className="mt-1 text-xs text-[var(--muted)]">
              rate used: {(Number(result.effective_rate_used) * 100).toFixed(2)}%
            </p>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
