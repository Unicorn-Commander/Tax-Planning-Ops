"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Library, Plus, Palette, SlidersHorizontal, ArrowRight } from "lucide-react";
import api from "@/lib/api";
import { useAction } from "@/lib/useAction";
import { Card, CardHeader, Badge, Button, Field, Input, Skeleton, EmptyState, PageHeader } from "@/components/ui";

interface Strategy { id: string; name: string; category: string; client_facing_copy: string; is_active: boolean }
const CATS = ["retirement", "charitable", "entity", "health", "investment", "other"];

export default function AdminPage() {
  const [items, setItems] = useState<Strategy[] | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "retirement", description: "", client_facing_copy: "" });

  function load() { api.get("/strategy-library").then((r) => setItems(r.data)).catch(() => setItems([])); }
  useEffect(load, []);

  const create = useAction(async () => {
    await api.put("/admin/strategy-library", { ...form, savings_method: "amount_x_effective_rate", is_active: true });
    setOpen(false); setForm({ name: "", category: "retirement", description: "", client_facing_copy: "" }); load();
  });

  return (
    <div className="animate-in">
      <PageHeader
        eyebrow="Admin"
        title="Strategy library"
        subtitle="Curate the strategies advisors select from — firm-editable, no vendor release required."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New strategy</Button>}
      />

      <Link href="/admin/brackets" className="mb-6 block">
        <Card className="flex items-center justify-between p-4 transition-colors hover:bg-surface-2">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] bg-primary-soft text-primary"><SlidersHorizontal className="h-4 w-4" /></span>
            <div><div className="text-[14px] font-medium text-ink">Tax tables &amp; constants</div><div className="text-[12.5px] text-muted">Brackets, deductions, thresholds — editable per year</div></div>
          </div>
          <ArrowRight className="h-4 w-4 text-muted" />
        </Card>
      </Link>

      <Card>
        <CardHeader title="Strategies" subtitle={items ? `${items.length} in library` : undefined} action={<Library className="h-4 w-4 text-muted" />} />
        {items === null ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)}</div>
        ) : items.length === 0 ? (
          <div className="p-6"><EmptyState icon={<Plus className="h-5 w-5" />} title="No strategies yet" body="Add your first strategy to the library." /></div>
        ) : (
          <div className="divide-y divide-line-2">
            {items.map((s) => (
              <div key={s.id} className="flex items-start justify-between gap-3 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2"><span className="text-[14px] font-medium text-ink">{s.name}</span><Badge tone="neutral">{s.category}</Badge></div>
                  <p className="mt-0.5 text-[13px] text-muted">{s.client_facing_copy}</p>
                </div>
                <Badge tone={s.is_active ? "positive" : "neutral"}>{s.is_active ? "active" : "inactive"}</Badge>
              </div>
            ))}
          </div>
        )}
      </Card>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <Card className="w-full max-w-lg animate-in p-0" onClick={(e) => e.stopPropagation()}>
            <CardHeader title="New strategy" action={<Palette className="h-4 w-4 text-muted" />} />
            <div className="space-y-4 p-5">
              <Field label="Name"><Input autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Mega Backdoor Roth" /></Field>
              <Field label="Category">
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] outline-none focus:border-primary">
                  {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
              <Field label="Advisor description"><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Internal description" /></Field>
              <Field label="Client-facing copy"><Input value={form.client_facing_copy} onChange={(e) => setForm({ ...form, client_facing_copy: e.target.value })} placeholder="Plain-language summary for the PDF" /></Field>
              {create.error ? <p className="text-[13px] text-negative">{create.error}</p> : null}
            </div>
            <div className="flex justify-end gap-2 border-t border-line-2 px-5 py-4">
              <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
              <Button loading={create.pending} disabled={!form.name.trim() || !form.description.trim() || !form.client_facing_copy.trim()} onClick={() => void create.run()}>Add to library</Button>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
