"use client";

import { Building2 } from "lucide-react";
import { useWorkspace } from "@/components/workspace-provider";

export function WorkspaceSwitcher() {
  const { workspaces, activeWorkspaceId, switchWorkspace } = useWorkspace();
  if (workspaces.length === 0) return null;
  return (
    <label className="inline-flex items-center gap-2 text-sm text-[var(--muted)]">
      <Building2 className="h-4 w-4" aria-hidden />
      <select
        value={activeWorkspaceId ?? ""}
        onChange={(event) => switchWorkspace(event.target.value)}
        className="h-9 rounded-md border border-[var(--line)] bg-white px-2 text-[var(--foreground)]"
      >
        {workspaces.map((workspace) => (
          <option key={workspace.workspaceId} value={workspace.workspaceId}>
            {workspace.displayName ?? workspace.workspaceId}
          </option>
        ))}
      </select>
    </label>
  );
}
