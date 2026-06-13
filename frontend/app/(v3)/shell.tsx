"use client";

// app/(v3)/shell.tsx — chrome for the v3 route group (not a route file).
// The posture-aware topbar, the file (case) topbar, and the honest scaffold
// helpers the Phase-0 surface stubs use until the swarm fills them in.

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Command } from "lucide-react";
import { cn } from "@/lib/cn";
import { useWorkspace } from "@/components/workspace-provider";
import { useClientOverview } from "@/components/client-overview";
import { usePosture } from "@/lib/posture";
import { Wordmark, Cavatar, Omnibar, Panel, MicroLabel } from "@/components/kit";
import { hueForClient } from "@/components/kit";

const FIRM_NAV = [
  { href: "/desk", label: "Desk" },
  { href: "/book", label: "Book" },
  { href: "/season", label: "Season" },
  { href: "/staff", label: "Staff" },
  { href: "/playbook", label: "Playbook" },
];
const SOLO_NAV = [{ href: "/home", label: "Your Plan" }];

function active(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(href + "/");
}

/** The workbench topbar (firm shell or dissolved solo shell). */
export function V3Topbar() {
  const pathname = usePathname();
  const posture = usePosture();
  const { activeWorkspace } = useWorkspace();
  const nav = posture === "firm" ? FIRM_NAV : SOLO_NAV;

  return (
    <div className="topbar">
      <div className="topbar-inner">
        <Wordmark href="/" />
        {activeWorkspace?.displayName ? (
          <button className="workspace-chip" type="button">
            <span className="sw" />
            {activeWorkspace.displayName}
          </button>
        ) : null}
        <nav className="nav ml-2">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={cn(active(pathname, n.href) && "on")}>
              {n.label}
            </Link>
          ))}
          <Link href="/console" className={cn(active(pathname, "/console") && "on")}>
            Console
          </Link>
        </nav>
        <div className="topbar-right">
          <span className="kbd inline-flex items-center gap-1">
            <Command className="h-3 w-3" /> K
          </span>
        </div>
      </div>
    </div>
  );
}

/** The file (case) topbar — the client/file is the context (§ topbar variant). */
export function FileTopbar({ clientId }: { clientId: string }) {
  const pathname = usePathname();
  const { overview } = useClientOverview();
  const c = overview?.client;
  const base = `/c/${clientId}`;
  const tabs = [
    { href: base, label: "Case" },
    { href: `${base}/return`, label: "Return" },
    { href: `${base}/entities`, label: "Entities" },
    { href: `${base}/brief`, label: "Brief" },
    { href: `${base}/lab`, label: "Lab" },
    { href: `${base}/memo`, label: "Memo" },
    { href: `${base}/plan`, label: "Plan" },
  ];
  return (
    <div className="topbar">
      <div className="topbar-inner">
        <Wordmark href="/" />
        <div className="client-crumb ml-2">
          <Cavatar name={c?.display_name ?? "—"} hue={hueForClient(clientId)} className="!h-[30px] !w-[30px]" />
          <div className="leading-tight">
            <b>{c?.display_name ?? "Loading…"}</b>
            <div className="meta">
              {c?.filing_status_default?.toUpperCase()} {c?.primary_state ? `· ${c.primary_state}` : ""}
            </div>
          </div>
        </div>
        <nav className="nav ml-3">
          {tabs.map((t) => (
            <Link key={t.href} href={t.href} className={cn(pathname === t.href && "on")}>
              {t.label}
            </Link>
          ))}
        </nav>
        <div className="topbar-right">
          <Link href={`${base}/present`} className="mini-btn">Present</Link>
          <span className="kbd inline-flex items-center gap-1">
            <Command className="h-3 w-3" /> K
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Honest Phase-0 scaffold. States the surface, its mockup, and its data wiring
 * so the swarm has a precise in-place target — and so it's unmistakable to a
 * viewer that the surface isn't built yet (no faked data). Removed as each
 * surface lands.
 */
export function SurfaceStub({
  no,
  title,
  intent,
  mockup,
  live,
  additive,
  children,
}: {
  no: string;
  title: string;
  intent: string;
  mockup: string;
  live?: string;
  additive?: string;
  children?: ReactNode;
}) {
  return (
    <div className="wrap py-7">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <MicroLabel>surface {no}</MicroLabel>
          <h1 className="mt-1 text-[30px] font-bold leading-tight tracking-tight">{title}</h1>
          <p className="mt-1 max-w-2xl text-[14px] text-[var(--g-ink-2)]">{intent}</p>
        </div>
      </div>
      {children}
      <Panel className="mt-6 p-5">
        <div className="flex items-center gap-2">
          <span className="dot dot-live" />
          <MicroLabel>Phase 1 target — being built by the swarm</MicroLabel>
        </div>
        <ul className="mt-3 space-y-1.5 text-[13px] text-[var(--g-ink-2)]">
          <li><b>Mockup:</b> <code className="fig">design/mockups/{mockup}</code></li>
          {live ? <li><b className="tone-agent">[live]</b> {live}</li> : null}
          {additive ? <li><b className="tone-cost">[additive]</b> {additive}</li> : null}
        </ul>
      </Panel>
      <div className="mt-6">
        <Omnibar />
      </div>
    </div>
  );
}

/** A small inline note for partially-real scaffolds. */
export function PhaseNote({ children }: { children: ReactNode }) {
  return (
    <div className="mt-4 inline-flex items-center gap-2 rounded-[8px] border border-dashed border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-1.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
      <span className="dot" style={{ background: "var(--cost)" }} />
      {children}
    </div>
  );
}
