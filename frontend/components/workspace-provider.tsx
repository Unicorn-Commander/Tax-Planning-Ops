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
  WORKSPACE_HEADER_NAME,
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
        const next = ids.map((id: string, index: number) => ({
          workspaceId: id,
          slug: `workspace-${index + 1}`,
          displayName: index === 0 ? "Primary workspace" : `Workspace ${index + 1}`,
          role: "advisor",
          isDefault: id === response.data?.workspace_id,
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
      setActiveWorkspaceId(workspaceId);
      setStoredWorkspaceId(workspaceId);
    },
    [workspaces],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const originalFetch = window.fetch;
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const workspaceId = getStoredWorkspaceId();
      if (workspaceId) {
        const headers = new Headers(init?.headers ?? {});
        if (!headers.has(WORKSPACE_HEADER_NAME)) {
          headers.set(WORKSPACE_HEADER_NAME, workspaceId);
        }
        init = { ...init, headers };
      }
      return originalFetch(input, init);
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, [activeWorkspaceId]);

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
