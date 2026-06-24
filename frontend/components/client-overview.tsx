"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/store";

export interface Snapshot {
  total_income_cents: number;
  agi_cents: number;
  taxable_income_cents: number;
  total_tax_cents: number;
  marginal_rate: string;
  effective_rate: string;
  has_manual_override: boolean;
  assumptions: Record<string, unknown>;
}
export interface YearRow {
  id: string;
  tax_year: number;
  role: string;
  filing_status: string;
  is_locked: boolean;
  finalized_at: string | null;
  snapshot: Snapshot | null;
}
export interface StrategyRow {
  id: string;
  name: string;
  category: string;
  client_facing_copy: string;
  disposition: string;
  amount_cents: number;
  estimated_savings_cents: number;
  effective_rate_used: string;
  status_flag: string;
}
export interface QuarterRow {
  quarter: number;
  due_date: string;
  required_payment_cents: number;
  payment_made_cents: number;
  unpaid_rollforward_cents: number;
  safe_harbor_basis: string;
  status: string;
}
export interface Overview {
  client: {
    id: string;
    display_name: string;
    filing_status_default: string;
    primary_state: string | null;
    status: string;
    external_ref: string | null;
    notes: string | null;
  };
  years: YearRow[];
  base_year_id: string | null;
  plan_year_id: string | null;
  strategies: StrategyRow[];
  quarterly: QuarterRow[];
}

interface Ctx {
  clientId: string;
  overview: Overview | null;
  loading: boolean;
  reload: () => void;
}
const OverviewContext = createContext<Ctx | undefined>(undefined);

export function ClientOverviewProvider({ clientId, children }: { clientId: string; children: ReactNode }) {
  const ready = useAuthStore((s) => s.ready);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const retries = useRef(0);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .get(`/clients/${clientId}/overview`)
      .then((r) => {
        setOverview(r.data);
        retries.current = 0;
      })
      .catch(() => {
        setOverview(null);
        // A cold load (full navigation / refresh / direct link) can fire this
        // before the auth token has hydrated; retry a few times with backoff so
        // the file chrome never gets stuck on a permanent "Loading…".
        if (retries.current < 4) {
          retries.current += 1;
          setTimeout(reload, 500 * retries.current);
        }
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  // Only fetch once auth has settled. Fetching on the first paint of a cold load
  // races the token hydration and 401s into a silently-null overview, which the
  // file topbar renders as a permanent "Loading…" — the same hydration-settled
  // rule the workspace provider already follows.
  useEffect(() => {
    if (!ready) return;
    reload();
  }, [ready, reload]);

  return <OverviewContext.Provider value={{ clientId, overview, loading, reload }}>{children}</OverviewContext.Provider>;
}

export function useClientOverview(): Ctx {
  const ctx = useContext(OverviewContext);
  if (!ctx) throw new Error("useClientOverview must be used within ClientOverviewProvider");
  return ctx;
}
