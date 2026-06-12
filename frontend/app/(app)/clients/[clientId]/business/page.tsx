"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Briefcase, Plus, RefreshCw, Trash2 } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, Field, MoneyInput, EmptyState, Disclaimer } from "@/components/ui";

type EntityKind = "schedule_c" | "partnership_k1" | "s_corp_k1" | "schedule_e" | "c_corp";

interface BusinessEntity {
  id: string;
  kind: EntityKind;
  name: string;
  amount_cents: number;
  w2_wages_paid_cents: number;
  ubia_cents: number;
  guaranteed_payments_cents: number;
  shareholder_w2_wages_cents: number;
  dividends_cents: number;
  nol_available_cents: number;
  is_general_partner: boolean;
  is_sstb: boolean;
  is_qbi: boolean;
  accounting_ops_workspace_id: string | null;
}

const KIND_LABEL: Record<EntityKind, string> = {
  schedule_c: "Schedule C (sole prop)",
  partnership_k1: "Partnership K-1",
  s_corp_k1: "S-corp K-1",
  schedule_e: "Schedule E (rental)",
  c_corp: "C-corp (1120)",
};

const KIND_BADGE: Record<EntityKind, string> = {
  schedule_c: "Schedule C",
  partnership_k1: "Partnership K-1",
  s_corp_k1: "S-corp K-1",
  schedule_e: "Schedule E",
  c_corp: "C-corp",
};

function amountLabel(kind: EntityKind): string {
  switch (kind) {
    case "schedule_c":
      return "Net profit";
    case "partnership_k1":
    case "s_corp_k1":
      return "K-1 ordinary income (box 1)";
    case "schedule_e":
      return "Net rental income";
    case "c_corp":
      return "Corporate taxable income";
  }
}

const selectClass =
  "h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-primary";

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 text-[13px] text-ink-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-line text-primary focus:ring-primary"
      />
      {label}
    </label>
  );
}

export default function BusinessTab() {
  const { overview, loading } = useClientOverview();
  const taxYearId = overview?.plan_year_id ?? overview?.base_year_id ?? null;

  const [entities, setEntities] = useState<BusinessEntity[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // Form state
  const [kind, setKind] = useState<EntityKind>("schedule_c");
  const [name, setName] = useState("");
  const [amountCents, setAmountCents] = useState<number | null>(null);
  const [w2WagesCents, setW2WagesCents] = useState<number | null>(null);
  const [ubiaCents, setUbiaCents] = useState<number | null>(null);
  const [guaranteedPaymentsCents, setGuaranteedPaymentsCents] = useState<number | null>(null);
  const [shareholderW2Cents, setShareholderW2Cents] = useState<number | null>(null);
  const [dividendsCents, setDividendsCents] = useState<number | null>(null);
  const [nolAvailableCents, setNolAvailableCents] = useState<number | null>(null);
  const [isGeneralPartner, setIsGeneralPartner] = useState(false);
  const [isSstb, setIsSstb] = useState(false);
  const [isQbi, setIsQbi] = useState(true);
  const [aoWorkspaceId, setAoWorkspaceId] = useState("");

  const reloadEntities = useCallback(() => {
    if (!taxYearId) {
      setListLoading(false);
      return;
    }
    setListLoading(true);
    setListError(null);
    api
      .get(`/clients/tax-years/${taxYearId}/business-entities`)
      .then((r) => setEntities(r.data))
      .catch(() => setListError("Could not load business entities."))
      .finally(() => setListLoading(false));
  }, [taxYearId]);

  useEffect(reloadEntities, [reloadEntities]);

  const resetForm = () => {
    setName("");
    setAmountCents(null);
    setW2WagesCents(null);
    setUbiaCents(null);
    setGuaranteedPaymentsCents(null);
    setShareholderW2Cents(null);
    setDividendsCents(null);
    setNolAvailableCents(null);
    setIsGeneralPartner(false);
    setIsSstb(false);
    setIsQbi(true);
    setAoWorkspaceId("");
  };

  const showQbiInputs = kind === "schedule_c" || kind === "partnership_k1" || kind === "s_corp_k1";
  const showSstb = kind === "schedule_c" || kind === "partnership_k1" || kind === "s_corp_k1";

  const add = useAction(async () => {
    if (!taxYearId) return;
    await api.post(`/clients/tax-years/${taxYearId}/business-entities`, {
      kind,
      name,
      amount_cents: amountCents ?? 0,
      w2_wages_paid_cents: showQbiInputs ? w2WagesCents ?? 0 : 0,
      ubia_cents: showQbiInputs ? ubiaCents ?? 0 : 0,
      guaranteed_payments_cents: kind === "partnership_k1" ? guaranteedPaymentsCents ?? 0 : 0,
      shareholder_w2_wages_cents:
        kind === "s_corp_k1" || kind === "c_corp" ? shareholderW2Cents ?? 0 : 0,
      dividends_cents: kind === "c_corp" ? dividendsCents ?? 0 : 0,
      nol_available_cents: kind === "c_corp" ? nolAvailableCents ?? 0 : 0,
      is_general_partner: kind === "partnership_k1" ? isGeneralPartner : false,
      is_sstb: showSstb ? isSstb : false,
      is_qbi: kind === "schedule_e" ? isQbi : true,
      accounting_ops_workspace_id: aoWorkspaceId.trim() || null,
    });
    resetForm();
    reloadEntities();
  });

  const remove = useAction(async (id: string) => {
    if (!taxYearId) return;
    await api.delete(`/clients/tax-years/${taxYearId}/business-entities/${id}`);
    reloadEntities();
  });

  const syncAo = useAction(async (id: string) => {
    if (!taxYearId) return;
    await api.post(`/clients/tax-years/${taxYearId}/business-entities/${id}/sync-accounting-ops`);
    reloadEntities();
  });

  if (loading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;

  if (!taxYearId) {
    return (
      <EmptyState
        icon={<Briefcase className="h-5 w-5" />}
        title="No tax year yet"
        body="Import and confirm a return on the Return tab to enter business entities."
        action={<Link href={`/clients/${overview?.client.id}`}><Button>Go to overview</Button></Link>}
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
      <Card>
        <CardHeader title="Business entities" subtitle={`${entities.length} pass-through entit${entities.length === 1 ? "y" : "ies"}`} />
        <div className="divide-y divide-line-2">
          {listLoading ? (
            <div className="px-5 py-10"><div className="h-20 skeleton rounded-[var(--radius-md)]" /></div>
          ) : listError ? (
            <div className="px-5 py-10 text-center text-[13.5px] text-negative">{listError}</div>
          ) : entities.length === 0 ? (
            <div className="px-5 py-10 text-center text-[13.5px] text-muted">No business entities yet — add one →</div>
          ) : (
            entities.map((e) => (
              <div key={e.id} className="px-5 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[14.5px] font-medium text-ink">{e.name}</span>
                      <Badge tone="primary">{KIND_BADGE[e.kind]}</Badge>
                      {e.kind !== "schedule_e" && e.is_sstb ? <Badge tone="warning">SSTB</Badge> : null}
                      {e.kind === "partnership_k1" && e.is_general_partner ? <Badge tone="neutral">General partner</Badge> : null}
                      {e.kind === "schedule_e" ? <Badge tone={e.is_qbi ? "positive" : "neutral"}>{e.is_qbi ? "§199A QBI" : "Not QBI"}</Badge> : null}
                      {e.accounting_ops_workspace_id ? <Badge tone="primary">Accounting-Ops linked</Badge> : null}
                    </div>
                    <p className="mt-1.5 text-[12.5px] text-muted tabular">
                      {e.kind === "schedule_e" ? "Net rental income" : amountLabel(e.kind)} {centsToUSD(e.amount_cents)}
                    </p>
                    {(e.kind === "schedule_c" || e.kind === "partnership_k1" || e.kind === "s_corp_k1") &&
                    (e.w2_wages_paid_cents > 0 || e.ubia_cents > 0) ? (
                      <p className="mt-1 text-[12px] text-muted tabular">
                        W-2 wages {centsToUSD(e.w2_wages_paid_cents)} · UBIA {centsToUSD(e.ubia_cents)}
                      </p>
                    ) : null}
                    {e.kind === "partnership_k1" && e.guaranteed_payments_cents > 0 ? (
                      <p className="mt-1 text-[12px] text-muted tabular">Guaranteed payments {centsToUSD(e.guaranteed_payments_cents)}</p>
                    ) : null}
                    {e.kind === "s_corp_k1" && e.shareholder_w2_wages_cents > 0 ? (
                      <p className="mt-1 text-[12px] text-muted tabular">Shareholder W-2 wages {centsToUSD(e.shareholder_w2_wages_cents)}</p>
                    ) : null}
                    {e.kind === "c_corp" &&
                    (e.shareholder_w2_wages_cents > 0 || e.dividends_cents > 0 || e.nol_available_cents > 0) ? (
                      <p className="mt-1 text-[12px] text-muted tabular">
                        Owner salary {centsToUSD(e.shareholder_w2_wages_cents)} · dividends {centsToUSD(e.dividends_cents)} · NOL {centsToUSD(e.nol_available_cents)}
                      </p>
                    ) : null}
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[15px] font-semibold text-ink tabular">{centsToUSD(e.amount_cents)}</div>
                    <div className="mt-1.5 flex items-center justify-end gap-1">
                      {e.accounting_ops_workspace_id ? (
                        <Button
                          variant="ghost"
                          icon={<RefreshCw className="h-4 w-4" />}
                          loading={syncAo.pending}
                          className="h-8 px-2 text-primary"
                          onClick={() => void syncAo.run(e.id)}
                        >
                          Pull from AO
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        icon={<Trash2 className="h-4 w-4" />}
                        loading={remove.pending}
                        className="h-8 px-2 text-negative"
                        onClick={() => void remove.run(e.id)}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                </div>
                {e.accounting_ops_workspace_id ? (
                  <p className="mt-1 text-[11.5px] text-muted">
                    AO workspace {e.accounting_ops_workspace_id}
                    {syncAo.error ? <span className="text-negative"> · {syncAo.error}</span> : null}
                  </p>
                ) : null}
              </div>
            ))
          )}
        </div>
        <Disclaimer className="border-t border-line-2 px-5 py-4" />
      </Card>

      <Card className="self-start">
        <CardHeader title="Add entity" subtitle="Pass-through business income for SE-tax & QBI" />
        <div className="space-y-4 p-5">
          <Field label="Entity type">
            <select value={kind} onChange={(e) => setKind(e.target.value as EntityKind)} className={selectClass}>
              {(Object.keys(KIND_LABEL) as EntityKind[]).map((k) => (
                <option key={k} value={k}>{KIND_LABEL[k]}</option>
              ))}
            </select>
          </Field>
          <Field label="Name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Acme Consulting LLC"
              className={selectClass}
            />
          </Field>
          <Field label={amountLabel(kind)}>
            <MoneyInput valueCents={amountCents} onChangeCents={setAmountCents} />
          </Field>

          {showQbiInputs ? (
            <>
              <Field label="W-2 wages paid (for QBI)">
                <MoneyInput valueCents={w2WagesCents} onChangeCents={setW2WagesCents} />
              </Field>
              <Field label="Qualified-property basis (UBIA)">
                <MoneyInput valueCents={ubiaCents} onChangeCents={setUbiaCents} />
              </Field>
            </>
          ) : null}

          {kind === "partnership_k1" ? (
            <>
              <Field label="Guaranteed payments">
                <MoneyInput valueCents={guaranteedPaymentsCents} onChangeCents={setGuaranteedPaymentsCents} />
              </Field>
              <Checkbox checked={isGeneralPartner} onChange={setIsGeneralPartner} label="General partner (subject to SE tax)" />
            </>
          ) : null}

          {kind === "s_corp_k1" ? (
            <Field label="Shareholder W-2 wages">
              <MoneyInput valueCents={shareholderW2Cents} onChangeCents={setShareholderW2Cents} />
            </Field>
          ) : null}

          {kind === "c_corp" ? (
            <>
              <Field label="Owner salary (W-2)">
                <MoneyInput valueCents={shareholderW2Cents} onChangeCents={setShareholderW2Cents} />
              </Field>
              <Field label="Dividends to owner">
                <MoneyInput valueCents={dividendsCents} onChangeCents={setDividendsCents} />
              </Field>
              <Field label="NOL carryforward available">
                <MoneyInput valueCents={nolAvailableCents} onChangeCents={setNolAvailableCents} />
              </Field>
            </>
          ) : null}

          {showSstb ? (
            <Checkbox checked={isSstb} onChange={setIsSstb} label="Specified service trade/business (SSTB)" />
          ) : null}

          {kind === "schedule_e" ? (
            <Checkbox checked={isQbi} onChange={setIsQbi} label="This rental rises to a §199A trade/business" />
          ) : null}

          <Field label="Accounting-Ops workspace ID (optional)">
            <input
              value={aoWorkspaceId}
              onChange={(e) => setAoWorkspaceId(e.target.value)}
              placeholder="Link to pull net income from the books"
              className={selectClass}
            />
          </Field>

          <Button
            className="w-full"
            icon={<Plus className="h-4 w-4" />}
            loading={add.pending}
            disabled={!name || amountCents === null}
            onClick={() => void add.run()}
          >
            Add entity
          </Button>
          {add.error ? <p className="text-[13px] text-negative">{add.error}</p> : null}
        </div>
      </Card>
    </div>
  );
}
