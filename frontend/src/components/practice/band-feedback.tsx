"use client";

import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { CheckCircle2, AlertTriangle, Lightbulb } from "lucide-react";
import { BandRing, ProgressBar } from "@/components/ui/progress";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { formatBand } from "@/lib/utils";

export interface Criterion {
  label: string;
  value: number | null | undefined;
}

export function BandFeedback({
  band,
  criteria,
  feedback,
  strengths,
  weaknesses,
  suggestions,
}: {
  band: number | null | undefined;
  criteria: Criterion[];
  feedback?: string;
  strengths?: string[];
  weaknesses?: string[];
  suggestions?: string[];
}) {
  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
      className="space-y-6"
    >
      <motion.div
        variants={fadeUp}
        className="glass-strong flex flex-col items-center gap-6 rounded-[28px] p-8 shadow-soft sm:flex-row sm:justify-between"
      >
        <BandRing band={band ?? null} />
        <div className="w-full flex-1 space-y-4">
          {criteria.map((c) => (
            <div key={c.label}>
              <div className="mb-1.5 flex justify-between text-sm">
                <span className="text-muted-foreground">{c.label}</span>
                <span className="font-display font-semibold">{formatBand(c.value)}</span>
              </div>
              <ProgressBar value={c.value != null ? (c.value / 9) * 100 : 0} />
            </div>
          ))}
        </div>
      </motion.div>

      {feedback && (
        <motion.div variants={fadeUp} className="glass rounded-[24px] p-6 shadow-soft">
          <h3 className="mb-3 font-display font-semibold">Examiner Feedback</h3>
          <div className="prose-chat text-sm leading-relaxed text-muted-foreground">
            <ReactMarkdown>{feedback}</ReactMarkdown>
          </div>
        </motion.div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {strengths && strengths.length > 0 && (
          <motion.div variants={fadeUp} className="glass rounded-[24px] p-5 shadow-soft">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-success">
              <CheckCircle2 className="size-4" aria-hidden /> Strengths
            </h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              {strengths.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </motion.div>
        )}
        {weaknesses && weaknesses.length > 0 && (
          <motion.div variants={fadeUp} className="glass rounded-[24px] p-5 shadow-soft">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-warning">
              <AlertTriangle className="size-4" aria-hidden /> Weaknesses
            </h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              {weaknesses.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </motion.div>
        )}
        {suggestions && suggestions.length > 0 && (
          <motion.div variants={fadeUp} className="glass rounded-[24px] p-5 shadow-soft">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-primary">
              <Lightbulb className="size-4" aria-hidden /> Suggestions
            </h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              {suggestions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

export function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value
    .map((v) => (typeof v === "string" ? v : JSON.stringify(v)))
    .filter(Boolean);
}
