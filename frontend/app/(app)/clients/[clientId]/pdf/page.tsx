"use client";

import { useState } from "react";
import Link from "next/link";
import { FileText, Sparkles, CheckCircle2, GitCompareArrows } from "lucide-react";
import api from "@/lib/api";
import { useAction } from "@/lib/useAction";
import { useClientOverview } from "@/components/client-overview";
import { Card, CardHeader, Button, Field, Input, EmptyState, Disclaimer, Badge } from "@/components/ui";

interface PlanDoc { id: string; version: number; garage_key: string; payload_hash: string }

export default function PdfTab() {
  const { overview, loading } = useClientOverview();
  const [firmName, setFirmName] = useState("Northstar Tax Advisory");
  const [docs, setDocs] = useState<PlanDoc[]>([]);
  const planId = overview?.plan_year_id ?? null;

  const generate = useAction(async () => {
    if (!planId) return;
    await api.put("/admin/branding", { firm_name: firmName || "Tax Planning Firm", primary_color: "#4f46e5" });
    const r = await api.post(`/plans/${planId}/pdf`, {});
    setDocs((d) => [r.data, ...d]);
  });

  if (loading) return <div className="h-64 skeleton rounded-[var(--radius-card)]" />;
  if (!planId) {
    return <EmptyState icon={<GitCompareArrows className="h-5 w-5" />} title="No plan year yet"
      body="Create a plan on the Overview tab before generating the client PDF."
      action={<Link href={`/clients/${overview?.client.id}`}><Button>Go to overview</Button></Link>} />;
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr]">
      <Card className="overflow-hidden self-start">
        <div className="bg-gradient-to-br from-primary to-accent p-6 text-white">
          <Sparkles className="h-6 w-6" />
          <h3 className="mt-3 text-[17px] font-semibold">Client tax-plan PDF</h3>
          <p className="mt-1 text-[13px] leading-relaxed text-white/85">
            A branded, white-label deliverable: current-vs-next-year, strategies with the math shown,
            the quarterly schedule, and the mandatory planning disclaimer — stored encrypted, versioned, and audit-logged.
          </p>
        </div>
        <div className="space-y-4 p-5">
          <Field label="Firm name (cover branding)"><Input value={firmName} onChange={(e) => setFirmName(e.target.value)} /></Field>
          <Button className="w-full" icon={<FileText className="h-4 w-4" />} loading={generate.pending} onClick={() => void generate.run()}>Generate plan PDF</Button>
          {generate.error ? <p className="text-[13px] text-negative">{generate.error}</p> : null}
        </div>
      </Card>

      <Card className="self-start">
        <CardHeader title="Generated documents" subtitle="Each regeneration is a new immutable version" />
        <div className="divide-y divide-line-2">
          {docs.length === 0 ? (
            <div className="px-5 py-10 text-center text-[13.5px] text-muted">No documents generated yet.</div>
          ) : docs.map((d) => (
            <div key={d.id} className="flex items-center gap-3 px-5 py-4">
              <span className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] bg-positive-soft text-positive"><CheckCircle2 className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium text-ink">Tax plan · v{d.version}</div>
                <div className="truncate font-mono text-[11.5px] text-muted">{d.payload_hash.slice(0, 24)}…</div>
              </div>
              <Badge tone="positive">stored</Badge>
            </div>
          ))}
        </div>
        <Disclaimer className="border-t border-line-2 px-5 py-4" />
      </Card>
    </div>
  );
}
