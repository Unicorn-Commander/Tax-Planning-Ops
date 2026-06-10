"use client";

import { AuthProvider } from "@/components/auth-provider";
import { WorkspaceProvider } from "@/components/workspace-provider";

export function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <WorkspaceProvider>{children}</WorkspaceProvider>
    </AuthProvider>
  );
}
