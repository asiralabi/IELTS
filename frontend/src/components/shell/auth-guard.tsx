"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/store";
import { api } from "@/lib/api";
import { syncUserState } from "@/lib/user-state";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { accessToken, setUser, logout } = useAuth();
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    const check = () => {
      const { accessToken: token, user } = useAuth.getState();
      if (!token) {
        router.replace("/login");
        return;
      }
      // Signed in a moment ago, or a saved session: the account is already
      // known, so show the app now and re-check it in the background instead
      // of holding every page behind a spinner for a round trip.
      if (user) setReady(true);
      api
        .me()
        .then((fresh) => {
          setUser(fresh);
          setReady(true);
        })
        .catch(() => {
          logout();
          router.replace("/login");
        });
      // Bring this account's saved progress down (and anything made offline up).
      syncUserState().catch(() => {});
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
        <div className="size-16 animate-pulse-glow rounded-xl bg-primary" />
      </div>
    );
  }
  return <>{children}</>;
}
