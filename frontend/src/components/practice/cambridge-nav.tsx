"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";

type SkillKey = "passage" | "part" | "task";

const SKILL_TO_SEGMENT: Record<SkillKey, string> = {
  passage: "reading",
  part: "listening",
  task: "writing",
};

/**
 * Sticky "back to Cambridge" bar shown on skill pages when they were entered
 * via the Cambridge picker (i.e. `?book=...&test=...&<skillKey>=N`).
 *
 * - "Back to Cambridge" always visible.
 * - "Next" bumps the N param (or advances to the next test if `maxN` is set).
 * - Renders nothing when not in Cambridge mode.
 */
export function CambridgeNav({
  bookId,
  testNumber,
  skillKey,
  n,
  maxN,
}: {
  bookId: string | null;
  testNumber: number | null;
  skillKey: SkillKey;
  n: number | null;
  /** Optional upper bound — when known we disable "Next" at the end. */
  maxN?: number;
}) {
  const router = useRouter();
  if (!bookId || !testNumber || !n) return null;

  const segment = SKILL_TO_SEGMENT[skillKey];

  const goNext = () => {
    const nextN = n + 1;
    if (typeof maxN === "number" && nextN > maxN) {
      // Roll over to the first section of the next test — the endpoint will
      // 404 if it doesn't exist, and the page's error UI catches that.
      const params = new URLSearchParams({
        book: bookId,
        test: String(testNumber + 1),
        [skillKey]: "1",
      });
      router.replace(`/${segment}?${params.toString()}`);
      return;
    }
    const params = new URLSearchParams({
      book: bookId,
      test: String(testNumber),
      [skillKey]: String(nextN),
    });
    router.replace(`/${segment}?${params.toString()}`);
  };

  const atEnd = typeof maxN === "number" && n >= maxN;
  const nextLabel =
    skillKey === "passage"
      ? `Passage ${n + 1}`
      : skillKey === "part"
        ? `Part ${n + 1}`
        : `Task ${n + 1}`;

  return (
    <div className="glass mb-5 flex flex-wrap items-center justify-between gap-3 rounded-[20px] px-4 py-2.5 text-sm shadow-soft">
      <Link
        href="/cambridge"
        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to Cambridge
      </Link>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="hidden sm:inline">
          {bookId} · Test {testNumber} · {skillKey} {n}
        </span>
        <button
          type="button"
          onClick={goNext}
          className="inline-flex items-center gap-1.5 rounded-xl bg-primary/10 px-3 py-1.5 font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
        >
          Next {atEnd ? "test" : nextLabel}
          <ArrowRight className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}
