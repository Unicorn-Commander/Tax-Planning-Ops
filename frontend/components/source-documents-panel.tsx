"use client";

// Source Documents panel — the OCR'd income/source forms synced from
// Accounting-Ops for a client's tax year (1099-R, SSA-1099, 1095-B, W-2, K-1,
// IRS / state notices). Fed entirely by:
//   GET  /clients/tax-years/:id/tax-documents     — the manifest (link state + docs)
//   POST /clients/tax-years/:id/sync-tax-documents — (re)pull from AO
//
// HARD INVARIANT (Honesty Protocol): a document's `fields` are the form's
// VERBATIM labeled box values as the extractor read them. We display them as-is
// — a value of the literal string "UNKNOWN" is shown as "UNKNOWN", never
// computed, never inferred. The LLM / this component is never a source; the
// source class on every figure here is `document` (the blue ¶ mark).

import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import api from "@/lib/api";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Stamp,
  MiniButton,
  WorkingDots,
  Aavatar,
  Term,
  SourceMark,
} from "@/components/kit";

/* ======================================================== wire shapes ======= */

interface TaxDocument {
  id: string;
  entity_id: string | null;
  receipt_id: string | null;
  doc_type: string;
  tax_year: number | null;
  payer_name: string | null;
  recipient_name: string | null;
  /** the form's verbatim labeled box values, e.g. {"1 Gross distribution": "39612.00"} */
  fields: Record<string, string> | null;
  confidence: number | null;
  status: string;
  model: string | null;
  extracted_at: string | null;
}

interface TaxDocumentManifest {
  tax_year_id: string;
  tax_year: number | null;
  linked: boolean;
  accounting_ops_workspace_id: string | null;
  accounting_ops_entity_id: string | null;
  synced_at: string | null;
  documents: TaxDocument[];
}

interface SyncResult {
  document_count: number;
  by_doc_type?: Record<string, number> | null;
  synced_at: string | null;
}

/* ======================================================== doc-type display === */

// A friendly label for the prominent form-type badge. Unknown types fall back to
// the raw code (uppercased), so a new form the extractor learns still renders.
const DOC_TYPE_LABEL: Record<string, string> = {
  "1099-R": "1099-R · retirement distribution",
  "1099-r": "1099-R · retirement distribution",
  "ssa-1099": "SSA-1099 · Social Security benefits",
  "SSA-1099": "SSA-1099 · Social Security benefits",
  "1095-B": "1095-B · health coverage",
  "1095-b": "1095-B · health coverage",
  "1095-A": "1095-A · marketplace coverage",
  "1095-a": "1095-A · marketplace coverage",
  "W-2": "W-2 · wages",
  "w-2": "W-2 · wages",
  "w2": "W-2 · wages",
  "K-1": "K-1 · pass-through",
  "k-1": "K-1 · pass-through",
  "1099-INT": "1099-INT · interest",
  "1099-int": "1099-INT · interest",
  "1099-DIV": "1099-DIV · dividends",
  "1099-div": "1099-DIV · dividends",
  "1099-NEC": "1099-NEC · nonemployee comp.",
  "1099-nec": "1099-NEC · nonemployee comp.",
  "1099-MISC": "1099-MISC",
  "1099-misc": "1099-MISC",
  notice: "IRS / state notice",
  irs_notice: "IRS notice",
  state_notice: "state notice",
};

function docTypeLabel(docType: string): string {
  return DOC_TYPE_LABEL[docType] ?? docType.toUpperCase();
}

// The short, prominent badge text (just the form code, not the descriptor).
function docTypeBadge(docType: string): string {
  const label = DOC_TYPE_LABEL[docType];
  if (label) return label.split(" · ")[0];
  return docType.toUpperCase();
}

/* ======================================================== field selection ====
   Which of a document's many verbatim box values to surface (compact view). We
   match labels loosely (the extractor's labels carry the box number + name,
   e.g. "1 Gross distribution") because the exact prefix varies by form vintage.
   We NEVER rename or recompute a value — only choose which labeled pairs to show
   and in what order; the label + value are the extractor's, rendered as-is. */

function normLabel(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

/** Pick the first field whose normalized label contains all of `needles`. */
function pickField(
  fields: Record<string, string>,
  needles: string[],
): { label: string; value: string } | null {
  for (const [label, value] of Object.entries(fields)) {
    const n = normLabel(label);
    if (needles.every((needle) => n.includes(needle))) {
      return { label, value };
    }
  }
  return null;
}

interface ShownField {
  label: string;
  value: string;
}

/**
 * The relevant fields for a document, in display order. Form-specific picks for
 * the common income forms; otherwise the first ~5 fields in the order the
 * extractor returned them. Returns the verbatim {label, value} pairs.
 */
function relevantFields(doc: TaxDocument): ShownField[] {
  const fields = doc.fields ?? {};
  const entries = Object.entries(fields);
  if (entries.length === 0) return [];

  const dt = doc.doc_type.toLowerCase();
  const seen = new Set<string>();
  const out: ShownField[] = [];
  const take = (f: { label: string; value: string } | null) => {
    if (f && !seen.has(f.label)) {
      seen.add(f.label);
      out.push(f);
    }
  };

  if (dt.includes("1099-r") || dt === "1099r") {
    take(pickField(fields, ["gross", "distribution"]));
    take(pickField(fields, ["taxable", "amount"]));
    take(pickField(fields, ["federal", "withheld"]) ?? pickField(fields, ["tax", "withheld"]));
    take(pickField(fields, ["distribution", "code"]));
  } else if (dt.includes("ssa")) {
    take(pickField(fields, ["net", "benefit"]) ?? pickField(fields, ["benefits"]));
    take(pickField(fields, ["voluntary", "withholding"]) ?? pickField(fields, ["withheld"]));
  } else if (dt.includes("1095")) {
    take(pickField(fields, ["coverage"]) ?? pickField(fields, ["covered"]));
    take(pickField(fields, ["months"]));
  } else if (dt.includes("w-2") || dt === "w2") {
    take(pickField(fields, ["wages"]) ?? pickField(fields, ["box 1"]));
    take(pickField(fields, ["federal", "withheld"]));
    take(pickField(fields, ["social", "security", "wages"]));
    take(pickField(fields, ["medicare", "wages"]));
  } else if (dt.includes("1099-int")) {
    take(pickField(fields, ["interest", "income"]));
    take(pickField(fields, ["federal", "withheld"]));
  } else if (dt.includes("1099-div")) {
    take(pickField(fields, ["ordinary", "dividends"]) ?? pickField(fields, ["total", "dividends"]));
    take(pickField(fields, ["qualified", "dividends"]));
    take(pickField(fields, ["capital", "gain"]));
  }

  // Fill the rest (or the whole list for un-specialized forms) from the
  // extractor's own order, up to ~5 fields total.
  for (const [label, value] of entries) {
    if (out.length >= 5) break;
    if (!seen.has(label)) {
      seen.add(label);
      out.push({ label, value });
    }
  }
  return out.slice(0, 5);
}

/* ======================================================== confidence ========= */

function confPct(confidence: number | null): number | null {
  if (confidence === null || confidence === undefined) return null;
  const n = Number(confidence);
  if (!Number.isFinite(n)) return null;
  return n > 1 ? n : n * 100; // tolerate 0-1 float or 0-100
}

/* ======================================================== component ========= */

export function SourceDocumentsPanel({ taxYearId }: { taxYearId: string }) {
  const [data, setData] = useState<TaxDocumentManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncNote, setSyncNote] = useState<string | null>(null);

  const load = useCallback(() => {
    let live = true;
    setLoading(true);
    setLoadError(false);
    api
      .get<TaxDocumentManifest>(`/clients/tax-years/${taxYearId}/tax-documents`)
      .then((r) => {
        if (live) setData(r.data);
      })
      .catch(() => {
        if (live) setLoadError(true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [taxYearId]);

  useEffect(() => load(), [load]);

  // (Re)sync from Accounting-Ops, then re-fetch the manifest. The POST can
  // legitimately return 503 (integration off), 502 (AO unreachable / not yet
  // authorized), or 400 (client not linked) — surface a friendly inline message
  // rather than crash, and never leave the spinner stuck.
  const sync = useCallback(async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncNote(null);
    try {
      const r = await api.post<SyncResult>(`/clients/tax-years/${taxYearId}/sync-tax-documents`);
      const res = r.data;
      const n = res?.document_count ?? 0;
      const parts = res?.by_doc_type
        ? Object.entries(res.by_doc_type)
            .map(([k, v]) => `${v} ${k}`)
            .join(" · ")
        : "";
      setSyncNote(
        n === 0
          ? "Accounting-Ops returned no source documents for this year yet."
          : `Synced ${n} document${n === 1 ? "" : "s"}${parts ? ` — ${parts}` : ""}.`,
      );
      // Re-fetch the manifest so the freshly-synced docs + synced_at render.
      api
        .get<TaxDocumentManifest>(`/clients/tax-years/${taxYearId}/tax-documents`)
        .then((rr) => setData(rr.data))
        .catch(() => setLoadError(true));
    } catch (err) {
      setSyncError(syncErrorMessage(err));
    } finally {
      setSyncing(false);
    }
  }, [taxYearId]);

  /* ---- loading ---- */
  if (loading) {
    return (
      <Panel className="rise mt-[22px] p-5">
        <div className="skeleton h-[220px] w-full rounded-[10px]" />
      </Panel>
    );
  }

  /* ---- couldn't load the manifest ---- */
  if (loadError || !data) {
    return (
      <Panel className="rise mt-[22px] px-5 py-8 text-center">
        <p className="text-[13px] text-[var(--g-ink-2)]">
          Couldn&apos;t load the source documents from Accounting-Ops.
        </p>
        <p className="mt-1 text-[12px] text-[var(--g-ink-3)]">
          The tax-documents endpoint didn&apos;t respond — retry the sync below.
        </p>
        <div className="mt-3 flex justify-center">
          <SyncButton syncing={syncing} onClick={() => void sync()} />
        </div>
        {syncError ? <InlineError className="mt-2">{syncError}</InlineError> : null}
      </Panel>
    );
  }

  const docs = data.documents ?? [];
  const linked = data.linked;

  return (
    <Panel className="rise mt-[22px]">
      <PanelHead>
        <MicroLabel>
          <Term
            term="Source documents"
            gloss="The income & coverage forms (1099-R, SSA-1099, 1095-B, W-2, K-1, notices) read off the client's documents and pulled in from Accounting-Ops."
          >
            Source documents
          </Term>{" "}
          · the income &amp; coverage forms, from the books
        </MicroLabel>
        {linked ? (
          <Stamp kind="verified" className="ml-auto !transform-none !text-[9px]">
            Accounting-Ops
          </Stamp>
        ) : (
          <Chip tone="cost" className="ml-auto !text-[10px]">
            not linked
          </Chip>
        )}
      </PanelHead>

      {/* ---- link + freshness status strip ---- */}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[var(--g-hairline-soft)] px-5 py-3">
        <Annotation>
          {data.tax_year ? `${data.tax_year} · ` : ""}
          {linked
            ? `${docs.length} document${docs.length === 1 ? "" : "s"} on file`
            : "no Accounting-Ops link"}
        </Annotation>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[10.5px] text-[var(--g-ink-3)]">
            {data.synced_at
              ? `synced ${new Date(data.synced_at).toLocaleString()}`
              : "never synced"}
          </span>
          <SyncButton syncing={syncing} onClick={() => void sync()} />
        </span>
      </div>

      {/* ---- sync feedback (success note OR friendly error) ---- */}
      {syncError ? (
        <div className="px-5 pt-3">
          <InlineError>{syncError}</InlineError>
        </div>
      ) : syncNote ? (
        <div className="px-5 pt-3">
          <p className="rounded-[8px] border border-[var(--g-hairline-soft)] bg-[var(--wash)] px-3 py-2 text-[11.5px] text-[var(--g-ink-2)]">
            {syncNote}
          </p>
        </div>
      ) : null}

      {/* ---- body: not-linked hint / empty / the document cards ---- */}
      {!linked ? (
        <div className="px-5 py-8 text-center">
          <Aavatar name="Bookrunner" agent="bookrunner" idle className="mx-auto mb-2" />
          <p className="text-[13px] text-[var(--g-ink-2)]">
            This client isn&apos;t linked to an Accounting-Ops workspace yet.
          </p>
          <p className="mx-auto mt-1 max-w-md text-[12px] text-[var(--g-ink-3)]">
            Link the client to its Accounting-Ops workspace, then sync to pull the OCR&apos;d
            source forms (1099-R, SSA-1099, 1095-B, W-2, K-1, notices) for this tax year.
          </p>
        </div>
      ) : docs.length === 0 ? (
        <div className="px-5 py-8 text-center">
          <p className="text-[13px] text-[var(--g-ink-2)]">
            {data.synced_at
              ? "No source documents on file for this tax year."
              : "No source documents synced yet."}
          </p>
          <p className="mx-auto mt-1 max-w-md text-[12px] text-[var(--g-ink-3)]">
            {data.synced_at
              ? "Accounting-Ops has no OCR'd source forms recorded for this year. Re-sync after the documents are uploaded there."
              : "Sync from Accounting-Ops to pull the income & coverage forms for this year."}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-[var(--g-hairline-soft)]">
          {docs.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} />
          ))}
        </div>
      )}

      <p className="border-t border-[var(--g-hairline-soft)] px-5 py-3 font-mono text-[10.5px] leading-relaxed text-[var(--g-ink-3)]">
        <SourceMark source="document" /> every value is the form&apos;s verbatim box reading from the
        document — shown exactly as extracted (a value of &ldquo;UNKNOWN&rdquo; is the extractor&apos;s,
        never computed here).
      </p>
    </Panel>
  );
}

/* ================================================================ sub-components */

function SyncButton({ syncing, onClick }: { syncing: boolean; onClick: () => void }) {
  return (
    <MiniButton go onClick={onClick} disabled={syncing}>
      {syncing ? <WorkingDots className="mr-1 inline-flex" /> : null}
      {syncing ? "Syncing…" : "Sync from Accounting-Ops"}
    </MiniButton>
  );
}

function InlineError({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p
      className={`rounded-[8px] border px-3 py-2 text-[11.5px] leading-relaxed ${className ?? ""}`}
      style={{ borderColor: "rgba(170,106,28,0.4)", background: "rgba(170,106,28,0.06)", color: "var(--cost)" }}
    >
      {children}
    </p>
  );
}

function DocumentRow({ doc }: { doc: TaxDocument }) {
  const fields = relevantFields(doc);
  const conf = confPct(doc.confidence);
  const failed = doc.status === "failed";
  const totalFields = doc.fields ? Object.keys(doc.fields).length : 0;
  const hidden = Math.max(0, totalFields - fields.length);

  return (
    <div className="px-5 py-4">
      {/* header row: form type + tax year + status + confidence */}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="text-[14.5px] font-bold leading-none tracking-[-0.01em]">
          {docTypeBadge(doc.doc_type)}
          <SourceMark source="document" title={`From the document · ${docTypeLabel(doc.doc_type)}`} />
        </span>
        {doc.tax_year ? (
          <Chip tone="neutral" className="!text-[10px]">
            {doc.tax_year}
          </Chip>
        ) : null}
        {failed ? (
          <Stamp kind="flag" className="!text-[9px]">
            extraction failed
          </Stamp>
        ) : null}
        <span className="ml-auto flex items-center gap-2.5">
          {conf !== null ? (
            <span
              className="font-mono text-[10px]"
              style={{ color: conf >= 95 ? "var(--save)" : conf >= 80 ? "var(--g-ink-3)" : "var(--cost)" }}
              title="extraction confidence"
            >
              {conf.toFixed(0)}% conf.
            </span>
          ) : null}
          {doc.status && !failed ? (
            <span className="font-mono text-[10px] text-[var(--g-ink-3)]">{doc.status}</span>
          ) : null}
        </span>
      </div>

      {/* payer → recipient line */}
      {doc.payer_name || doc.recipient_name ? (
        <div className="mt-1 text-[12px] text-[var(--g-ink-2)]">
          {doc.payer_name ? <span className="font-medium text-[var(--g-ink)]">{doc.payer_name}</span> : null}
          {doc.payer_name && doc.recipient_name ? (
            <span className="text-[var(--g-ink-3)]"> → </span>
          ) : null}
          {doc.recipient_name ? <span>{doc.recipient_name}</span> : null}
        </div>
      ) : null}

      {/* the relevant verbatim box values */}
      {fields.length > 0 ? (
        <div className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {fields.map((f) => (
            <FieldPair key={f.label} label={f.label} value={f.value} />
          ))}
        </div>
      ) : failed ? (
        <p className="mt-2 text-[12px] text-[var(--cost)]">
          The extractor couldn&apos;t read this form — re-sync after a clean scan is uploaded to
          Accounting-Ops.
        </p>
      ) : (
        <p className="mt-2 font-mono text-[11px] text-[var(--g-ink-3)]">no labeled fields extracted</p>
      )}

      {/* footer: hidden-field count + extracted-at + model */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px] text-[var(--g-ink-3)]">
        {hidden > 0 ? <span>+ {hidden} more field{hidden === 1 ? "" : "s"} on the form</span> : null}
        {doc.extracted_at ? (
          <span className="ml-auto">extracted {new Date(doc.extracted_at).toLocaleDateString()}</span>
        ) : null}
        {doc.model ? <span>· {doc.model}</span> : null}
      </div>
    </div>
  );
}

/** One verbatim label → value pair. Both are shown exactly as the extractor read
    them; a literal "UNKNOWN" value is rendered as-is (dimmed, never computed). */
function FieldPair({ label, value }: { label: string; value: string }) {
  const isUnknown = value.trim().toUpperCase() === "UNKNOWN";
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dotted border-[var(--g-hairline-soft)] pb-1">
      <span className="text-[12px] text-[var(--g-ink-2)]">{label}</span>
      <span
        className={`shrink-0 font-mono text-[12px] ${isUnknown ? "text-[var(--g-ink-3)] italic" : "text-[var(--g-ink)]"}`}
        title={isUnknown ? "the extractor could not read this box" : undefined}
      >
        {value}
      </span>
    </div>
  );
}

/* ======================================================== error mapping ======
   Map the sync POST's documented failure modes to a friendly, specific inline
   message. 503 = integration disabled · 502 = AO unreachable / not yet
   authorized · 400 = client not linked. Anything else → a generic note. */
function syncErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const status = err.response?.status;
    const detail =
      (err.response?.data as { detail?: string; message?: string } | undefined)?.detail ??
      (err.response?.data as { detail?: string; message?: string } | undefined)?.message;
    if (status === 503) {
      return (
        detail ??
        "The Accounting-Ops integration is turned off for this tenant — no documents can be synced right now."
      );
    }
    if (status === 502) {
      return (
        detail ??
        "Accounting-Ops is unreachable or this link isn't authorized yet. Confirm the connection, then try again."
      );
    }
    if (status === 400) {
      return (
        detail ??
        "This client isn't linked to an Accounting-Ops workspace yet — link it before syncing."
      );
    }
    if (detail) return detail;
  }
  return "Couldn't sync from Accounting-Ops just now. Please try again.";
}
