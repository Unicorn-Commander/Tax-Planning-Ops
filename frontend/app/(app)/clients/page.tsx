"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Plus, X, ArrowUpRight } from "lucide-react";
import api from "@/lib/api";
import { centsToUSD, percent } from "@/lib/format";
import { useAction } from "@/lib/useAction";
import { Card, Badge, Input, Field, Button, Skeleton, EmptyState, PageHeader } from "@/components/ui";

interface Client { id: string; display_name: string; filing_status_default: string; primary_state: string | null; status: string }
interface ScanRow { client_id: string; tax_year: number; total_tax_cents: number; effective_rate: string }

const FILING = [
  { v: "single", l: "Single" }, { v: "mfj", l: "Married filing jointly" },
  { v: "mfs", l: "Married filing separately" }, { v: "hoh", l: "Head of household" }, { v: "qss", l: "Qualifying surviving spouse" },
];
const FILING_SHORT: Record<string, string> = { single: "Single", mfj: "MFJ", mfs: "MFS", hoh: "HoH", qss: "QSS" };
const initials = (n: string) => n.split(" ").map((s) => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();

export default function ClientsPage() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[] | null>(null);
  const [scan, setScan] = useState<ScanRow[]>([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ display_name: "", filing_status_default: "single", primary_state: "" });

  function load() {
    api.get("/clients").then((r) => setClients(r.data)).catch(() => setClients([]));
    api.get("/agents/scan-book").then((r) => setScan(r.data)).catch(() => setScan([]));
  }
  useEffect(load, []);

  const taxByClient = useMemo(() => {
    const m = new Map<string, ScanRow>();
    for (const r of scan) if (r.tax_year === 2025) m.set(r.client_id, r);
    return m;
  }, [scan]);

  const filtered = useMemo(
    () => (clients ?? []).filter((c) => c.display_name.toLowerCase().includes(q.toLowerCase())),
    [clients, q],
  );

  const create = useAction(async () => {
    const r = await api.post("/clients", {
      display_name: form.display_name,
      filing_status_default: form.filing_status_default,
      primary_state: form.primary_state || null,
      status: "active",
    });
    setOpen(false);
    setForm({ display_name: "", filing_status_default: "single", primary_state: "" });
    router.push(`/clients/${r.data.id}`);
  });

  return (
    <div className="animate-in">
      <PageHeader
        title="Clients"
        subtitle="Every household and entity you advise, with their current-year position."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New client</Button>}
      />

      <Card>
        <div className="flex items-center gap-3 border-b border-line-2 px-4 py-3">
          <Search className="h-4 w-4 text-muted" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search clients…"
            className="h-7 w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-muted"
          />
          <span className="shrink-0 text-[12px] text-muted">{filtered.length} of {clients?.length ?? 0}</span>
        </div>

        {clients === null ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<Plus className="h-5 w-5" />}
              title={q ? "No matching clients" : "No clients yet"}
              body={q ? "Try a different search." : "Add your first client to begin planning."}
              action={!q ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New client</Button> : undefined}
            />
          </div>
        ) : (
          <div className="divide-y divide-line-2">
            <div className="grid grid-cols-[1fr_120px_90px_140px_40px] gap-3 px-5 py-2.5 text-[11.5px] font-semibold uppercase tracking-wide text-muted">
              <span>Client</span><span>Filing</span><span>State</span><span className="text-right">2025 tax</span><span />
            </div>
            {filtered.map((c) => {
              const row = taxByClient.get(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() => router.push(`/clients/${c.id}`)}
                  className="grid w-full grid-cols-[1fr_120px_90px_140px_40px] items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-surface-2"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary-soft to-[#e7e9ff] text-[12.5px] font-semibold text-primary-strong">
                      {initials(c.display_name)}
                    </span>
                    <span className="truncate text-[14px] font-medium text-ink">{c.display_name}</span>
                  </div>
                  <div><Badge tone="neutral">{FILING_SHORT[c.filing_status_default] ?? c.filing_status_default}</Badge></div>
                  <div className="text-[13px] text-ink-2">{c.primary_state ?? "—"}</div>
                  <div className="text-right text-[14px] font-medium text-ink tabular">
                    {row ? centsToUSD(row.total_tax_cents) : <span className="text-muted">—</span>}
                    {row ? <div className="text-[11px] font-normal text-muted">{percent(row.effective_rate)} eff</div> : null}
                  </div>
                  <ArrowUpRight className="h-4 w-4 justify-self-end text-muted" aria-hidden />
                </button>
              );
            })}
          </div>
        )}
      </Card>

      {/* Create modal */}
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <Card className="w-full max-w-md animate-in p-0" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line-2 px-5 py-4">
              <h3 className="text-[16px] font-semibold text-ink">New client</h3>
              <button onClick={() => setOpen(false)} className="rounded-md p-1 text-muted hover:bg-surface-2"><X className="h-4 w-4" /></button>
            </div>
            <div className="space-y-4 p-5">
              <Field label="Name"><Input autoFocus value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="e.g. Marcus Webb" /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Filing status">
                  <select value={form.filing_status_default} onChange={(e) => setForm({ ...form, filing_status_default: e.target.value })}
                    className="h-10 w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 text-[14px] text-ink outline-none focus:border-primary">
                    {FILING.map((f) => <option key={f.v} value={f.v}>{f.l}</option>)}
                  </select>
                </Field>
                <Field label="State"><Input value={form.primary_state} onChange={(e) => setForm({ ...form, primary_state: e.target.value.toUpperCase().slice(0, 2) })} placeholder="CA" /></Field>
              </div>
              {create.error ? <p className="text-[13px] text-negative">{create.error}</p> : null}
            </div>
            <div className="flex justify-end gap-2 border-t border-line-2 px-5 py-4">
              <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
              <Button loading={create.pending} disabled={!form.display_name.trim()} onClick={() => void create.run()}>Create client</Button>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
