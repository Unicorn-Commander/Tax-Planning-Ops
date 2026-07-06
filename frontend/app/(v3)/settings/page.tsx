"use client";

// Surface — ACCOUNT & SETTINGS
//
// The account/settings home in the v3 "Daylight & Paper" style. Five sections,
// each wired to a real endpoint (no fabricated data; honest loading/empty/error
// states throughout).
//
// DATA WIRING:
// [live] GET  /me                → Profile (identity is the SSO's; read-only)
// [live] GET  /workspaces        → Workspaces list (the multi-tenant manager)
// [live] POST /workspaces {name} → create, then switch to it
// [live] PATCH /workspaces/{id} {name} → rename a membership
// [live] GET/PUT /admin/branding → firm letterhead (name/color/signature)
//        Appearance → the global light/dark mechanism (components/theme.tsx)
//
// [additive] POST /demo/load · POST /demo/reset — being built by another agent.
//        Called BY PATH; a 404 (not-yet-deployed) degrades to a disabled
//        "coming soon" state rather than crashing.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Building2,
  Check,
  KeyRound,
  Moon,
  Palette,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sun,
  UserRound,
} from "lucide-react";
import api from "@/lib/api";
import { isAxiosError } from "axios";
import { useAction } from "@/lib/useAction";
import { useWorkspace } from "@/components/workspace-provider";
import { setTheme } from "@/components/theme";
import {
  getStoredWorkspaces,
  setStoredWorkspaces,
  setStoredWorkspaceId,
} from "@/lib/workspace";
import type { WorkspaceMembership } from "@/lib/store";
import {
  Panel,
  PanelHead,
  MicroLabel,
  Annotation,
  Chip,
  Button,
  Stamp,
} from "@/components/kit";

/* ----------------------------- shapes ----------------------------- */
interface MeResponse {
  sub: string;
  workspace_id: string;
  authorized_workspace_ids: string[];
  workspaces: WorkspaceMembership[];
  scopes: string[];
  claims: Record<string, unknown>;
}
interface Branding {
  firm_name: string;
  logo_blob_key: string | null;
  primary_color: string;
  advisor_signature: string | null;
}

/* A labelled section frame matching the Daylight surfaces. */
function Section({
  icon,
  title,
  desc,
  children,
  aside,
}: {
  icon: ReactNode;
  title: string;
  desc: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <Panel className="rise overflow-hidden">
      <PanelHead>
        <span className="grid h-7 w-7 place-items-center rounded-[8px] bg-[var(--agent-soft)] text-[var(--agent)]">
          {icon}
        </span>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold leading-tight text-[var(--g-ink)]">{title}</div>
          <div className="mt-0.5 text-[12px] text-[var(--g-ink-3)]">{desc}</div>
        </div>
        {aside ? <div className="ml-auto">{aside}</div> : null}
      </PanelHead>
      {children}
    </Panel>
  );
}

/* A read-only "what is it" row. */
function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-[var(--g-hairline-soft)] px-5 py-3 first:border-t-0">
      <span className="w-[140px] shrink-0 text-[12px] text-[var(--g-ink-3)]">{label}</span>
      <span className="min-w-0 flex-1 text-[13.5px] text-[var(--g-ink)]">{children}</span>
    </div>
  );
}

/* A labelled text input matching the Daylight form style. */
function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  hint?: ReactNode;
}) {
  return (
    <label className="block">
      <span className="microlabel">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1.5 h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-3 text-[14px] text-[var(--g-ink)] outline-none transition-colors focus:border-[var(--agent)]"
      />
      {hint ? <span className="mt-1 block text-[11.5px] text-[var(--g-ink-3)]">{hint}</span> : null}
    </label>
  );
}

export default function SettingsPage() {
  return (
    <div className="wrap py-7 pb-16">
      <section className="rise">
        <MicroLabel>Account &amp; settings</MicroLabel>
        <h1 className="mt-2 text-[30px] font-bold leading-tight tracking-[-0.02em]">Settings</h1>
        <Annotation className="mt-1 block !text-[14.5px]">
          your identity, your workspaces, and how the firm presents itself
        </Annotation>
      </section>

      <div className="mt-6 grid gap-[22px]">
        <ProfileSection />
        <WorkspacesSection />
        <BrandingSection />
        <AppearanceSection />
        <IntegrationsSection />
        <DemoSection />
      </div>
    </div>
  );
}

/* ============================== PROFILE ============================== */
function ProfileSection() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const { activeWorkspace } = useWorkspace();

  useEffect(() => {
    let cancelled = false;
    api
      .get("/me")
      .then((r) => {
        if (!cancelled) setMe(r.data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const claims = me?.claims ?? {};
  const email =
    (claims.email as string | undefined) ||
    (claims.preferred_username as string | undefined) ||
    (claims.name as string | undefined) ||
    null;
  const scopes = me?.scopes ?? [];

  return (
    <Section
      icon={<UserRound className="h-4 w-4" />}
      title="Profile"
      desc="Who you are signed in as"
      aside={
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--g-hairline)] px-2.5 py-1 text-[11px] text-[var(--g-ink-3)]">
          <ShieldCheck className="h-3.5 w-3.5" />
          managed by SSO
        </span>
      }
    >
      {loading ? (
        <div className="space-y-2 p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-8 w-full rounded-[8px]" />
          ))}
        </div>
      ) : failed ? (
        <div className="px-5 py-5 text-[13px] text-[var(--cliff)]">Couldn&rsquo;t load your profile.</div>
      ) : (
        <>
          <InfoRow label="Email">
            {email ?? <span className="text-[var(--g-ink-3)]">not provided by the identity token</span>}
          </InfoRow>
          <InfoRow label="User ID">
            <code className="fig text-[12.5px] text-[var(--g-ink-2)]">{me?.sub}</code>
          </InfoRow>
          <InfoRow label="Active workspace">
            {activeWorkspace?.displayName ?? activeWorkspace?.workspaceId.slice(0, 8) ?? "—"}
            {activeWorkspace?.role ? (
              <Chip className="ml-2 !py-0.5 text-[10.5px]">{activeWorkspace.role}</Chip>
            ) : null}
          </InfoRow>
          <InfoRow label="Access / scopes">
            {scopes.length > 0 ? (
              <span className="flex flex-wrap gap-1.5">
                {scopes.map((s) => (
                  <Chip key={s} className="!py-0.5 font-mono text-[10.5px]">
                    {s}
                  </Chip>
                ))}
              </span>
            ) : (
              <span className="text-[var(--g-ink-3)]">none</span>
            )}
          </InfoRow>
          <div className="border-t border-[var(--g-hairline-soft)] px-5 py-3 text-[11.5px] text-[var(--g-ink-3)]">
            Your identity is managed by single sign-on — edit your name, email, or password in your
            account provider, not here.
          </div>
        </>
      )}
    </Section>
  );
}

/* ============================ WORKSPACES ============================ */
function WorkspacesSection() {
  const { activeWorkspaceId, switchWorkspace } = useWorkspace();
  const [list, setList] = useState<WorkspaceMembership[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameName, setRenameName] = useState("");

  const load = useCallback(() => {
    api
      .get("/workspaces")
      .then((r) => setList(Array.isArray(r.data) ? r.data : []))
      .catch(() => setList([]));
  }, []);
  useEffect(load, [load]);

  // POST /workspaces → switch to it (full reload picks up the new active id).
  const create = useAction(async () => {
    const name = newName.trim();
    if (!name) return;
    const res = await api.post("/workspaces", { name });
    const created = res.data as WorkspaceMembership;
    const stored = [
      ...getStoredWorkspaces().filter((w) => w.workspaceId !== created.workspaceId),
      created,
    ];
    setStoredWorkspaces(stored);
    setStoredWorkspaceId(created.workspaceId);
    setCreating(false);
    setNewName("");
    if (typeof window !== "undefined") window.location.reload();
  });

  // PATCH /workspaces/{id}
  const rename = useAction(async (id: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await api.patch(`/workspaces/${id}`, { name: trimmed });
    setRenamingId(null);
    setStoredWorkspaces(
      getStoredWorkspaces().map((w) => (w.workspaceId === id ? { ...w, displayName: trimmed } : w)),
    );
    load();
  });

  return (
    <Section
      icon={<Building2 className="h-4 w-4" />}
      title="Workspaces"
      desc="Each workspace is a separate firm/tenant — its own clients, books, and letterhead"
      aside={
        !creating ? (
          <Button variant="ghost" className="text-[12.5px]" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" /> New workspace
          </Button>
        ) : null
      }
    >
      {creating ? (
        <form
          className="flex flex-wrap items-end gap-2 border-b border-[var(--g-hairline-soft)] bg-[var(--g-bg-2)] px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            void create.run();
          }}
        >
          <label className="min-w-[220px] flex-1">
            <span className="microlabel">New workspace name</span>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Northstar Advisory"
              className="mt-1.5 h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-surface)] px-3 text-[14px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
            />
          </label>
          <div className="flex gap-2">
            <Button
              type="submit"
              variant="ink"
              disabled={create.pending || !newName.trim()}
              className="text-[12.5px]"
            >
              {create.pending ? "Creating…" : "Create & switch"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="text-[12.5px]"
              onClick={() => {
                setCreating(false);
                setNewName("");
              }}
            >
              Cancel
            </Button>
          </div>
          {create.error ? (
            <p className="w-full text-[12.5px] text-[var(--cliff)]">{create.error}</p>
          ) : null}
        </form>
      ) : null}

      {list === null ? (
        <div className="space-y-2 p-5">
          {[0, 1].map((i) => (
            <div key={i} className="skeleton h-12 w-full rounded-[10px]" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="px-5 py-6 text-center text-[13px] text-[var(--g-ink-3)]">
          No workspaces yet. Create one to get started.
        </div>
      ) : (
        <div>
          {list.map((ws) => {
            const isActive = ws.workspaceId === activeWorkspaceId;
            const isRenaming = renamingId === ws.workspaceId;
            return (
              <div
                key={ws.workspaceId}
                className="flex flex-wrap items-center gap-3 border-t border-[var(--g-hairline-soft)] px-5 py-3.5 first:border-t-0"
              >
                <span
                  className={
                    "grid h-9 w-9 shrink-0 place-items-center rounded-[10px] " +
                    (isActive
                      ? "bg-[var(--agent-soft)] text-[var(--agent)]"
                      : "border border-[var(--g-hairline)] text-[var(--g-ink-3)]")
                  }
                >
                  {isActive ? <Check className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
                </span>

                {isRenaming ? (
                  <form
                    className="flex min-w-[220px] flex-1 items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void rename.run(ws.workspaceId, renameName);
                    }}
                  >
                    <input
                      autoFocus
                      value={renameName}
                      onChange={(e) => setRenameName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="h-9 min-w-0 flex-1 rounded-[9px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-2.5 text-[13.5px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
                    />
                    <Button
                      type="submit"
                      variant="ink"
                      disabled={rename.pending || !renameName.trim()}
                      className="!px-3 !py-2 text-[12px]"
                    >
                      Save
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="!px-3 !py-2 text-[12px]"
                      onClick={() => setRenamingId(null)}
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <b className="truncate text-[14px] text-[var(--g-ink)]">
                          {ws.displayName ?? ws.workspaceId.slice(0, 8)}
                        </b>
                        {ws.isDefault ? (
                          <span className="font-mono text-[10px] text-[var(--g-ink-3)]">home</span>
                        ) : null}
                        {isActive ? <Chip tone="agent" className="!py-0.5 text-[10px]">active</Chip> : null}
                      </div>
                      <div className="mt-0.5 font-mono text-[10.5px] text-[var(--g-ink-3)]">
                        {ws.role} · {ws.workspaceId.slice(0, 8)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[12px] text-[var(--g-ink-3)] hover:bg-[var(--wash)] hover:text-[var(--g-ink)]"
                        onClick={() => {
                          setRenamingId(ws.workspaceId);
                          setRenameName(ws.displayName ?? "");
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" /> Rename
                      </button>
                      {!isActive ? (
                        <Button
                          variant="ghost"
                          className="!px-3 !py-2 text-[12px]"
                          onClick={() => switchWorkspace(ws.workspaceId)}
                        >
                          Switch
                        </Button>
                      ) : null}
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {rename.error ? (
            <p className="px-5 pb-2 text-[12.5px] text-[var(--cliff)]">{rename.error}</p>
          ) : null}
        </div>
      )}
    </Section>
  );
}

/* ============================= BRANDING ============================= */
function BrandingSection() {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [firmName, setFirmName] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#0f766e");
  const [signature, setSignature] = useState("");
  const [logoKey, setLogoKey] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/admin/branding")
      .then((r) => {
        if (cancelled) return;
        const b = r.data as Branding | null;
        if (b) {
          setFirmName(b.firm_name ?? "");
          setPrimaryColor(b.primary_color || "#0f766e");
          setSignature(b.advisor_signature ?? "");
          setLogoKey(b.logo_blob_key ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // PUT /admin/branding (BrandingIn: firm_name, logo_blob_key?, primary_color, advisor_signature?)
  const save = useAction(async () => {
    await api.put("/admin/branding", {
      firm_name: firmName.trim(),
      logo_blob_key: logoKey,
      primary_color: primaryColor,
      advisor_signature: signature.trim() || null,
    });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
  });

  const colorOk = /^#[0-9a-fA-F]{6}$/.test(primaryColor);

  return (
    <Section
      icon={<Palette className="h-4 w-4" />}
      title="Firm branding"
      desc="The letterhead on plans, memos, and the Present view"
      aside={
        saved ? (
          <Stamp kind="verified" fresh className="!transform-none">
            saved
          </Stamp>
        ) : null
      }
    >
      {loading ? (
        <div className="space-y-3 p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-12 w-full rounded-[10px]" />
          ))}
        </div>
      ) : failed ? (
        <div className="px-5 py-5 text-[13px] text-[var(--cliff)]">
          Couldn&rsquo;t load the firm branding. You may not have admin access in this workspace.
        </div>
      ) : (
        <form
          className="space-y-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            void save.run();
          }}
        >
          <LabeledInput
            label="Firm name"
            value={firmName}
            onChange={setFirmName}
            placeholder="e.g. Northstar Advisory"
            hint="Appears as the letterhead on every client document."
          />

          <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
            <label className="block">
              <span className="microlabel">Primary color</span>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  type="color"
                  value={colorOk ? primaryColor : "#0f766e"}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  aria-label="Primary color picker"
                  className="h-10 w-12 shrink-0 cursor-pointer rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg)] p-1"
                />
                <input
                  type="text"
                  value={primaryColor}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  placeholder="#0f766e"
                  className="h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-3 font-mono text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
                />
              </div>
              {!colorOk ? (
                <span className="mt-1 block text-[11.5px] text-[var(--cost)]">Use a 6-digit hex like #0f766e.</span>
              ) : null}
            </label>

            <label className="block">
              <span className="microlabel">Advisor signature</span>
              <input
                type="text"
                value={signature}
                onChange={(e) => setSignature(e.target.value)}
                placeholder="e.g. Jordan Alvarez, EA"
                className="mt-1.5 h-10 w-full rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-3 text-[14px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
              />
              <span className="mt-1 block text-[11.5px] text-[var(--g-ink-3)]">
                Signs the plan memo and engagement letter.
              </span>
            </label>
          </div>

          {save.error ? <p className="text-[12.5px] text-[var(--cliff)]">{save.error}</p> : null}

          <div className="flex items-center gap-3 pt-1">
            <Button
              type="submit"
              variant="ink"
              disabled={save.pending || !firmName.trim() || !colorOk}
              className="text-[13px]"
            >
              {save.pending ? "Saving…" : "Save branding"}
            </Button>
            <span className="inline-flex items-center gap-2 text-[12px] text-[var(--g-ink-3)]">
              <span
                className="inline-block h-3 w-3 rounded-full ring-1 ring-inset ring-[var(--g-hairline)]"
                style={{ background: colorOk ? primaryColor : "transparent" }}
              />
              live preview of the accent
            </span>
          </div>
        </form>
      )}
    </Section>
  );
}

/* ============================ APPEARANCE ============================ */
function AppearanceSection() {
  const [theme, setLocal] = useState<"light" | "dark">("light");

  useEffect(() => {
    const t = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    setLocal(t);
  }, []);

  function choose(next: "light" | "dark") {
    setTheme(next);
    setLocal(next);
  }

  const options: { key: "light" | "dark"; label: string; sub: string; icon: ReactNode }[] = [
    { key: "light", label: "Daylight", sub: "the default working surface", icon: <Sun className="h-4 w-4" /> },
    { key: "dark", label: "Dusk", sub: "low-light workbench", icon: <Moon className="h-4 w-4" /> },
  ];

  return (
    <Section
      icon={theme === "dark" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
      title="Appearance"
      desc="The workbench theme — documents stay paper in both"
    >
      <div className="grid gap-3 p-5 sm:grid-cols-2">
        {options.map((opt) => {
          const on = theme === opt.key;
          return (
            <button
              key={opt.key}
              type="button"
              onClick={() => choose(opt.key)}
              aria-pressed={on}
              className={
                "flex items-center gap-3 rounded-[12px] border px-4 py-3 text-left transition-colors " +
                (on
                  ? "border-[color-mix(in_srgb,var(--agent)_45%,transparent)] bg-[var(--agent-soft)]"
                  : "border-[var(--g-hairline)] bg-[var(--g-bg)] hover:bg-[var(--g-bg-2)]")
              }
            >
              <span
                className={
                  "grid h-9 w-9 place-items-center rounded-[9px] " +
                  (on ? "bg-[var(--agent)] text-white" : "border border-[var(--g-hairline)] text-[var(--g-ink-2)]")
                }
              >
                {opt.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-semibold text-[var(--g-ink)]">{opt.label}</span>
                <span className="block text-[12px] text-[var(--g-ink-3)]">{opt.sub}</span>
              </span>
              {on ? <Check className="h-4 w-4 text-[var(--agent)]" /> : null}
            </button>
          );
        })}
      </div>
    </Section>
  );
}

/* ========================= MCP / API ACCESS ========================= */
// Static help surface — how to drive TPO from an external agent (Claude Code,
// Cursor, ...) via the MCP "third door". No data fetch: the PAT-management UI is
// not built yet, so this documents the durable-token path (mint via the API) and
// points at docs/MCP.md. Every tool proxies the same /api/v1 endpoints, so an
// agent caller gets the identical auth / RLS / entitlement fence as this browser.
function IntegrationsSection() {
  return (
    <Section
      icon={<Plug className="h-4 w-4" />}
      title="Connect via MCP / API"
      desc="Drive TPO from an agent client (Claude Code, Cursor) — the third door over the same engine"
      aside={
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--g-hairline)] px-2.5 py-1 text-[11px] text-[var(--g-ink-3)]">
          <KeyRound className="h-3.5 w-3.5" />
          durable token
        </span>
      }
    >
      <div className="space-y-4 p-5">
        <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
          TPO exposes an <b className="text-[var(--g-ink)]">MCP / API</b> surface alongside this GUI —
          same engine, same rules. An agent authenticates with a{" "}
          <code className="fig text-[12px] text-[var(--g-ink-2)]">tpo_pat_</code> Personal Access Token
          and gets the <b className="text-[var(--g-ink)]">identical RLS, entitlement, and scope fence</b>{" "}
          you have in the browser — it can only reach the workspaces and actions your own scopes allow.
        </p>

        <div>
          <span className="microlabel">HTTP MCP endpoint</span>
          <div className="mt-1.5 overflow-x-auto rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2.5">
            <code className="fig whitespace-pre text-[12px] text-[var(--g-ink-2)]">
              POST https://api.taxplanningops.magicunicorn.dev/api/v1/mcp
            </code>
          </div>
        </div>

        <div>
          <span className="microlabel">Mint a token</span>
          <span className="mt-1 block text-[11.5px] text-[var(--g-ink-3)]">
            A dedicated token manager is coming to Settings. Until then, mint one from the API with your
            signed-in session (the raw secret is shown once):
          </span>
          <div className="mt-1.5 overflow-x-auto rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2.5">
            <code className="fig whitespace-pre text-[12px] text-[var(--g-ink-2)]">
              POST /api/v1/auth/pats  {"{"} &quot;name&quot;: &quot;claude-code&quot;, &quot;ttl_days&quot;: 90 {"}"}
            </code>
          </div>
        </div>

        <div>
          <span className="microlabel">Add to Claude Code</span>
          <div className="mt-1.5 overflow-x-auto rounded-[10px] border border-[var(--g-hairline)] bg-[var(--g-bg-2)] px-3 py-2.5">
            <code className="fig whitespace-pre text-[12px] text-[var(--g-ink-2)]">
              claude mcp add --transport http tax-planning-ops \{"\n"}
              {"  "}https://api.taxplanningops.magicunicorn.dev/api/v1/mcp \{"\n"}
              {"  "}--header &quot;Authorization: Bearer tpo_pat_...&quot;
            </code>
          </div>
        </div>

        <p className="text-[11.5px] text-[var(--g-ink-3)]">
          Full tool catalog, PAT lifecycle (mint / list / revoke), and the stdio transport are documented
          in <code className="fig">docs/MCP.md</code>.
        </p>
      </div>
    </Section>
  );
}

/* =========================== DEMO / SAMPLE =========================== */
// The demo endpoints are built by another agent (POST /demo/load, /demo/reset).
// Called BY PATH. A 404 means not-yet-deployed → degrade to a disabled
// "coming soon" state; any other error surfaces inline. Never crash.
function DemoSection() {
  const [available, setAvailable] = useState<boolean | null>(null); // null = unknown
  const [loadedNote, setLoadedNote] = useState<string | null>(null);

  function markComingSoon(err: unknown): boolean {
    // A 404/405 (route absent) → not deployed yet. Treat as "coming soon".
    if (isAxiosError(err) && (err.response?.status === 404 || err.response?.status === 405)) {
      setAvailable(false);
      return true;
    }
    return false;
  }

  const load = useAction(async () => {
    try {
      await api.post("/demo/load");
      setAvailable(true);
      setLoadedNote("Sample data loaded — switch to the new 'Sample Firm (demo)' workspace above.");
      // Refresh so the new demo workspace appears in the switcher + /me.
      if (typeof window !== "undefined") {
        window.setTimeout(() => window.location.reload(), 900);
      }
    } catch (err) {
      if (markComingSoon(err)) return;
      throw err;
    }
  });

  const reset = useAction(async () => {
    try {
      await api.post("/demo/reset");
      setAvailable(true);
      setLoadedNote("Demo data reset.");
      if (typeof window !== "undefined") {
        window.setTimeout(() => window.location.reload(), 900);
      }
    } catch (err) {
      if (markComingSoon(err)) return;
      throw err;
    }
  });

  const comingSoon = available === false;

  return (
    <Section
      icon={<Sparkles className="h-4 w-4" />}
      title="Demo / sample data"
      desc="Spin up a self-contained sample firm to explore — or wipe it"
      aside={
        comingSoon ? (
          <span className="rounded-full border border-dashed border-[var(--g-hairline)] px-2.5 py-1 text-[11px] text-[var(--g-ink-3)]">
            coming soon
          </span>
        ) : null
      }
    >
      <div className="p-5">
        <p className="text-[13px] leading-relaxed text-[var(--g-ink-2)]">
          Loading sample data creates a separate{" "}
          <b className="text-[var(--g-ink)]">Sample Firm (demo)</b> workspace with example clients you
          can switch into — it never touches your real workspaces.
        </p>

        {loadedNote ? (
          <div className="mt-3 flex items-center gap-2 rounded-[10px] border border-[color-mix(in_srgb,var(--save)_35%,transparent)] bg-[var(--save-soft)] px-3.5 py-2.5 text-[12.5px] text-[var(--save)]">
            <Check className="h-4 w-4 shrink-0" />
            {loadedNote}
          </div>
        ) : null}

        {load.error ? <p className="mt-3 text-[12.5px] text-[var(--cliff)]">{load.error}</p> : null}
        {reset.error ? <p className="mt-3 text-[12.5px] text-[var(--cliff)]">{reset.error}</p> : null}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="ink"
            disabled={comingSoon || load.pending || reset.pending}
            onClick={() => void load.run()}
            className="text-[13px]"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {load.pending ? "Loading…" : "Load sample data"}
          </Button>
          <Button
            variant="ghost"
            disabled={comingSoon || reset.pending || load.pending}
            onClick={() => void reset.run()}
            className="text-[13px]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {reset.pending ? "Resetting…" : "Reset demo data"}
          </Button>
        </div>

        {comingSoon ? (
          <p className="mt-3 font-mono text-[10.5px] text-[var(--g-ink-3)]">
            The demo endpoints aren&rsquo;t deployed on this node yet — these controls activate once
            <code className="mx-1 fig">POST /demo/load</code> ships.
          </p>
        ) : null}
      </div>
    </Section>
  );
}
