"use client";

import { useEffect, useState } from "react";
import { FileText, RefreshCcw } from "lucide-react";
import api from "@/lib/api";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";

interface Me {
  sub: string;
  workspace_id: string;
  scopes: string[];
}

const disclaimer =
  "Planning estimate only. Not a filed tax return and not tax advice. Figures are projections based on advisor-entered assumptions and editable bracket tables.";

export default function DashboardPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [health, setHealth] = useState<string>("checking");

  useEffect(() => {
    api
      .get("/healthz")
      .then(() => setHealth("healthy"))
      .catch(() => setHealth("unavailable"));
    api.get("/me").then((response) => setMe(response.data));
  }, []);

  return (
    <main className="min-h-screen">
      <header className="border-b border-[var(--line)] bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[var(--accent)] text-white">
              <FileText className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Tax-Planning-Ops</h1>
              <p className="text-xs text-[var(--muted)]">Advisor workspace</p>
            </div>
          </div>
          <WorkspaceSwitcher />
        </div>
      </header>
      <section className="mx-auto grid max-w-6xl gap-4 px-6 py-6 md:grid-cols-3">
        <div className="rounded-lg border border-[var(--line)] bg-white p-4">
          <p className="text-sm text-[var(--muted)]">API status</p>
          <div className="mt-2 flex items-center gap-2 text-xl font-semibold">
            <RefreshCcw className="h-5 w-5" aria-hidden />
            {health}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--line)] bg-white p-4 md:col-span-2">
          <p className="text-sm text-[var(--muted)]">Active workspace</p>
          <p className="mt-2 font-mono text-sm">{me?.workspace_id ?? "loading"}</p>
          <p className="mt-3 text-sm text-[var(--muted)]">Signed in as {me?.sub ?? "loading"}</p>
        </div>
      </section>
      <section className="mx-auto max-w-6xl px-6">
        <div className="rounded-lg border border-[var(--line)] bg-white p-4 text-sm text-[var(--muted)]">
          {disclaimer}
        </div>
      </section>
    </main>
  );
}
