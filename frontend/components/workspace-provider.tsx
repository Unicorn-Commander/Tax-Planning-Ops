"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import api from "@/lib/api";
import { useAuthStore, type WorkspaceMembership } from "@/lib/store";
import {
  clearWorkspaceStorage,
  getStoredWorkspaceId,
  getStoredWorkspaces,
  resolveActiveWorkspaceId,
  setStoredWorkspaceId,
  setStoredWorkspaces,
} from "@/lib/workspace";

interface WorkspaceContextValue {
  workspaces: WorkspaceMembership[];
  activeWorkspaceId: string | null;
  activeWorkspace: WorkspaceMembership | null;
  isLoading: boolean;
  switchWorkspace: (workspaceId: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [workspaces, setWorkspaces] = useState<WorkspaceMembership[]>(() => getStoredWorkspaces());
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(() =>
    getStoredWorkspaceId(),
  );
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!isAuthenticated) {
      setWorkspaces([]);
      setActiveWorkspaceId(null);
      clearWorkspaceStorage();
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    api
      .get("/me")
      .then((response) => {
        if (cancelled) return;
        const ids = Array.isArray(response.data?.authorized_workspace_ids)
          ? response.data.authorized_workspace_ids
          : [];
        const activeId = response.data?.workspace_id;
        const next = ids.map((id: string) => ({
          workspaceId: id,
          // Honest label until the control-plane exposes workspace names — show
          // the short id, not a fabricated "Primary workspace" ordinal.
          displayName: id.slice(0, 8),
          role: "member",
          isDefault: id === activeId,
        }));
        setWorkspaces(next);
        setStoredWorkspaces(next);
        const resolved = resolveActiveWorkspaceId(next, getStoredWorkspaceId());
        setActiveWorkspaceId(resolved);
        if (resolved) setStoredWorkspaceId(resolved);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const switchWorkspace = useCallback(
    (workspaceId: string) => {
      if (!workspaces.some((ws) => ws.workspaceId === workspaceId)) return;
      setStoredWorkspaceId(workspaceId);
      setActiveWorkspaceId(workspaceId);
      // All API traffic goes through the axios instance, whose interceptor
      // reads the stored workspace id; reload so every screen refetches under
      // the newly selected workspace (previously the UI showed stale data).
      if (typeof window !== "undefined") window.location.reload();
    },
    [workspaces],
  );

  const activeWorkspace = useMemo(
    () => workspaces.find((ws) => ws.workspaceId === activeWorkspaceId) ?? null,
    [workspaces, activeWorkspaceId],
  );

  const value = useMemo(
    () => ({ workspaces, activeWorkspaceId, activeWorkspace, isLoading, switchWorkspace }),
    [workspaces, activeWorkspaceId, activeWorkspace, isLoading, switchWorkspace],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  }
  return context;
}
