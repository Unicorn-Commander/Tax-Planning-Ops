"use client";

// The workspace switcher — the firm/tenant picker in the v3 topbar.
//
// Backed by the real multi-workspace tenancy:
//   GET  /me           → membership list (via useWorkspace())
//   POST /workspaces   → create a workspace, then switch to it
//   PATCH /workspaces/{id} → rename a membership
// switchWorkspace() (from the provider) persists the active id and reloads so
// every surface refetches under the chosen workspace; the axios client sends
// the active X-Workspace-Id automatically.

import { useEffect, useRef, useState } from "react";
import { Building2, Check, ChevronsUpDown, Pencil, Plus } from "lucide-react";
import api from "@/lib/api";
import { useAction } from "@/lib/useAction";
import { useWorkspace } from "@/components/workspace-provider";
import {
  getStoredWorkspaces,
  setStoredWorkspaces,
  setStoredWorkspaceId,
} from "@/lib/workspace";
import type { WorkspaceMembership } from "@/lib/store";

export function WorkspaceSwitcher() {
  const { workspaces, activeWorkspaceId, activeWorkspace, switchWorkspace } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameName, setRenameName] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside-click / Escape.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
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

  // POST /workspaces → switch to the freshly created one.
  const create = useAction(async () => {
    const name = newName.trim();
    if (!name) return;
    const res = await api.post("/workspaces", { name });
    const created = res.data as WorkspaceMembership;
    // Seed the stored membership list so the switcher's reload lands on a known
    // workspace even before /me refetches.
    const next = [...getStoredWorkspaces().filter((w) => w.workspaceId !== created.workspaceId), created];
    setStoredWorkspaces(next);
    setStoredWorkspaceId(created.workspaceId);
    setCreating(false);
    setNewName("");
    // The provider only switches to known memberships; persist + reload directly.
    if (typeof window !== "undefined") window.location.reload();
  });

  // PATCH /workspaces/{id} → rename, then reload to pick up the new label.
  const rename = useAction(async (workspaceId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await api.patch(`/workspaces/${workspaceId}`, { name: trimmed });
    const next = getStoredWorkspaces().map((w) =>
      w.workspaceId === workspaceId ? { ...w, displayName: trimmed } : w,
    );
    setStoredWorkspaces(next);
    setRenamingId(null);
    if (typeof window !== "undefined") window.location.reload();
  });

  if (workspaces.length === 0) return null;

  const label = activeWorkspace?.displayName ?? activeWorkspace?.workspaceId.slice(0, 8) ?? "Workspace";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className="workspace-chip"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title="Switch workspace"
      >
        <span className="sw" />
        <span className="max-w-[180px] truncate">{label}</span>
        <ChevronsUpDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute left-0 top-[calc(100%+8px)] z-[300] w-[280px] overflow-hidden rounded-[12px] border border-[var(--g-hairline)] bg-[var(--g-surface)] shadow-[var(--shadow-panel)]"
        >
          <div className="border-b border-[var(--g-hairline-soft)] px-3 py-2 microlabel">
            Workspaces
          </div>

          <div className="max-h-[320px] overflow-y-auto py-1">
            {workspaces.map((ws) => {
              const isActive = ws.workspaceId === activeWorkspaceId;
              const isRenaming = renamingId === ws.workspaceId;
              return (
                <div key={ws.workspaceId} className="px-1">
                  {isRenaming ? (
                    <form
                      className="flex items-center gap-1.5 px-2 py-1.5"
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
                          if (e.key === "Escape") {
                            e.preventDefault();
                            setRenamingId(null);
                          }
                        }}
                        className="h-8 min-w-0 flex-1 rounded-[8px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-2 text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
                        placeholder="Workspace name"
                      />
                      <button
                        type="submit"
                        disabled={rename.pending || !renameName.trim()}
                        className="mini-btn go !px-2 !py-1.5 text-[11px]"
                      >
                        Save
                      </button>
                    </form>
                  ) : (
                    <div
                      className="group flex w-full items-center gap-2 rounded-[8px] px-2 py-1.5 text-[13px] hover:bg-[var(--wash)]"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                        onClick={() => {
                          if (!isActive) switchWorkspace(ws.workspaceId);
                          else setOpen(false);
                        }}
                      >
                        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-[6px] bg-[var(--agent-soft)] text-[var(--agent)]">
                          {isActive ? <Check className="h-3.5 w-3.5" /> : <Building2 className="h-3 w-3" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[var(--g-ink)]">
                            {ws.displayName ?? ws.workspaceId.slice(0, 8)}
                          </span>
                          <span className="block truncate font-mono text-[10px] text-[var(--g-ink-3)]">
                            {ws.role}
                            {ws.isDefault ? " · home" : ""}
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        title="Rename"
                        aria-label={`Rename ${ws.displayName ?? "workspace"}`}
                        className="shrink-0 rounded-[6px] p-1 text-[var(--g-ink-3)] opacity-0 transition-opacity hover:bg-[var(--wash-2)] hover:text-[var(--g-ink)] group-hover:opacity-100"
                        onClick={() => {
                          setRenamingId(ws.workspaceId);
                          setRenameName(ws.displayName ?? "");
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {rename.error ? (
            <p className="px-3 pb-1 text-[12px] text-[var(--cliff)]">{rename.error}</p>
          ) : null}

          <div className="border-t border-[var(--g-hairline-soft)] p-1">
            {creating ? (
              <form
                className="flex items-center gap-1.5 px-2 py-1.5"
                onSubmit={(e) => {
                  e.preventDefault();
                  void create.run();
                }}
              >
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      e.preventDefault();
                      setCreating(false);
                      setNewName("");
                    }
                  }}
                  className="h-8 min-w-0 flex-1 rounded-[8px] border border-[var(--g-hairline)] bg-[var(--g-bg)] px-2 text-[13px] text-[var(--g-ink)] outline-none focus:border-[var(--agent)]"
                  placeholder="New workspace name"
                />
                <button
                  type="submit"
                  disabled={create.pending || !newName.trim()}
                  className="mini-btn go !px-2 !py-1.5 text-[11px]"
                >
                  {create.pending ? "Creating…" : "Create"}
                </button>
              </form>
            ) : (
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-[8px] px-2 py-1.5 text-[13px] text-[var(--g-ink-2)] hover:bg-[var(--wash)] hover:text-[var(--g-ink)]"
                onClick={() => setCreating(true)}
              >
                <span className="grid h-5 w-5 place-items-center rounded-[6px] border border-dashed border-[var(--g-hairline)] text-[var(--g-ink-3)]">
                  <Plus className="h-3 w-3" />
                </span>
                New workspace
              </button>
            )}
            {create.error ? (
              <p className="px-2 pb-1 text-[12px] text-[var(--cliff)]">{create.error}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
