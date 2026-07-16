"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/store";
import { api } from "@/lib/api";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { accessToken, setUser, logout } = useAuth();
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    const check = () => {
      const { accessToken: token } = useAuth.getState();
      if (!token) {
        router.replace("/login");
        return;
      }
      api
        .me()
        .then((user) => {
          setUser(user);
          setReady(true);
        })
        .catch(() => {
          logout();
          router.replace("/login");
        });
    };
    // Zustand persist may still be rehydrating from localStorage on a full
    // page load — checking the token before that finishes logs users out.
    if (useAuth.persist.hasHydrated()) {
      check();
      return;
    }
    return useAuth.persist.onFinishHydration(check);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!ready && !accessToken) return null;
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="size-16 animate-pulse-glow rounded-[22px] bg-gradient-to-br from-primary to-secondary" />
      </div>
    );
  }
  return <>{children}</>;
}
