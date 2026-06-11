"use client";

import { use } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { ClientOverviewProvider, useClientOverview } from "@/components/client-overview";
import { Badge, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";

const FILING: Record<string, string> = { single: "Single", mfj: "MFJ", mfs: "MFS", hoh: "HoH", qss: "QSS" };
const initials = (n: string) => n.split(" ").map((s) => s[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();

function Header({ clientId }: { clientId: string }) {
  const { overview, loading } = useClientOverview();
  const pathname = usePathname();
  const base = `/clients/${clientId}`;
  const tabs = [
    { href: base, label: "Overview" },
    { href: `${base}/returns`, label: "Return" },
    { href: `${base}/strategies`, label: "Strategies" },
    { href: `${base}/analysis`, label: "Analysis" },
    { href: `${base}/quarterly`, label: "Quarterly" },
    { href: `${base}/pdf`, label: "Plan PDF" },
  ];
  const c = overview?.client;

  return (
    <div className="mb-6">
      <Link href="/clients" className="mb-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> All clients
      </Link>
      <div className="flex items-center gap-4">
        {loading ? (
          <Skeleton className="h-12 w-12 rounded-full" />
        ) : (
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-primary to-accent text-[16px] font-semibold text-white shadow-[0_4px_14px_rgba(124,92,255,0.35)]">
            {initials(c?.display_name ?? "?")}
          </span>
        )}
        <div className="min-w-0">
          {loading ? (
            <Skeleton className="h-7 w-56" />
          ) : (
            <h1 className="truncate text-[24px] font-semibold tracking-tight text-ink">{c?.display_name}</h1>
          )}
          {c ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Badge tone="neutral">{FILING[c.filing_status_default] ?? c.filing_status_default}</Badge>
              {c.primary_state ? <Badge tone="neutral">{c.primary_state}</Badge> : null}
              <Badge tone={c.status === "active" ? "positive" : "neutral"}>{c.status}</Badge>
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-5 flex gap-1 border-b border-line">
        {tabs.map((t) => {
          const active = pathname === t.href;
          return (
            <Link
              key={t.href}
              href={t.href}
              className={cn(
                "relative px-3.5 py-2.5 text-[13.5px] font-medium transition-colors",
                active ? "text-primary" : "text-muted hover:text-ink",
              )}
            >
              {t.label}
              {active ? <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" /> : null}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function ClientLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = use(params);
  return (
    <ClientOverviewProvider clientId={clientId}>
      <div className="animate-in">
        <Header clientId={clientId} />
        {children}
      </div>
    </ClientOverviewProvider>
  );
}
