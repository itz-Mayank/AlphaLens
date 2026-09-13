import { create } from "zustand";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: "USER" | "ANALYST" | "ADMIN";
  is_active: boolean;
  is_email_verified: boolean;
  created_at: string;
}

export type AuthStatus = "idle" | "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  status: AuthStatus;
  setStatus: (status: AuthStatus) => void;
  setSession: (user: AuthUser, accessToken: string) => void;
  clear: () => void;
}

// Deliberately NOT persisted (no zustand `persist` middleware, unlike
// uiStore): the access token must never sit in localStorage where any
// injected script could read it. Session restore across page loads goes
// through the httpOnly refresh cookie instead — see useAuthBootstrap.
export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  status: "idle",
  setStatus: (status) => set({ status }),
  setSession: (user, accessToken) => set({ user, accessToken, status: "authenticated" }),
  clear: () => set({ user: null, accessToken: null, status: "unauthenticated" }),
}));
