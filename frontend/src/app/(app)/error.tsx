"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AppError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error("[AppRouteError]", error);
  }, [error]);

  return (
    <div
      className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center p-8 text-center"
      role="alert"
      aria-live="assertive"
    >
      <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-rose-500/20 to-red-500/10 text-rose-500">
        <AlertTriangle className="size-8" aria-hidden />
      </span>
      <h2 className="font-display text-2xl font-bold">This page had a problem</h2>
      <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
        {error.message || "We hit an unexpected error loading this section."}
      </p>
      {error.digest && (
        <p className="mt-2 font-mono text-xs text-muted-foreground/60">
          Error ID: {error.digest}
        </p>
      )}
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button onClick={() => unstable_retry()}>
          <RefreshCw className="size-4" aria-hidden />
          Try again
        </Button>
        <Button variant="secondary" onClick={() => (window.location.href = "/dashboard")}>
          <Home className="size-4" aria-hidden />
          Dashboard
        </Button>
      </div>
    </div>
  );
}
