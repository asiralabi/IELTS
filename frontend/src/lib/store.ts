"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "./types";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  setTokens: (access: string, refresh: string) => void;
  setUser: (user: User | null) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (access, refresh) =>
        set({ accessToken: access, refreshToken: refresh }),
      setUser: (user) => set({ user }),
      logout: () => {
        // Progress is kept on the account (lib/user-state.ts); the local copy
        // goes, so the next person on a shared computer does not inherit it.
        try {
          localStorage.removeItem("ai-ielts-cambridge-progress");
          localStorage.removeItem("ai-ielts-vocab");
        } catch {
          /* private mode */
        }
        set({ accessToken: null, refreshToken: null, user: null });
      },
    }),
    { name: "ai-ielts-auth" }
  )
);
