"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/store";

// [OVDBG] temporary cold-load instrumentation — REMOVE in the fix commit.
function OVDBG(tag: string, data: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  // eslint-disable-next-line no-console
  console.log(`[OVDBG] ${tag}`, JSON.stringify(data));
}

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
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const retries = useRef(0);

  const reload = useCallback(() => {
    setLoading(true);
    OVDBG("provider.reload.fire", {
      clientId,
      retries: retries.current,
      ready: useAuthStore.getState().ready,
      authed: useAuthStore.getState().isAuthenticated,
    });
    // Bound the request. On a cold load the first call can race token hydration
    // (401) or STALL inside the axios auth-refresh interceptor (which has no
    // timeout) — either way the file chrome must never stick on "Loading…". A
    // per-request timeout turns a stall into a rejection; we then retry with
    // backoff until the session settles and the call returns 200.
    api
      .get(`/clients/${clientId}/overview`, { timeout: 7000 })
      .then((r) => {
        OVDBG("provider.then.OK", { status: r.status, name: r.data?.client?.display_name });
        setOverview(r.data);
        retries.current = 0;
      })
      .catch((e) => {
        OVDBG("provider.catch.FAIL", {
          status: e?.response?.status,
          code: e?.code,
          msg: e?.message,
          retries: retries.current,
        });
        setOverview(null);
        if (retries.current < 6) {
          retries.current += 1;
          setTimeout(reload, 700 * retries.current);
        }
      })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return <OverviewContext.Provider value={{ clientId, overview, loading, reload }}>{children}</OverviewContext.Provider>;
}

export function useClientOverview(): Ctx {
  const ctx = useContext(OverviewContext);
  if (!ctx) throw new Error("useClientOverview must be used within ClientOverviewProvider");
  return ctx;
}
