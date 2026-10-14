"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { API_URL } from "@/lib/api";

/**
 * The API runs as a serverless function that sleeps when nobody is using it,
 * and waking it costs ~6 seconds. Knock on it the moment a sign-in page opens,
 * so it is awake by the time the student has typed a password or picked a
 * Google account, and fetch the dashboard's code while they do.
 */
export function WarmUp() {
  const router = useRouter();
  React.useEffect(() => {
    fetch(`${API_URL}/health`, { cache: "no-store" }).catch(() => {});
    router.prefetch("/dashboard");
  }, [router]);
  return null;
}
