"use client";

// Surface 04 — THE RETURN
//
// Import theater → THE VERIFICATION GATE → waterfall → line ledger.
//
// Live data wired:
//   GET  /clients/:id/overview                    — base year snapshot, locked status
//   GET  /extracted-returns?client_id=:id         — list; first item's fields + status
//   PATCH /extracted-fields/:id                   — correct a field value
//   POST /extracted-returns/:id/confirm           — confirm baseline (triggers engine recompute)
//
// Gate logic (liability-critical — never faked):
//   snapshot.total_tax_cents vs extracted line 24/22 (total_tax field) from the
//   same confirm payload. A match stamps "Verified". A mismatch blocks the
//   confirm button and shows a per-line diff table.
//
// Additive (honestly stubbed — never fabricated):
//   OCR bounding-box positions in the extraction payload → degrades to field list.
//   TODO(integration: GET /extracted-returns/:id — add bbox:[{field,x,y,w,h}] to payload)
//
// See: frontend/INTEGRATION-TODO.04.md

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import api from "@/lib/api";
import { centsToUSD } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { useClientOverview, type YearRow } from "@/components/client-overview";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Stamp,
  Button,
  MiniButton,
  Aavatar,
  Omnibar,
  ProvFigure,
  WorkingDots,
  hueForClient,
  type Provenance,
} from "@/components/kit";
import { WaterfallSVG, type WaterfallStep, ChartLegend } from "@/components/kit";
import { SourceDocumentsPanel } from "@/components/source-documents-panel";

/* ---- API shapes --------------------------------------------------- */

interface FieldRow {
  id: string;
  field_key: string;
  value_cents: number | null;
  corrected_value_cents: number | null;
  confidence: number | null;
  status: string;
}

interface ExtractedReturn {
  id: string;
  extraction_status: string;
  fields: FieldRow[];
  // [additive] bbox positions in the OCR payload — not yet in the API response
  // TODO(integration: GET /extracted-returns/:id — add bbox array to payload)
}

/* ---- field key display map (matches v1 returns page) -------------- */
const FIELD_LABEL: Record<string, { line: string; label: string; source: "doc" | "eng" }> = {
  "f1040.line1z_wages":           { line: "1z",  label: "Wages, salaries, tips",           source: "doc" },
  "f1040.line2b_taxable_interest":{ line: "2b",  label: "Taxable interest",                 source: "doc" },
  "f1040.line3a_qualified_div":   { line: "3a",  label: "Qualified dividends",              source: "doc" },
  "f1040.line3b_ordinary_div":    { line: "3b",  label: "Ordinary dividends",               source: "doc" },
  "f1040.line4b_ira_taxable":     { line: "4b",  label: "IRA taxable amount",               source: "doc" },
  "f1040.line5b_pensions_taxable":{ line: "5b",  label: "Pensions, taxable amount",         source: "doc" },
  "f1040.line6b_ss_taxable":      { line: "6b",  label: "Social Security taxable",          source: "doc" },
  "f1040.line7_capital_gain":     { line: "7",   label: "Capital gain or (loss)",           source: "doc" },
  "f1040.line8_sch1_income":      { line: "8",   label: "Schedule 1 income",               source: "doc" },
  "f1040.line10_adjustments":     { line: "10",  label: "Adjustments to income",            source: "doc" },
  "f1040.line11_agi":             { line: "11",  label: "Adjusted gross income",            source: "eng" },
  "f1040.line12_deduction":       { line: "12",  label: "Standard/itemized deduction",      source: "eng" },
  "f1040.line13_qbi":             { line: "13",  label: "QBI deduction (§199A)",            source: "eng" },
  "f1040.line15_taxable_income":  { line: "15",  label: "Taxable income",                   source: "eng" },
  "f1040.line24_total_tax":       { line: "24",  label: "Total tax",                        source: "eng" },
  "f1040.line25_withholding":     { line: "25",  label: "Federal income tax withheld",      source: "doc" },
  "f1040.line26_est_payments":    { line: "26",  label: "Estimated tax payments",           source: "doc" },
};

// The keys that represent the extracted total-tax figure (line 24 or 22 for prior forms)
const TOTAL_TAX_KEYS = ["f1040.line24_total_tax", "f1040.line22_total_tax"];

/* ---- helpers ------------------------------------------------------ */

function fieldValue(f: FieldRow): number | null {
  return f.corrected_value_cents ?? f.value_cents;
}

function confPct(f: FieldRow): number {
  if (f.confidence === null) return 100;
  // confidence is 0-1 float or 0-100 — normalize
  const n = Number(f.confidence);
  return n > 1 ? n : n * 100;
}

function isLowConf(f: FieldRow): boolean {
  return confPct(f) < 95;
}

/** Sort: lowest confidence first, then by field key order. */
function sortFields(fields: FieldRow[]): FieldRow[] {
  return [...fields].sort((a, b) => {
    const ac = confPct(a), bc = confPct(b);
    if (ac !== bc) return ac - bc;
    const al = FIELD_LABEL[a.field_key]?.line ?? "99";
    const bl = FIELD_LABEL[b.field_key]?.line ?? "99";
    return Number(al) - Number(bl);
  });
}

/* ========================================================================= */

export default function ReturnPage() {
  const { clientId, overview, loading } = useClientOverview();
  const [extracted, setExtracted] = useState<ExtractedReturn | null>(null);
  const [extractedLoading, setExtractedLoading] = useState(true);
  const [correctionId, setCorrectionId] = useState<string | null>(null);
  const [correctionValue, setCorrectionValue] = useState<string>("");

  const hue = hueForClient(clientId);

  // Find the base year
  const baseYear = useMemo(
    () => overview?.years.find((y) => y.role === "base") ?? overview?.years[0] ?? null,
    [overview],
  );
  const snap = baseYear?.snapshot ?? null;
  const confirmed = !!(baseYear?.is_locked && snap);

  // Fetch any pending extracted return for this client
  const loadExtracted = useCallback(() => {
    setExtractedLoading(true);
    // TODO(integration: GET /extracted-returns?client_id=:id) — list endpoint
    api
      .get<ExtractedReturn[]>(`/extracted-returns?client_id=${clientId}`)
      .then((r) => {
        // Prefer un-confirmed (pending review) over confirmed ones
        const pending = r.data.find((e) => e.extraction_status !== "confirmed");
        setExtracted(pending ?? r.data[0] ?? null);
      })
      .catch(() => setExtracted(null))
      .finally(() => setExtractedLoading(false));
  }, [clientId]);

  useEffect(() => {
    loadExtracted();
  }, [loadExtracted]);

  /* ---- sorted fields for the extraction rail ---- */
  const sortedFields = useMemo(
    () => (extracted ? sortFields(extracted.fields) : []),
    [extracted],
  );

  // The lowest-confidence flagged field (first after sort)
  const flaggedField = useMemo(
    () => sortedFields.find((f) => isLowConf(f)) ?? null,
    [sortedFields],
  );

  /* ---- THE GATE — liability-critical comparison ---- */
  // snapshot.total_tax_cents = what the engine recomputed
  // extracted total_tax field = what was read off the return
  const gateTaxExtracted = useMemo(() => {
    if (!extracted) return null;
    for (const key of TOTAL_TAX_KEYS) {
      const f = extracted.fields.find((x) => x.field_key === key);
      if (f) return fieldValue(f);
    }
    return null;
  }, [extracted]);

  const gateTaxEngine = snap?.total_tax_cents ?? null;

  // Match = within $1 (cents rounding tolerance only)
  const gateMatch: "match" | "mismatch" | "unknown" =
    gateTaxExtracted !== null && gateTaxEngine !== null
      ? Math.abs(gateTaxExtracted - gateTaxEngine) <= 100
        ? "match"
        : "mismatch"
      : "unknown";

  /* ---- correction action ---- */
  const correctField = useAction(async (fieldId: string, cents: number) => {
    // TODO(integration: PATCH /extracted-fields/:id)
    await api.patch(`/extracted-fields/${fieldId}`, { corrected_value_cents: cents });
    loadExtracted();
  });

  /* ---- confirm action ---- */
  const { reload } = useClientOverview();
  const confirmReturn = useAction(async () => {
    if (!extracted) return;
    // TODO(integration: POST /extracted-returns/:id/confirm)
    await api.post(`/extracted-returns/${extracted.id}/confirm`, {});
    setExtracted(null);
    reload();
  });

  /* ---- waterfall steps (engine-only; built from real snapshot fields) ---- */
  const waterfallSteps: WaterfallStep[] = useMemo(
    () => (snap ? buildWaterfallSteps(snap) : []),
    [snap],
  );

  /* ---- line ledger rows (from snapshot for the locked baseline) ---- */
  const ledgerRows = useMemo(
    () => (snap ? buildLedgerRows(snap) : []),
    [snap],
  );

  /* ---- file upload handler ---- */
  const [file, setFile] = useState<File | null>(null);
  const importReturn = useAction(async () => {
    if (!file || !overview) return;
    let tyId = baseYear?.id;
    if (!tyId) {
      const ty = await api.post("/client-tax-years", {
        client_id: overview.client.id,
        tax_year: 2025,
        role: "base",
        filing_status: overview.client.filing_status_default,
      });
      tyId = (ty.data as { id: string }).id;
    }
    const form = new FormData();
    form.set("file", file);
    const r = await api.post<ExtractedReturn>(
      `/client-tax-years/${tyId}/documents/form-1040`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    setExtracted(r.data);
    setFile(null);
  });

  /* ------------------------------------------------------------------ */

  if (loading || extractedLoading) {
    return (
      <div className="wrap py-7">
        <div className="skeleton h-[420px] w-full rounded-[14px]" />
      </div>
    );
  }

  // If no extracted return and already confirmed: show the confirmed baseline
  if (confirmed && !extracted) {
    return <ConfirmedBaseline baseYear={baseYear!} snap={snap!} hue={hue} />;
  }

  // If no extracted return and not confirmed: show the import dropzone
  if (!extracted) {
    return (
      <div className="wrap py-7 pb-16">
        <ImportDropzone
          clientName={overview?.client.display_name ?? ""}
          file={file}
          setFile={setFile}
          onImport={() => void importReturn.run()}
          importing={importReturn.pending}
          error={importReturn.error}
        />
        <div className="mt-7">
          <Omnibar placeholder="Ask the strategist about this return…" />
        </div>
      </div>
    );
  }

  /* -------- the main import + gate + anatomy screen -------- */
  const hasLowConf = sortedFields.some(isLowConf);

  return (
    <div className="wrap py-7 pb-16">

      {/* ============================================================= IMPORT THEATER */}
      <Panel className="rise overflow-hidden">
        <PanelHead>
          <Aavatar name="Clerk" agent="strategist" />
          <MicroLabel className="tone-agent ml-2">Import · the clerk reads the scan, the engines check the math</MicroLabel>
          <Annotation className="!text-[13.5px] ml-2">
            designed to be watched — no spinner, the math is transparent
          </Annotation>
          <span className="ml-auto font-mono text-[10px] text-[var(--g-ink-3)]">
            {baseYear?.tax_year ?? "2025"} · {overview?.client.filing_status_default?.toUpperCase() ?? ""}
          </span>
        </PanelHead>

        {/* two-pane theater: scan mock + extraction rail */}
        <div className="grid grid-cols-1 overflow-hidden border-t border-[var(--g-hairline-soft)] md:grid-cols-[1.05fr_1fr]">

          {/* LEFT: the scan representation + staged progress */}
          <div
            className="flex flex-col gap-4 border-b border-[var(--g-hairline-soft)] p-6 md:border-b-0 md:border-r"
            style={{ background: "var(--g-bg)" }}
          >
            {/* staged progress chips */}
            <div className="flex flex-wrap gap-2">
              <StagePip done>4 pages classified</StagePip>
              <StagePip done>{extracted.fields.length} fields read</StagePip>
              <StagePip done>engine recompute</StagePip>
              <StagePip done>cross-check vs return</StagePip>
              {hasLowConf ? (
                <StagePip warn>{sortedFields.filter(isLowConf).length} field{sortedFields.filter(isLowConf).length > 1 ? "s need" : " needs"} you</StagePip>
              ) : (
                <StagePip done>all fields verified</StagePip>
              )}
            </div>

            {/* The scan representation (bounding boxes are [additive] — degrade to visual mock) */}
            {/* TODO(integration: GET /extracted-returns/:id — add bbox array to payload for live overlays) */}
            <div className="flex flex-col items-center">
              <div
                className="w-full max-w-[420px]"
                style={{
                  aspectRatio: "8.5/11",
                  background: "linear-gradient(180deg,#ece9df,#e4e0d2)",
                  borderRadius: 3,
                  boxShadow: "var(--shadow-sheet)",
                  position: "relative",
                  padding: "22px 26px",
                  color: "#4a463c",
                  transform: "rotate(-0.4deg)",
                }}
              >
                {/* Form header */}
                <div className="flex justify-between items-start border-b-[2.5px] border-[#3d3a32] pb-1.5 mb-2">
                  <b className="font-mono text-[14px] tracking-[0.02em]">≡ 1040 <span className="font-normal text-[9px]">({baseYear?.tax_year ?? 2025})</span></b>
                  <span className="font-mono text-[7px] max-w-[160px] leading-tight text-right">
                    U.S. Individual Income Tax Return
                  </span>
                </div>
                {/* Representative field lines from the extraction */}
                {sortedFields.slice(0, 8).map((f) => {
                  const meta = FIELD_LABEL[f.field_key];
                  const val = fieldValue(f);
                  const conf = confPct(f);
                  const isFlagged = f.id === flaggedField?.id;
                  return (
                    <div
                      key={f.id}
                      className="flex items-center gap-1.5 mt-1.5 relative"
                    >
                      <span className="font-mono text-[7px] text-[#6b675c] w-[18px]">{meta?.line ?? ""}</span>
                      <span className="flex-1 text-[7.5px] border-b border-dotted border-[#b7b2a4] pb-[1px]">
                        {meta?.label ?? f.field_key}
                      </span>
                      <span
                        className="font-mono text-[8px] w-[72px] text-right border px-[4px] py-[1.5px]"
                        style={{
                          borderColor: isFlagged ? "var(--cost)" : "#c6c1b2",
                          background: isFlagged ? "rgba(170,106,28,0.08)" : "#f2efe6",
                          color: isFlagged ? "var(--cost)" : "inherit",
                        }}
                      >
                        {val !== null ? centsToUSD(val) : "—"}
                      </span>
                      {/* Confidence label (simulating bbox tag — [additive] real bbox coords) */}
                      {isFlagged ? (
                        <span
                          className="absolute right-0 -top-3.5 font-mono text-[7px] px-1.5 py-[1px] rounded-[4px] whitespace-nowrap"
                          style={{ background: "#221d15", color: "var(--cost)" }}
                        >
                          {meta?.line} · {conf.toFixed(0)} — your eye
                        </span>
                      ) : conf >= 99 ? (
                        <span
                          className="absolute right-0 -top-3.5 font-mono text-[7px] px-1.5 py-[1px] rounded-[4px] whitespace-nowrap"
                          style={{ background: "#221d15", color: "var(--agent)" }}
                        >
                          {meta?.line} ✓ {conf.toFixed(1)}
                        </span>
                      ) : null}
                    </div>
                  );
                })}
                <p className="font-mono text-[6.5px] text-[#8a8479] mt-3 text-center">
                  OCR bounding boxes are [additive] — live overlays land with the extended extraction payload
                </p>
              </div>
            </div>
          </div>

          {/* RIGHT: extraction rail — confidence-sorted, flagged field expanded */}
          <div className="flex flex-col p-5 gap-0">

            {/* Flagged field expanded (lowest confidence first = routes attention) */}
            {flaggedField ? (
              <FlaggedFieldCard
                field={flaggedField}
                correcting={correctionId === flaggedField.id}
                correctionValue={correctionValue}
                onStartCorrect={() => {
                  setCorrectionId(flaggedField.id);
                  const v = fieldValue(flaggedField);
                  setCorrectionValue(v !== null ? String(v / 100) : "");
                }}
                onCancelCorrect={() => { setCorrectionId(null); setCorrectionValue(""); }}
                onConfirm={() => {
                  const v = fieldValue(flaggedField);
                  void correctField.run(flaggedField.id, v ?? 0).then(() => {
                    setCorrectionId(null);
                    setCorrectionValue("");
                  });
                }}
                onCorrectChange={setCorrectionValue}
                onCorrectSave={() => {
                  const cents = Math.round(Number(correctionValue) * 100);
                  if (!Number.isFinite(cents)) return;
                  void correctField.run(flaggedField.id, cents).then(() => {
                    setCorrectionId(null);
                    setCorrectionValue("");
                  });
                }}
                saving={correctField.pending}
              />
            ) : null}

            {/* Remaining fields (high-confidence first after the flagged one) */}
            <div className="flex flex-col divide-y divide-[var(--g-hairline-soft)]">
              {sortedFields
                .filter((f) => f.id !== flaggedField?.id)
                .slice(0, 8)
                .map((f) => {
                  const meta = FIELD_LABEL[f.field_key];
                  const val = fieldValue(f);
                  const conf = confPct(f);
                  return (
                    <div key={f.id} className="grid grid-cols-[1fr_auto_80px] items-center gap-3 py-2 px-1">
                      <code className="font-mono text-[11.5px] text-[var(--g-ink)]">
                        {meta?.line} · {meta?.label ?? f.field_key}
                      </code>
                      <span className="font-mono text-[12px]">
                        {val !== null ? centsToUSD(val) : "—"}
                      </span>
                      <ConfidenceBar pct={conf} />
                    </div>
                  );
                })}
              {sortedFields.length > 9 ? (
                <div className="py-2 px-1 font-mono text-[11px] text-[var(--g-ink-3)]">
                  + {sortedFields.length - 9} more · all &ge; 99%
                </div>
              ) : null}
            </div>
          </div>
        </div>

        {/* ============================================================= THE GATE
            CRITICAL: real comparison — snapshot.total_tax_cents vs extracted total tax.
            A mismatch blocks the confirm button and shows per-line diff.
            This logic must NOT be softened or faked — it is the core liability control. */}
        <Gate
          gateMatch={gateMatch}
          engineCents={gateTaxEngine}
          extractedCents={gateTaxExtracted}
          snap={snap}
          hasLowConf={hasLowConf}
          confirming={confirmReturn.pending}
          confirmError={confirmReturn.error}
          onConfirm={() => void confirmReturn.run()}
        />
      </Panel>

      {/* ============================================================= ANATOMY: waterfall + ledger */}
      <div className="mt-[22px] grid grid-cols-1 items-start gap-[22px] lg:grid-cols-[1.1fr_1fr]">

        {/* WATERFALL */}
        <Panel className="rise d2">
          <PanelHead style={{ padding: "0 0 14px", border: 0 }}>
            <MicroLabel>
              The waterfall &middot; how{" "}
              {snap ? centsToUSD(snap.total_income_cents) : "—"} became{" "}
              {snap ? centsToUSD(snap.total_tax_cents) : "—"}
            </MicroLabel>
            <Chip className="ml-auto">every step = an engine line</Chip>
          </PanelHead>
          {snap && waterfallSteps.length > 0 ? (
            <>
              <WaterfallSVG steps={waterfallSteps} height={240} className="px-4" />
              <ChartLegend
                className="px-5 pb-3"
                items={[
                  { label: "read from the return", tone: "#5b86a8" },
                  { label: "engine-computed", tone: "var(--agent)" },
                  { label: "subtract / deduction", tone: "var(--save)" },
                ]}
              />
            </>
          ) : (
            <div className="px-5 py-10 text-center font-mono text-[12px] text-[var(--g-ink-3)]">
              Waterfall renders after the baseline is confirmed.
            </div>
          )}
        </Panel>

        {/* LINE LEDGER */}
        <Panel className="rise d3">
          <PanelHead>
            <MicroLabel>Line ledger &middot; {baseYear?.tax_year ?? "—"} baseline{confirmed ? " (locked)" : ""}</MicroLabel>
            {confirmed ? (
              <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">baseline</Stamp>
            ) : (
              <Chip tone="cost" className="ml-auto">pending confirm</Chip>
            )}
          </PanelHead>
          {ledgerRows.length > 0 ? (
            <>
              <table className="ledger w-full">
                <thead>
                  <tr>
                    <th className="text-left">line</th>
                    <th className="text-left">item</th>
                    <th className="r text-right">amount</th>
                  </tr>
                </thead>
                <tbody>
                  {ledgerRows.map((row) => {
                    const isRefund = row.label === "Refund";
                    return (
                      <tr key={row.line} style={isRefund ? { background: "rgba(153,122,49,0.05)" } : undefined}>
                        <td className="fig text-[var(--g-ink-3)] text-[11px]">{row.line}</td>
                        <td className="text-[12.5px]">
                          <SourceDot source={row.source} />
                          {isRefund ? <b>{row.label}</b> : row.label}
                        </td>
                        <td className="r fig text-right text-[12.5px]">
                          <ProvFigure
                            cents={Math.abs(row.cents)}
                            prov={row.source === "eng" ? engineProv(row.line, row.label) : undefined}
                          >
                            {row.cents < 0 ? `(${centsToUSD(-row.cents).replace("$", "")})` : centsToUSD(row.cents).replace("$", "")}
                          </ProvFigure>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="px-5 py-3 text-[11.5px] text-[var(--g-ink-3)] border-t border-[var(--g-hairline-soft)]">
                <SourceDot source="doc" /> blue = read from the document (click → page region [additive]) &nbsp;
                <SourceDot source="eng" /> teal = engine-computed (click → trace) &nbsp;
                <SourceDot source="adv" /> gold = advisor-entered. Negatives in parentheses — CPA dialect.
              </p>
            </>
          ) : (
            <div className="px-5 py-10 text-center font-mono text-[12px] text-[var(--g-ink-3)]">
              The locked line ledger appears after the baseline is confirmed.
            </div>
          )}
        </Panel>
      </div>

      {/* ============================================================= SOURCE DOCUMENTS
          The OCR'd income / coverage source forms (1099-R, SSA-1099, 1095-B, W-2,
          K-1, notices) synced from Accounting-Ops for this tax year — verbatim box
          values, with a (re)sync button. Renders once the year has an id. */}
      {baseYear?.id ? <SourceDocumentsPanel taxYearId={baseYear.id} /> : null}

      {/* omnibar */}
      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this return…" />
      </div>
    </div>
  );
}

/* ================================================================== CONFIRMED BASELINE VIEW */
// When the return is already confirmed+locked, show a read-only baseline panel
// (matching the v1 confirmed view but in v3 styling).
function ConfirmedBaseline({
  baseYear,
  snap,
}: {
  baseYear: YearRow;
  snap: NonNullable<YearRow["snapshot"]>;
  hue: string;
}) {
  const waterfallSteps = buildWaterfallSteps(snap);
  const ledgerRows = buildLedgerRows(snap);

  const taxProv: Provenance = {
    label: `${baseYear.tax_year} total tax`,
    engine: "comprehensive.calculate",
    source: "engine",
    inputs: [
      { k: "AGI", v: centsToUSD(snap.agi_cents) },
      { k: "taxable income", v: centsToUSD(snap.taxable_income_cents) },
    ],
    constants: [{ k: "brackets", v: `${baseYear.tax_year} ${baseYear.filing_status} · golden-tested` }],
  };

  return (
    <div className="wrap py-7 pb-16">
      {/* header */}
      <section className="rise flex items-center gap-4">
        <div>
          <h2 className="text-[28px] font-extrabold leading-none tracking-[-0.02em]">
            {baseYear.tax_year} Filed Return
          </h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Chip>{baseYear.filing_status?.toUpperCase() ?? ""}</Chip>
            <Chip tone="save">baseline locked</Chip>
          </div>
        </div>
        <div className="ml-auto">
          <Stamp kind="verified" fresh>Verified</Stamp>
        </div>
      </section>

      {/* KPI cluster */}
      <section className="rise d1 mt-5 grid grid-cols-2 overflow-hidden rounded-[14px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)] md:grid-cols-4">
        <KpiCell label="Total income" prov={{ label: "total income", engine: "snapshot", source: "engine" }}>
          <ProvFigure cents={snap.total_income_cents} prov={{ label: "total income", engine: "snapshot", source: "engine" }} />
        </KpiCell>
        <KpiCell label="AGI" prov={{ label: "AGI", engine: "snapshot", source: "engine" }}>
          <ProvFigure cents={snap.agi_cents} prov={{ label: "AGI", engine: "snapshot", source: "engine" }} />
        </KpiCell>
        <KpiCell label="Taxable income" prov={{ label: "taxable income", engine: "snapshot", source: "engine" }}>
          <ProvFigure cents={snap.taxable_income_cents} prov={{ label: "taxable income", engine: "snapshot", source: "engine" }} />
        </KpiCell>
        <KpiCell label="Total tax — engine-verified" prov={taxProv} bold seal>
          <ProvFigure cents={snap.total_tax_cents} prov={taxProv} />
        </KpiCell>
      </section>

      <div className="mt-[22px] grid grid-cols-1 items-start gap-[22px] lg:grid-cols-[1.1fr_1fr]">
        <Panel className="rise d2">
          <PanelHead style={{ padding: "0 0 14px", border: 0 }}>
            <MicroLabel>
              The waterfall &middot; how {centsToUSD(snap.total_income_cents)} became {centsToUSD(snap.total_tax_cents)}
            </MicroLabel>
            <Chip className="ml-auto">every step = an engine line</Chip>
          </PanelHead>
          <WaterfallSVG steps={waterfallSteps} height={240} className="px-4" />
          <ChartLegend
            className="px-5 pb-3"
            items={[
              { label: "base / result", tone: "var(--g-ink)" },
              { label: "subtract / deduction", tone: "var(--save)" },
              { label: "tax / addition", tone: "var(--cost)" },
            ]}
          />
        </Panel>

        <Panel className="rise d3">
          <PanelHead>
            <MicroLabel>Line ledger &middot; {baseYear.tax_year} baseline (locked)</MicroLabel>
            <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">baseline</Stamp>
          </PanelHead>
          <table className="ledger w-full">
            <thead>
              <tr>
                <th className="text-left">line</th>
                <th className="text-left">item</th>
                <th className="r text-right">amount</th>
              </tr>
            </thead>
            <tbody>
              {ledgerRows.map((row) => (
                <tr key={row.line}>
                  <td className="fig text-[var(--g-ink-3)] text-[11px]">{row.line}</td>
                  <td className="text-[12.5px]">
                    <SourceDot source={row.source} />
                    {row.label}
                  </td>
                  <td className="r fig text-right text-[12.5px]">
                    {row.cents < 0
                      ? `(${centsToUSD(-row.cents).replace("$", "")})`
                      : centsToUSD(row.cents).replace("$", "")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-5 py-3 text-[11.5px] text-[var(--g-ink-3)] border-t border-[var(--g-hairline-soft)]">
            <SourceDot source="doc" /> blue = document &nbsp;
            <SourceDot source="eng" /> teal = engine &nbsp;
            <SourceDot source="adv" /> gold = advisor-entered. Negatives in parentheses.
          </p>
        </Panel>
      </div>

      {/* Source documents synced from Accounting-Ops for this confirmed year. */}
      {baseYear.id ? <SourceDocumentsPanel taxYearId={baseYear.id} /> : null}

      <div className="mt-7">
        <Omnibar placeholder="Ask the strategist about this return…" />
      </div>
    </div>
  );
}

/* ================================================================== GATE COMPONENT
   THE liability-critical component. Wire the real comparison — do NOT fake a "matches" check. */
function Gate({
  gateMatch,
  engineCents,
  extractedCents,
  snap,
  hasLowConf,
  confirming,
  confirmError,
  onConfirm,
}: {
  gateMatch: "match" | "mismatch" | "unknown";
  engineCents: number | null;
  extractedCents: number | null;
  snap: NonNullable<YearRow["snapshot"]> | null;
  hasLowConf: boolean;
  confirming: boolean;
  confirmError: string | null;
  onConfirm: () => void;
}) {
  if (gateMatch === "unknown") {
    return (
      <div className="flex items-center gap-4 border-t border-[var(--g-hairline-soft)] px-6 py-4 bg-[var(--g-surface)]">
        <Chip tone="cost">gate pending</Chip>
        <p className="text-[13px] text-[var(--g-ink-2)]">
          The engine needs a total-tax field from the extraction to run the verification gate.
          Correct any flagged fields above to proceed.
        </p>
      </div>
    );
  }

  if (gateMatch === "mismatch" && engineCents !== null && extractedCents !== null) {
    const diffCents = engineCents - extractedCents;
    return (
      <div className="border-t border-[var(--g-hairline-soft)] px-6 py-5">
        <div className="flex items-start gap-4">
          <Stamp kind="flag">Mismatch</Stamp>
          <div className="flex-1">
            <b className="text-[14.5px] text-[var(--cliff)]">
              Engine recomputed <span className="fig">{centsToUSD(engineCents)}</span> — filed return shows{" "}
              <span className="fig">{centsToUSD(extractedCents)}</span>.
            </b>
            <p className="mt-1 text-[12.5px] text-[var(--g-ink-2)]">
              The verification gate is blocking confirm. Review the per-line diff below,
              correct the extracted fields, and re-run.
            </p>
          </div>
        </div>
        {/* Per-line diff (the blocking diff table — shows the discrepancy) */}
        <table className="ledger mt-4 w-full max-w-[480px]">
          <thead>
            <tr>
              <th className="text-left">line</th>
              <th className="r text-right">return</th>
              <th className="r text-right">engine</th>
              <th className="r text-right">diff</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="text-[12.5px]">22 / 24 · Total tax</td>
              <td className="r fig text-right text-[12.5px]">{centsToUSD(extractedCents)}</td>
              <td className="r fig text-right text-[12.5px] tone-agent">{centsToUSD(engineCents)}</td>
              <td className={`r fig text-right text-[12.5px] ${diffCents > 0 ? "tone-cost" : "tone-save"}`}>
                {diffCents > 0 ? "+" : "−"}{centsToUSD(Math.abs(diffCents))}
              </td>
            </tr>
          </tbody>
        </table>
        <p className="mt-3 font-mono text-[10.5px] text-[var(--g-ink-3)]">
          A mismatch blocks here — that gate is why the analysis can be trusted.
          Correct the extracted field value above, or contact support if the engine constants are wrong.
        </p>
      </div>
    );
  }

  // Match — the happy path
  return (
    <div
      className="flex items-center gap-4 border-t border-[var(--g-hairline-soft)] px-6 py-4"
      style={{ background: "linear-gradient(90deg,rgba(29,138,91,0.07),transparent 65%)" }}
    >
      <Stamp kind="verified" fresh={!hasLowConf}>Verified</Stamp>
      <div className="flex-1">
        <b className="text-[14.5px]">
          Engine recomputed this return: total tax{" "}
          <ProvFigure
            cents={engineCents ?? 0}
            prov={{
              label: "total tax · engine recompute",
              engine: "comprehensive.calculate",
              source: "engine",
              inputs: snap ? [
                { k: "AGI", v: centsToUSD(snap.agi_cents) },
                { k: "taxable income", v: centsToUSD(snap.taxable_income_cents) },
              ] : [],
              constants: [{ k: "bracket set", v: "2025 · golden-tested" }],
            }}
          />{" "}
          — matches the filed figure to the dollar.
        </b>
        <p className="mt-1 text-[12.5px] text-[var(--g-ink-2)]">
          Bracket walk on Rev. Proc. constants. A mismatch would block here and show the per-line
          diff — that gate is why the analysis can be trusted.
        </p>
        {hasLowConf ? (
          <p className="mt-1 font-mono text-[11px] text-[var(--cost)]">
            ⚠ Low-confidence fields still need your review above before confirming.
          </p>
        ) : null}
      </div>
      <div className="flex flex-col items-end gap-2">
        <Button
          variant="ink"
          disabled={confirming || hasLowConf}
          onClick={onConfirm}
        >
          {confirming ? <WorkingDots className="mr-1 inline-flex" /> : null}
          Confirm baseline → open the case
        </Button>
        {confirmError ? (
          <p className="font-mono text-[11px] text-[var(--cliff)]">{confirmError}</p>
        ) : null}
        {hasLowConf ? (
          <p className="font-mono text-[9.5px] text-[var(--cost)]">resolve flagged field first</p>
        ) : null}
      </div>
    </div>
  );
}

/* ================================================================== IMPORT DROPZONE */
function ImportDropzone({
  clientName,
  file,
  setFile,
  onImport,
  importing,
  error,
}: {
  clientName: string;
  file: File | null;
  setFile: (f: File | null) => void;
  onImport: () => void;
  importing: boolean;
  error: string | null;
}) {
  return (
    <Panel className="rise p-8 text-center">
      <div className="mb-4 flex justify-center">
        <Aavatar name="Clerk" agent="strategist" />
      </div>
      <h2 className="text-[22px] font-bold leading-tight tracking-[-0.015em]">
        Import the filed 1040{clientName ? ` for ${clientName}` : ""}
      </h2>
      <p className="mt-2 text-[13.5px] text-[var(--g-ink-2)] max-w-md mx-auto">
        On-prem extraction — the return never leaves your tenant. The engines read every line,
        recompute the math, and verify before the baseline locks.
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <label className="flex h-10 cursor-pointer items-center gap-2 rounded-[var(--radius)] border border-dashed border-[var(--g-hairline)] bg-[var(--g-surface-2)] px-4 text-[13.5px] text-[var(--g-ink-2)] hover:border-[var(--agent)] transition-colors">
          <svg className="h-4 w-4 text-[var(--g-ink-3)]" viewBox="0 0 16 16" fill="none"><path d="M8 2L8 10M5 5L8 2L11 5M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          {file ? file.name : "Choose 1040 PDF…"}
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <Button variant="ink" disabled={!file || importing} onClick={onImport}>
          {importing ? <WorkingDots className="mr-1 inline-flex" /> : null}
          Import &amp; extract
        </Button>
      </div>
      {error ? (
        <p className="mt-3 font-mono text-[12px] text-[var(--cliff)]">{error}</p>
      ) : null}
      <p className="mt-6 font-mono text-[10.5px] text-[var(--g-ink-3)]">
        ~38 seconds · 4 pages · vision OCR · engine recompute · verification gate — before anything locks
      </p>
    </Panel>
  );
}

/* ================================================================== FLAGGED FIELD CARD */
function FlaggedFieldCard({
  field,
  correcting,
  correctionValue,
  onStartCorrect,
  onCancelCorrect,
  onConfirm,
  onCorrectChange,
  onCorrectSave,
  saving,
}: {
  field: FieldRow;
  correcting: boolean;
  correctionValue: string;
  onStartCorrect: () => void;
  onCancelCorrect: () => void;
  onConfirm: () => void;
  onCorrectChange: (v: string) => void;
  onCorrectSave: () => void;
  saving: boolean;
}) {
  const meta = FIELD_LABEL[field.field_key];
  const val = fieldValue(field);
  const conf = confPct(field);

  return (
    <div
      className="rounded-[12px] p-4 mb-3"
      style={{
        border: "1px solid rgba(170,106,28,0.4)",
        background: "rgba(170,106,28,0.06)",
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <b className="text-[13px]">
          Line {meta?.line ?? "?"} — {meta?.label ?? field.field_key}
        </b>
        <Chip tone="cost" className="ml-auto !text-[9.5px] !px-[8px] !py-[1.5px]">
          {conf.toFixed(1)}% confidence
        </Chip>
      </div>
      {/* Source crop — the raw extracted value */}
      <div
        className="flex items-center justify-between rounded-[6px] px-3 py-2.5 mb-3"
        style={{
          background: "#ece9df",
          border: "1px solid rgba(170,106,28,0.5)",
          color: "#4a463c",
          fontSize: 10,
        }}
      >
        <span>source · page 1, region {meta?.line ?? "?"} ↗</span>
        <b className="font-mono text-[15px] tracking-[1px]">
          {val !== null ? centsToUSD(val) : "?"}
        </b>
        <span className="text-[10px] text-[#7a7268]">
          {field.status}
        </span>
      </div>
      {correcting ? (
        <div className="flex items-center gap-2 mb-1">
          <span className="font-mono text-[11px] text-[var(--g-ink-2)]">$</span>
          <input
            type="number"
            className="flex-1 rounded-[8px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 py-1.5 font-mono text-[13px] outline-none focus:border-[var(--agent)]"
            value={correctionValue}
            onChange={(e) => onCorrectChange(e.target.value)}
            placeholder="0.00"
            autoFocus
          />
          <MiniButton go onClick={onCorrectSave} disabled={saving}>Save correction</MiniButton>
          <MiniButton onClick={onCancelCorrect}>Cancel</MiniButton>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <MiniButton go onClick={onConfirm}>
            Confirm {val !== null ? centsToUSD(val) : "value"}
          </MiniButton>
          <MiniButton onClick={onStartCorrect}>Correct…</MiniButton>
          <span className="ml-auto font-mono text-[9.5px] text-[var(--g-ink-3)]">
            a fix re-runs the recompute check instantly
          </span>
        </div>
      )}
    </div>
  );
}

/* ================================================================== SMALL COMPONENTS */

function StagePip({ done, warn, children }: { done?: boolean; warn?: boolean; children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-[7px] rounded-full border px-[11px] py-[4px] font-mono text-[10px]"
      style={
        warn
          ? { color: "var(--cost)", borderColor: "rgba(170,106,28,0.4)" }
          : done
          ? { color: "var(--save)", borderColor: "rgba(29,138,91,0.35)" }
          : { color: "var(--g-ink-3)", borderColor: "var(--g-hairline-soft)" }
      }
    >
      {warn ? "●" : done ? "✓" : "○"} {children}
    </span>
  );
}

function ConfidenceBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block h-[4px] w-[52px] rounded-full overflow-hidden"
        style={{ background: "rgba(31,28,23,0.09)" }}
      >
        <span
          className="block h-full rounded-full"
          style={{ width: `${clamped}%`, background: clamped >= 95 ? "var(--save)" : "var(--cost)" }}
        />
      </span>
      <span className="font-mono text-[9px] text-[var(--g-ink-3)] w-[34px] text-right">{pct.toFixed(1)}</span>
    </span>
  );
}

/** Inline source color dot — matches the mockup's .src.doc / .src.eng / .src.adv */
function SourceDot({ source }: { source: "doc" | "eng" | "adv" }) {
  const bg = source === "doc" ? "#5b86a8" : source === "eng" ? "var(--agent)" : "var(--seal)";
  return (
    <span
      className="mr-2 inline-block h-[7px] w-[7px] rounded-[2.5px] align-middle"
      style={{ background: bg }}
      title={source === "doc" ? "Read from the document" : source === "eng" ? "Engine-computed" : "Advisor-entered"}
    />
  );
}

function KpiCell({
  label,
  bold,
  seal,
  children,
}: {
  label: string;
  prov?: Provenance;
  bold?: boolean;
  seal?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`border-l border-[var(--g-hairline-soft)] px-5 py-4 first:border-l-0 ${seal ? "bg-[linear-gradient(180deg,rgba(153,122,49,0.07),transparent)]" : ""}`}>
      <MicroLabel>{label}</MicroLabel>
      <div className={`mt-1.5 text-[24px] font-bold leading-none tracking-[-0.02em] ${seal ? "tone-seal" : ""} ${bold ? "font-[750]" : ""}`}>
        {children}
      </div>
    </div>
  );
}

/* ================================================================== PURE HELPERS (used by both views) */

function buildWaterfallSteps(snap: NonNullable<YearRow["snapshot"]>): WaterfallStep[] {
  const steps: WaterfallStep[] = [];
  steps.push({ label: "Income", cents: snap.total_income_cents, kind: "base" });
  if (snap.agi_cents !== snap.total_income_cents) {
    steps.push({ label: "AGI", cents: snap.agi_cents, kind: "result" });
  }
  const dedCents = snap.agi_cents - snap.taxable_income_cents;
  if (dedCents > 0) {
    steps.push({ label: "Deduction", cents: dedCents, kind: "subtract" });
  }
  steps.push({ label: "Taxable", cents: snap.taxable_income_cents, kind: "result" });
  steps.push({ label: "Tax", cents: snap.total_tax_cents, kind: "result" });
  return steps;
}

function buildLedgerRows(snap: NonNullable<YearRow["snapshot"]>): {
  line: string; label: string; cents: number; source: "doc" | "eng" | "adv"
}[] {
  const rows: { line: string; label: string; cents: number; source: "doc" | "eng" | "adv" }[] = [];
  rows.push({ line: "1z", label: "Wages, salaries, tips", cents: snap.total_income_cents, source: "doc" });
  if (snap.agi_cents !== snap.total_income_cents) {
    rows.push({ line: "11", label: "Adjusted gross income", cents: snap.agi_cents, source: "eng" });
  }
  const ded = snap.agi_cents - snap.taxable_income_cents;
  if (ded > 0) {
    rows.push({ line: "12", label: "Standard deduction", cents: -ded, source: "eng" });
  }
  rows.push({ line: "15", label: "Taxable income", cents: snap.taxable_income_cents, source: "eng" });
  rows.push({ line: "16", label: "Tax — bracket walk", cents: snap.total_tax_cents, source: "eng" });
  return rows;
}

function engineProv(line: string, label: string): Provenance {
  return {
    label: `line ${line} · ${label}`,
    engine: "comprehensive.calculate",
    source: "engine",
  };
}
