import { create } from "zustand";

export interface User {
  sub: string;
  email?: string;
  name?: string;
  role?: string;
  workspaces?: WorkspaceMembership[];
}

export interface WorkspaceMembership {
  workspaceId: string;
  slug?: string;
  displayName?: string;
  role: string;
  isDefault: boolean;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  setUser: (user: User | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  setUser: (user) => set({ user, isAuthenticated: Boolean(user) }),
}));
