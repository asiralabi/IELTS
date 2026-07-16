"use client";

import { motion } from "framer-motion";
import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export type PracticeErrorProps = {
  title?: string;
  message: string;
  retryLabel?: string;
  onRetry: () => void;
  onDismiss?: () => void;
  dismissLabel?: string;
};

export function PracticeError({
  title = "We couldn't finish that",
  message,
  retryLabel = "Try again",
  onRetry,
  onDismiss,
  dismissLabel = "Start over",
}: PracticeErrorProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-strong mx-auto max-w-xl rounded-[28px] p-8 text-center shadow-soft"
      role="alert"
      aria-live="assertive"
    >
      <span className="mx-auto mb-4 flex size-14 items-center justify-center rounded-[20px] bg-gradient-to-br from-rose-500/20 to-red-500/10 text-rose-500">
        <AlertTriangle className="size-7" aria-hidden />
      </span>
      <h3 className="font-display text-xl font-semibold">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{message}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Button onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden />
          {retryLabel}
        </Button>
        {onDismiss && (
          <Button variant="secondary" onClick={onDismiss}>
            <X className="size-4" aria-hidden />
            {dismissLabel}
          </Button>
        )}
      </div>
    </motion.div>
  );
}
