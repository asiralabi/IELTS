"use client";

import { Skeleton } from "@/components/ui/skeleton";

/**
 * Two-column skeleton for the initial generation phase of reading (and
 * single-column variants for listening / writing). Keeps the user oriented in
 * the eventual layout while the LLM is thinking, instead of a modal loader.
 */
export function ReadingSkeleton() {
  return (
    <div
      className="grid gap-6 lg:grid-cols-2"
      role="status"
      aria-live="polite"
      aria-label="Loading passage"
    >
      <div className="glass rounded-[24px] p-7 shadow-soft">
        <Skeleton className="mb-4 h-5 w-24" />
        <Skeleton className="mb-4 h-7 w-3/4" />
        <div className="space-y-3">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      </div>
      <div className="space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="glass rounded-[20px] p-5 shadow-soft">
            <Skeleton className="mb-3 h-4 w-5/6" />
            <Skeleton className="mb-2 h-4 w-3/5" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </div>
        ))}
      </div>
      <span className="sr-only">
        The AI examiner is preparing your passage — this can take a minute.
      </span>
    </div>
  );
}

export function ListeningSkeleton() {
  return (
    <div
      className="space-y-6"
      role="status"
      aria-live="polite"
      aria-label="Loading listening practice"
    >
      <div className="glass flex items-center justify-between rounded-[24px] p-6 shadow-soft">
        <div className="flex items-center gap-4">
          <Skeleton className="size-11 rounded-2xl" />
          <Skeleton className="h-8 w-48" />
        </div>
        <Skeleton className="h-6 w-24 rounded-full" />
      </div>
      <div className="space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="glass rounded-[20px] p-5 shadow-soft">
            <Skeleton className="mb-3 h-4 w-5/6" />
            <Skeleton className="mb-2 h-4 w-3/5" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </div>
        ))}
      </div>
      <span className="sr-only">
        The AI examiner is producing your recording — this can take a minute.
      </span>
    </div>
  );
}

export function WritingSkeleton() {
  return (
    <div
      className="space-y-5"
      role="status"
      aria-live="polite"
      aria-label="Loading writing task"
    >
      <div className="flex flex-wrap items-center gap-3">
        <Skeleton className="h-10 w-72 rounded-2xl" />
        <Skeleton className="h-9 w-40 rounded-2xl" />
      </div>
      <Skeleton className="h-24 w-full rounded-2xl" />
      <Skeleton className="h-[360px] w-full rounded-[24px]" />
      <span className="sr-only">
        The AI examiner is preparing your task prompt.
      </span>
    </div>
  );
}
