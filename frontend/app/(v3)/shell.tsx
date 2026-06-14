"use client";

// app/(v3)/shell.tsx — chrome for the v3 route group (not a route file).
// The posture-aware topbar, the file (case) topbar, and the honest scaffold
// helpers the Phase-0 surface stubs use until the swarm fills them in.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Command, LogOut, Settings, UserRound } from "lucide-react";
import { cn } from "@/lib/cn";
import api from "@/lib/api";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { useClientOverview } from "@/components/client-overview";
import { usePosture } from "@/lib/posture";
import { clearWorkspaceStorage } from "@/lib/workspace";
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
  const nav = posture === "firm" ? FIRM_NAV : SOLO_NAV;

  return (
    <div className="topbar">
      <div className="topbar-inner">
        <Wordmark href="/" />
        {/* Workspace switcher: GET /me memberships · POST/PATCH /workspaces */}
        <WorkspaceSwitcher />
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
          <AccountMenu />
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
          <AccountMenu />
        </div>
      </div>
    </div>
  );
}

/**
 * The account menu — the signed-in identity + a way out. Reads identity from
 * GET /me claims (the SSO is the source of truth for who you are); offers the
 * Settings surface and Sign out (clears the local token + workspace cache and
 * returns to the login screen). Mounted in both topbars.
 */
function AccountMenu() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // GET /me → claims for the signed-in identity (email/preferred_username/sub).
  useEffect(() => {
    let cancelled = false;
    api
      .get("/me")
      .then((res) => {
        if (cancelled) return;
        const claims = (res.data?.claims ?? {}) as Record<string, unknown>;
        const ident =
          (claims.email as string | undefined) ||
          (claims.preferred_username as string | undefined) ||
          (claims.name as string | undefined) ||
          (res.data?.sub as string | undefined) ||
          null;
        setEmail(ident);
      })
      .catch(() => {
        /* identity is best-effort chrome; the menu still works for Sign out */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function signOut() {
    if (typeof window === "undefined") return;
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    clearWorkspaceStorage();
    window.location.href = "/auth/login";
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account"
        title="Account"
        onClick={() => setOpen((v) => !v)}
        className="grid h-[32px] w-[32px] place-items-center rounded-full border border-[var(--g-hairline)] bg-[var(--g-surface)] text-[var(--g-ink-2)] hover:bg-[var(--g-bg-2)] hover:text-[var(--g-ink)]"
      >
        <UserRound className="h-4 w-4" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+8px)] z-[300] w-[240px] overflow-hidden rounded-[12px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)]"
        >
          <div className="border-b border-[var(--g-hairline-soft)] px-3 py-2.5">
            <div className="microlabel">Signed in</div>
            <div className="mt-0.5 truncate text-[13px] text-[var(--g-ink)]" title={email ?? undefined}>
              {email ?? "—"}
            </div>
          </div>
          <div className="p-1">
            <Link
              href="/settings"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-[13px] text-[var(--g-ink-2)] hover:bg-[var(--wash)] hover:text-[var(--g-ink)]"
            >
              <Settings className="h-4 w-4" />
              Settings
            </Link>
            <button
              type="button"
              role="menuitem"
              onClick={signOut}
              className="flex w-full items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-left text-[13px] text-[var(--g-ink-2)] hover:bg-[var(--wash)] hover:text-[var(--cliff)]"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </div>
      ) : null}
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
