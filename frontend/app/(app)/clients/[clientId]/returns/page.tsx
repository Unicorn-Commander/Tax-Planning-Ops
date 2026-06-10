"use client";

import { useState } from "react";
import { FileUp, Lock, CheckCircle2, FileText } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Badge, Button, MoneyInput, Disclaimer } from "@/components/ui";

interface FieldRow { id: string; field_key: string; value_cents: number | null; corrected_value_cents: number | null; confidence: number | null; status: string }
interface Extracted { id: string; extraction_status: string; fields: FieldRow[] }

const LABEL: Record<string, string> = {
  "f1040.line1z_wages": "Wages (1z)", "f1040.line2b_taxable_interest": "Taxable interest (2b)",
  "f1040.line3a_qualified_div": "Qualified dividends (3a)", "f1040.line3b_ordinary_div": "Ordinary dividends (3b)",
  "f1040.line4b_ira_taxable": "IRA taxable (4b)", "f1040.line5b_pensions_taxable": "Pensions taxable (5b)",
  "f1040.line6b_ss_taxable": "Social Security taxable (6b)", "f1040.line7_capital_gain": "Capital gain/loss (7)",
  "f1040.line8_sch1_income": "Schedule 1 income (8)", "f1040.line10_adjustments": "Adjustments (10)",
  "f1040.line12_deduction": "Deduction (12)", "f1040.line13_qbi": "QBI deduction (13)",
  "f1040.line25_withholding": "Withholding (25)", "f1040.line26_est_payments": "Estimated payments (26)",
  "f1040.line11_agi": "AGI (11)", "f1040.line15_taxable_income": "Taxable income (15)", "f1040.line24_total_tax": "Total tax (24)",
};

export default function ReturnTab() {
  const { overview, loading, reload } = useClientOverview();
  const [file, setFile] = useState<File | null>(null);
  const [extracted, setExtracted] = useState<Extracted | null>(null);

  const base = overview?.years.find((y) => y.role === "base") ?? null;
  const confirmed = base?.is_locked && base.snapshot;

  const importReturn = useAction(async () => {
    if (!file || !overview) return;
    let tyId = base?.id;
    if (!tyId) {
      const ty = await api.post("/client-tax-years", { client_id: overview.client.id, tax_year: 2025, role: "base", filing_status: overview.client.filing_status_default });
      tyId = ty.data.id;
    }
    const form = new FormData();
    form.set("file", file);
    const r = await api.post(`/client-tax-years/${tyId}/documents/form-1040`, form, { headers: { "Content-Type": "multipart/form-data" } });
    setExtracted(r.data);
  });

  async function correct(fieldId: string, cents: number | null, prev: number | null) {
    if (cents === prev) return;
    await api.patch(`/extracted-fields/${fieldId}`, { corrected_value_cents: cents });
  }

  const confirmReturn = useAction(async () => {
    if (!extracted) return;
    await api.post(`/extracted-returns/${extracted.id}/confirm`, {});
    setExtracted(null);
    reload();
  });

  if (loading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;

  // Confirmed baseline summary
  if (confirmed && base?.snapshot && !extracted) {
    const s = base.snapshot;
    const rows: [string, string][] = [
      ["Total income", centsToUSD(s.total_income_cents)], ["Adjusted gross income", centsToUSD(s.agi_cents)],
      ["Taxable income", centsToUSD(s.taxable_income_cents)], ["Total tax", centsToUSD(s.total_tax_cents)],
      ["Marginal bracket", percent(s.marginal_rate)], ["Effective rate", percent(s.effective_rate)],
    ];
    return (
      <Card>
        <CardHeader
          title={`${base.tax_year} filed return`}
          subtitle="The advisor-confirmed baseline — immutable and locked."
          action={<Badge tone="positive"><Lock className="h-3 w-3" /> Confirmed</Badge>}
        />
        <div className="grid grid-cols-2 gap-px bg-line-2 md:grid-cols-3">
          {rows.map(([k, v]) => (
            <div key={k} className="bg-surface p-5">
              <div className="text-[12px] text-muted">{k}</div>
              <div className="mt-1 text-[20px] font-semibold text-ink tabular">{v}</div>
            </div>
          ))}
        </div>
        <Disclaimer className="border-t border-line-2 px-5 py-4" />
      </Card>
    );
  }

  // Import / review flow
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Import the filed 1040" subtitle="On-prem extraction — the return never leaves your tenant." />
        <div className="flex flex-wrap items-center gap-3 p-5">
          <label className="flex h-10 cursor-pointer items-center gap-2 rounded-[var(--radius-md)] border border-dashed border-line bg-surface-2 px-4 text-[13.5px] text-ink-2 hover:border-primary">
            <FileText className="h-4 w-4 text-muted" />
            {file ? file.name : "Choose 1040 PDF…"}
            <input type="file" accept="application/pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <Button icon={<FileUp className="h-4 w-4" />} disabled={!file} loading={importReturn.pending} onClick={() => void importReturn.run()}>Import &amp; extract</Button>
          {importReturn.error ? <p className="text-[13px] text-negative">{importReturn.error}</p> : null}
        </div>
      </Card>

      {extracted ? (
        <Card>
          <CardHeader
            title="Review &amp; correct"
            subtitle="Confidence-scored fields — correct any line, then confirm the baseline."
            action={<Button icon={<CheckCircle2 className="h-4 w-4" />} loading={confirmReturn.pending} onClick={() => void confirmReturn.run()}>Confirm baseline</Button>}
          />
          <div className="divide-y divide-line-2">
            {extracted.fields.map((f) => (
              <div key={f.id} className="grid grid-cols-[1fr_160px] items-center gap-4 px-5 py-2.5">
                <div>
                  <div className="text-[13.5px] text-ink">{LABEL[f.field_key] ?? f.field_key}</div>
                  <div className="text-[11.5px] text-muted">{f.status}{f.corrected_value_cents !== null ? " · override" : ""}</div>
                </div>
                <MoneyInput valueCents={f.corrected_value_cents ?? f.value_cents} onBlurCents={(c) => void correct(f.id, c, f.corrected_value_cents ?? f.value_cents)} placeholder="0" />
              </div>
            ))}
          </div>
          <Disclaimer className="border-t border-line-2 px-5 py-4" />
        </Card>
      ) : null}
    </div>
  );
}
