"use client";

import { CreditCard } from "lucide-react";

interface CueCardObject {
  topic?: string;
  bullets?: string[];
  closing?: string;
}

/** Type-guard for the structured Part 2 cue-card object. */
export function isCueCardObject(value: unknown): value is CueCardObject {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.topic === "string" ||
    Array.isArray(v.bullets) ||
    typeof v.closing === "string"
  );
}

export function CueCard({ question }: { question: string | CueCardObject }) {
  if (typeof question === "string") {
    return (
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
        {question}
      </p>
    );
  }

  const bullets = Array.isArray(question.bullets) ? question.bullets : [];
  return (
    <div className="glass-strong rounded-[20px] border border-primary/20 p-5 shadow-soft">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-primary">
        <CreditCard className="size-4" aria-hidden />
        Cue card
      </div>
      {question.topic && (
        <p className="font-display text-lg font-semibold leading-snug">
          {question.topic}
        </p>
      )}
      {bullets.length > 0 && (
        <>
          <p className="mt-4 text-xs text-muted-foreground">You should say:</p>
          <ul className="mt-2 space-y-1.5 text-sm">
            {bullets.map((b, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-primary" aria-hidden>
                  •
                </span>
                <span>{b}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {question.closing && (
        <p className="mt-4 text-sm text-muted-foreground">{question.closing}</p>
      )}
    </div>
  );
}
