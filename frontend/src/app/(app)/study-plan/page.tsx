"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CalendarCheck, Crosshair } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { StudyPlan, WeaknessProfile } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { JsonContent } from "@/components/practice/json-content";
import { cn } from "@/lib/utils";

type Tab = "plan" | "weaknesses";

export default function StudyPlanPage() {
  const [tab, setTab] = React.useState<Tab>("plan");
  const [plan, setPlan] = React.useState<StudyPlan | null>(null);
  const [weaknesses, setWeaknesses] = React.useState<WeaknessProfile | null>(null);
  const [loading, setLoading] = React.useState(false);

  const load = async (which: Tab) => {
    setLoading(true);
    try {
      if (which === "plan") setPlan(await api.studyPlan());
      else setWeaknesses(await api.weaknesses());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not build the analysis.");
    } finally {
      setLoading(false);
    }
  };

  const current = tab === "plan" ? plan : weaknesses;

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Study Plan" />

      <div className="glass mb-6 inline-flex rounded-2xl p-1 shadow-soft">
        {(
          [
            { id: "plan", label: "Study Plan", icon: CalendarCheck },
            { id: "weaknesses", label: "Weakness Analysis", icon: Crosshair },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all",
              tab === t.id
                ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <t.icon className="size-4" aria-hidden />
            {t.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {loading ? (
          <motion.div key="loading" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-6">
            <ExaminerLoading
              label={tab === "plan" ? "Designing your study plan" : "Analysing your weaknesses"}
            />
          </motion.div>
        ) : current ? (
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-[28px] p-8 shadow-soft"
          >
            <JsonContent value={current} />
            <div className="mt-6 flex justify-end">
              <Button variant="secondary" size="sm" onClick={() => load(tab)}>
                Regenerate
              </Button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key={`${tab}-empty`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-strong rounded-[28px] p-10 text-center shadow-soft"
          >
            <h2 className="font-display text-xl font-bold">
              {tab === "plan"
                ? "A plan built from your real results"
                : "Find out exactly what is holding you back"}
            </h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              {tab === "plan"
                ? "The AI reviews your submissions and scores, then lays out what to practise and when."
                : "The AI scans your writing and speaking history for recurring grammar and vocabulary issues."}
            </p>
            <Button size="lg" className="mt-8" onClick={() => load(tab)}>
              {tab === "plan" ? "Build my study plan" : "Analyse my weaknesses"}
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
