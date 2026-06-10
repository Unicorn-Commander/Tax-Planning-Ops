"use client";

import { useState } from "react";
import { Upload, CheckCircle2 } from "lucide-react";
import api from "@/lib/api";

interface FieldRow {
  id: string;
  field_key: string;
  value_cents: number | null;
  confidence: number | null;
  status: string;
  corrected_value_cents: number | null;
}

interface ExtractedReturn {
  id: string;
  extraction_status: string;
  fields: FieldRow[];
}

const disclaimer =
  "Planning estimate only. Not a filed tax return and not tax advice. Figures are projections based on advisor-entered assumptions and editable bracket tables.";

export default function ReturnReviewPage() {
  const [taxYearId, setTaxYearId] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [extracted, setExtracted] = useState<ExtractedReturn | null>(null);
  const [message, setMessage] = useState("");

  async function uploadReturn() {
    if (!selectedFile || !taxYearId) return;
    const form = new FormData();
    form.set("file", selectedFile);
    const response = await api.post(
      `/client-tax-years/${taxYearId}/documents/form-1040`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    setExtracted(response.data);
  }

  async function correctField(fieldId: string, corrected: string) {
    const value = corrected === "" ? null : Number.parseInt(corrected, 10);
    const response = await api.patch(`/extracted-fields/${fieldId}`, {
      corrected_value_cents: value,
    });
    setExtracted((current) =>
      current
        ? {
            ...current,
            fields: current.fields.map((field) =>
              field.id === fieldId ? { ...field, ...response.data } : field,
            ),
          }
        : current,
    );
  }

  async function confirmReturn() {
    if (!extracted) return;
    const response = await api.post(`/extracted-returns/${extracted.id}/confirm`);
    setMessage(`Confirmed baseline. Total tax: $${(response.data.total_tax_cents / 100).toFixed(0)}`);
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">1040 Review</h1>
        <p className="text-sm text-[var(--muted)]">{disclaimer}</p>
      </header>

      <section className="grid gap-4 md:grid-cols-[320px_1fr]">
        <div className="rounded-lg border border-[var(--line)] bg-white p-4">
          <label className="block text-sm font-medium">Client tax year id</label>
          <input
            value={taxYearId}
            onChange={(event) => setTaxYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-sm"
          />
          <label className="mt-4 block text-sm font-medium">Form 1040 PDF</label>
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            className="mt-2 block w-full text-sm"
          />
          <button
            type="button"
            onClick={uploadReturn}
            className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
          >
            <Upload className="h-4 w-4" aria-hidden />
            Upload
          </button>
        </div>

        <div className="rounded-lg border border-[var(--line)] bg-white">
          <div className="flex items-center justify-between border-b border-[var(--line)] p-4">
            <div>
              <p className="text-sm text-[var(--muted)]">Extraction status</p>
              <p className="font-medium">{extracted?.extraction_status ?? "No return loaded"}</p>
            </div>
            <button
              type="button"
              onClick={confirmReturn}
              disabled={!extracted}
              className="flex h-10 items-center gap-2 rounded-md border border-[var(--line)] px-3 text-sm disabled:opacity-50"
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden />
              Confirm
            </button>
          </div>
          <div className="divide-y divide-[var(--line)]">
            {extracted?.fields.map((field) => (
              <div key={field.id} className="grid gap-3 p-4 md:grid-cols-[1fr_120px_160px]">
                <div>
                  <p className="font-mono text-sm">{field.field_key}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {field.status}
                    {field.corrected_value_cents !== null ? " · manual override" : ""}
                  </p>
                </div>
                <div className="text-sm">
                  <p>${((field.value_cents ?? 0) / 100).toFixed(0)}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {field.confidence === null ? "no confidence" : `${Math.round(field.confidence * 100)}%`}
                  </p>
                </div>
                <input
                  type="number"
                  placeholder="Override cents"
                  defaultValue={field.corrected_value_cents ?? ""}
                  onBlur={(event) => correctField(field.id, event.target.value)}
                  className="h-10 rounded-md border border-[var(--line)] px-3 text-sm"
                />
              </div>
            ))}
            {extracted && extracted.fields.length === 0 ? (
              <p className="p-4 text-sm text-[var(--muted)]">
                OCR is disabled or returned no fields. Use the API to add fields before confirming.
              </p>
            ) : null}
          </div>
        </div>
      </section>
      {message ? <p className="mt-4 text-sm font-medium">{message}</p> : null}
    </main>
  );
}
