import type { WorkspaceMembership } from "@/lib/store";

export const WORKSPACE_STORAGE_KEY = "taxplanningops.activeWorkspaceId";
export const WORKSPACES_STORAGE_KEY = "taxplanningops.workspaces";
export const WORKSPACE_HEADER_NAME = "X-Workspace-Id";

function hasStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getStoredWorkspaceId(): string | null {
  if (!hasStorage()) return null;
  try {
    return window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredWorkspaceId(workspaceId: string): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, workspaceId);
  } catch {}
}

export function getStoredWorkspaces(): WorkspaceMembership[] {
  if (!hasStorage()) return [];
  try {
    const raw = window.localStorage.getItem(WORKSPACES_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as WorkspaceMembership[]) : [];
  } catch {
    return [];
  }
}

export function setStoredWorkspaces(workspaces: WorkspaceMembership[]): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.setItem(WORKSPACES_STORAGE_KEY, JSON.stringify(workspaces));
  } catch {}
}

export function clearWorkspaceStorage(): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.removeItem(WORKSPACE_STORAGE_KEY);
    window.localStorage.removeItem(WORKSPACES_STORAGE_KEY);
  } catch {}
}

export function resolveActiveWorkspaceId(
  workspaces: WorkspaceMembership[],
  storedWorkspaceId?: string | null,
): string | null {
  if (workspaces.length === 0) return null;
  if (storedWorkspaceId && workspaces.some((ws) => ws.workspaceId === storedWorkspaceId)) {
    return storedWorkspaceId;
  }
  return (workspaces.find((ws) => ws.isDefault) ?? workspaces[0]).workspaceId;
}
