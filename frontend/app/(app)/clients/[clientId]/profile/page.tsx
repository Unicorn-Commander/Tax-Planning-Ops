"use client";

import { useCallback, useEffect, useState } from "react";
import { Target, Save } from "lucide-react";
import api from "@/lib/api";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Button, Field, MoneyInput, Disclaimer } from "@/components/ui";

interface Profile {
  primary_objective: string;
  retirement_target_year: number | null;
  liquidity_event: string;
  liquidity_event_year: number | null;
  liquidity_event_amount_cents: number;
  charitable_intent: string;
  annual_giving_cents: number;
  estate_priority: string;
  planned_relocation_state: string | null;
  relocation_year: number | null;
  roth_preference: string;
  risk_tolerance: string;
  cash_flow_sensitivity: string;
  education_funding: boolean;
  business_succession: string;
  notes: string | null;
}

const EMPTY: Profile = {
  primary_objective: "no_preference",
  retirement_target_year: null,
  liquidity_event: "none",
  liquidity_event_year: null,
  liquidity_event_amount_cents: 0,
  charitable_intent: "none",
  annual_giving_cents: 0,
  estate_priority: "none",
  planned_relocation_state: null,
  relocation_year: null,
  roth_preference: "no_preference",
  risk_tolerance: "moderate",
  cash_flow_sensitivity: "medium",
  education_funding: false,
  business_succession: "none",
  notes: null,
};

const selectClass =
  "h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-primary";

const OBJECTIVE = {
  no_preference: "No stated preference",
  minimize_current_tax: "Minimize current-year tax",
  minimize_lifetime_tax: "Minimize lifetime tax",
  maximize_retirement: "Maximize retirement readiness",
  wealth_transfer: "Transfer wealth to heirs",
  charitable_legacy: "Build a charitable legacy",
};
const LIQUIDITY = {
  none: "None expected",
  business_sale: "Business sale",
  equity_compensation: "Equity comp / RSU vesting",
  real_estate: "Real-estate sale",
  inheritance: "Inheritance",
  other: "Other",
};
const CHARITABLE = { none: "None", low: "Low", moderate: "Moderate", high: "High", legacy: "Legacy" };
const ESTATE = { none: "None", moderate: "Moderate", high: "High" };
const ROTH = {
  no_preference: "No preference",
  prefer_roth: "Prefer Roth",
  prefer_traditional: "Prefer traditional",
  advisor_optimize: "Let advisor optimize",
};
const RISK = { conservative: "Conservative", moderate: "Moderate", aggressive: "Aggressive" };
const CASHFLOW = { low: "Low (can defer)", medium: "Medium", high: "High (needs liquidity)" };
const SUCCESSION = {
  none: "None / n-a",
  sell_external: "Sell to outside buyer",
  transfer_family: "Transfer to family",
  esop: "ESOP",
  undecided: "Undecided",
};

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Record<string, string>;
}) {
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={selectClass}>
        {Object.entries(options).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </Field>
  );
}

function YearInput({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  return (
    <input
      type="number"
      inputMode="numeric"
      placeholder="Year"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? parseInt(e.target.value, 10) : null)}
      className={selectClass}
    />
  );
}

export default function GoalsTab() {
  const { overview, loading } = useClientOverview();
  const clientId = overview?.client.id ?? null;
  const [p, setP] = useState<Profile>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    if (!clientId) return;
    api
      .get(`/clients/${clientId}/planning-profile`)
      .then((r) => {
        if (r.data) setP({ ...EMPTY, ...r.data });
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, [clientId]);

  useEffect(load, [load]);

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => {
    setSaved(false);
    setP((prev) => ({ ...prev, [k]: v }));
  };

  const save = useAction(async () => {
    if (!clientId) return;
    await api.put(`/clients/${clientId}/planning-profile`, p);
    setSaved(true);
  });

  if (loading || !loaded) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Target className="h-4 w-4 text-primary" />
              Planning objectives
            </span>
          }
          subtitle="What the client is trying to accomplish — the strategist reads these to tailor and prioritize its advice."
        />
        <div className="grid grid-cols-1 gap-5 p-5 md:grid-cols-2">
          <Select
            label="Primary objective"
            value={p.primary_objective}
            onChange={(v) => set("primary_objective", v)}
            options={OBJECTIVE}
          />
          <Field label="Target retirement year">
            <YearInput value={p.retirement_target_year} onChange={(v) => set("retirement_target_year", v)} />
          </Field>

          <Select
            label="Expected liquidity event"
            value={p.liquidity_event}
            onChange={(v) => set("liquidity_event", v)}
            options={LIQUIDITY}
          />
          {p.liquidity_event !== "none" ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Event year">
                <YearInput value={p.liquidity_event_year} onChange={(v) => set("liquidity_event_year", v)} />
              </Field>
              <Field label="Est. amount / gain">
                <MoneyInput
                  valueCents={p.liquidity_event_amount_cents}
                  onChangeCents={(v) => set("liquidity_event_amount_cents", v ?? 0)}
                />
              </Field>
            </div>
          ) : (
            <div />
          )}

          <Select
            label="Charitable intent"
            value={p.charitable_intent}
            onChange={(v) => set("charitable_intent", v)}
            options={CHARITABLE}
          />
          {p.charitable_intent !== "none" ? (
            <Field label="Typical annual giving">
              <MoneyInput
                valueCents={p.annual_giving_cents}
                onChangeCents={(v) => set("annual_giving_cents", v ?? 0)}
              />
            </Field>
          ) : (
            <div />
          )}

          <Select
            label="Estate / wealth-transfer priority"
            value={p.estate_priority}
            onChange={(v) => set("estate_priority", v)}
            options={ESTATE}
          />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Planned move to state">
              <input
                value={p.planned_relocation_state ?? ""}
                onChange={(e) =>
                  set("planned_relocation_state", e.target.value.toUpperCase().slice(0, 2) || null)
                }
                placeholder="e.g. TX"
                className={selectClass}
              />
            </Field>
            <Field label="Move year">
              <YearInput value={p.relocation_year} onChange={(v) => set("relocation_year", v)} />
            </Field>
          </div>

          <Select
            label="Roth vs traditional preference"
            value={p.roth_preference}
            onChange={(v) => set("roth_preference", v)}
            options={ROTH}
          />
          <Select
            label="Risk tolerance"
            value={p.risk_tolerance}
            onChange={(v) => set("risk_tolerance", v)}
            options={RISK}
          />
          <Select
            label="Cash-flow sensitivity"
            value={p.cash_flow_sensitivity}
            onChange={(v) => set("cash_flow_sensitivity", v)}
            options={CASHFLOW}
          />
          <Select
            label="Business succession / exit"
            value={p.business_succession}
            onChange={(v) => set("business_succession", v)}
            options={SUCCESSION}
          />

          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            <input
              type="checkbox"
              checked={p.education_funding}
              onChange={(e) => set("education_funding", e.target.checked)}
              className="h-4 w-4 rounded border-line text-primary focus:ring-primary"
            />
            Funding education for dependents (529)
          </label>
          <div />

          <div className="md:col-span-2">
            <Field label="Advisor notes">
              <textarea
                value={p.notes ?? ""}
                onChange={(e) => set("notes", e.target.value || null)}
                rows={3}
                placeholder="Anything else that should shape the plan…"
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-primary"
              />
            </Field>
          </div>

          <div className="flex items-center gap-3 md:col-span-2">
            <Button icon={<Save className="h-4 w-4" />} loading={save.pending} onClick={() => void save.run()}>
              Save objectives
            </Button>
            {save.error ? <p className="text-[13px] text-negative">{save.error}</p> : null}
            {saved && !save.error ? <p className="text-[13px] text-positive">Saved.</p> : null}
          </div>
        </div>
        <Disclaimer className="border-t border-line-2 px-5 py-4" />
      </Card>
    </div>
  );
}
