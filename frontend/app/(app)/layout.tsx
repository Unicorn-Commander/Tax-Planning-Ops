"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Users, Library, SlidersHorizontal, Sparkles, ShieldCheck } from "lucide-react";
import { useWorkspace } from "@/components/workspace-provider";
import { useAuthStore } from "@/lib/store";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/clients", label: "Clients", icon: Users },
  { href: "/admin", label: "Strategy Library", icon: Library },
  { href: "/admin/brackets", label: "Tax Tables", icon: SlidersHorizontal },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { activeWorkspace } = useWorkspace();
  const user = useAuthStore((s) => s.user);

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-[252px] shrink-0 flex-col border-r border-line bg-surface/70 backdrop-blur-xl md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-[11px] bg-gradient-to-br from-primary to-accent text-white shadow-[0_4px_14px_rgba(124,92,255,0.4)]">
            <Sparkles className="h-[18px] w-[18px]" aria-hidden />
          </div>
          <div className="leading-tight">
            <div className="text-[14.5px] font-semibold tracking-tight text-ink">Tax-Planning-Ops</div>
            <div className="text-[11px] font-medium text-muted">Advisory workspace</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2">
          {(() => {
            // longest-prefix match so /admin/brackets activates "Tax Tables", not "Strategy Library"
            const activeHref = NAV
              .filter((n) => pathname === n.href || pathname.startsWith(n.href + "/"))
              .sort((a, b) => b.href.length - a.href.length)[0]?.href;
            return NAV.map((item) => {
              const active = item.href === activeHref;
              const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2.5 text-[13.5px] font-medium transition-colors",
                  active ? "bg-primary-soft text-primary-strong" : "text-ink-2 hover:bg-surface-2",
                )}
              >
                {active ? <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-primary" /> : null}
                <Icon className={cn("h-[18px] w-[18px]", active ? "text-primary" : "text-muted group-hover:text-ink-2")} aria-hidden />
                {item.label}
              </Link>
            );
            });
          })()}
        </nav>

        <div className="border-t border-line-2 p-3">
          <div className="flex items-center gap-2 rounded-[var(--radius-md)] px-2 py-1.5 text-[12px] text-muted">
            <ShieldCheck className="h-4 w-4 text-positive" aria-hidden />
            <span className="truncate">{activeWorkspace?.displayName ?? "Workspace"}</span>
          </div>
          <div className="mt-1 flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-ink to-ink-2 text-[12px] font-semibold text-white">
              {(user?.name ?? "A").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 leading-tight">
              <div className="truncate text-[12.5px] font-medium text-ink">{user?.name ?? "Advisor"}</div>
              <div className="truncate text-[11px] text-muted">{user?.email ?? "signed in"}</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1200px] px-6 py-7 lg:px-10">{children}</div>
      </main>
    </div>
  );
}
