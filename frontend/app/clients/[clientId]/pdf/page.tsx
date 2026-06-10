"use client";

import { useState } from "react";
import { FileDown } from "lucide-react";
import api from "@/lib/api";

export default function PdfPage() {
  const [planYearId, setPlanYearId] = useState("");
  const [firmName, setFirmName] = useState("");
  const [result, setResult] = useState<Record<string, string | number> | null>(null);

  async function saveBranding() {
    await api.put("/admin/branding", {
      firm_name: firmName || "Tax Planning Firm",
      primary_color: "#0f766e",
    });
  }

  async function generatePdf() {
    await saveBranding();
    const response = await api.post(`/plans/${planYearId}/pdf`);
    setResult(response.data);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <header className="mb-5">
        <h1 className="text-xl font-semibold">Client Plan PDF</h1>
        <p className="text-sm text-[var(--muted)]">
          Planning estimate only. Not a filed tax return and not tax advice.
        </p>
      </header>
      <section className="rounded-lg border border-[var(--line)] bg-white p-4">
        <label className="block text-sm">
          Firm name
          <input
            value={firmName}
            onChange={(event) => setFirmName(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3"
          />
        </label>
        <label className="mt-4 block text-sm">
          Plan tax year id
          <input
            value={planYearId}
            onChange={(event) => setPlanYearId(event.target.value)}
            className="mt-2 h-10 w-full rounded-md border border-[var(--line)] px-3 font-mono text-sm"
          />
        </label>
        <button
          type="button"
          onClick={generatePdf}
          className="mt-4 flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
        >
          <FileDown className="h-4 w-4" aria-hidden />
          Generate PDF
        </button>
      </section>
      {result ? (
        <pre className="mt-4 overflow-auto rounded-lg border border-[var(--line)] bg-white p-4 text-xs">
          {JSON.stringify(result, null, 2)}
        </pre>
      ) : null}
    </main>
  );
}
