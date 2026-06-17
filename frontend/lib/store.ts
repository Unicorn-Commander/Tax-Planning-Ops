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
  // False until the auth provider has read localStorage and made a sign-in
  // decision. Consumers must wait for this before reacting to `isAuthenticated`
  // — on first paint it is transiently `false` purely because the token hasn't
  // hydrated yet, NOT because the user is logged out. (Acting on that transient
  // false is what previously wiped the selected workspace on every reload.)
  ready: boolean;
  setUser: (user: User | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  ready: false,
  // Any setUser call is a settled auth decision (authed or not) → we're ready.
  setUser: (user) => set({ user, isAuthenticated: Boolean(user), ready: true }),
}));
