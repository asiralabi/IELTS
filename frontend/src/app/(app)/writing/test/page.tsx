"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { PenLine, RotateCcw, CheckCheck, ArrowLeft, Timer } from "lucide-react";
import { api } from "@/lib/api";
import type {
  FullWritingTask,
  FullWritingTest,
  FullWritingTestResult,
  TaskType,
  Visual,
} from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { BandFeedback, toStringArray } from "@/components/practice/band-feedback";
import { Visuals } from "@/components/practice/visual";
import { PracticeError } from "@/components/practice/practice-error";
import { WritingSkeleton } from "@/components/practice/skill-skeleton";
import { BandRing } from "@/components/ui/progress";
import { cn, formatBand, formatDuration } from "@/lib/utils";

type Phase = "start" | "generating" | "writing" | "marking" | "done" | "error";

// The paper is one hour, and a candidate who spends it all on Task 2 has
// thrown away a third of the mark. Counting down per task is the only way the
// split is visible while writing.
const PAPER_MINUTES = 60;

function promptText(task: FullWritingTask): string {
  const q = task.question;
  if (typeof q === "string") return q;
  if (q == null) return "";
  return JSON.stringify(q, null, 2);
}

export default function WritingTestPage() {
  const router = useRouter();
  const [phase, setPhase] = React.useState<Phase>("start");
  const [test, setTest] = React.useState<FullWritingTest | null>(null);
  const [essays, setEssays] = React.useState<Partial<Record<TaskType, string>>>({});
  const [active, setActive] = React.useState<TaskType>("task1");
  const [result, setResult] = React.useState<FullWritingTestResult | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [seconds, setSeconds] = React.useState(0);

  React.useEffect(() => {
    if (phase !== "writing") return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase]);

  const generate = async () => {
    setPhase("generating");
    setErrorMsg(null);
    try {
      const t = await api.writingFullTest();
      setTest(t);
      setEssays({});
      setResult(null);
      setActive((t.tasks[0]?.task as TaskType) ?? "task1");
      setSeconds(0);
      setPhase("writing");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not generate the paper.");
      setPhase("error");
    }
  };

  const submit = async () => {
    if (!test) return;
    setPhase("marking");
    setErrorMsg(null);
    try {
      const payload: Partial<
        Record<TaskType, { prompt: string; essay: string; visual?: Visual | null }>
      > = {};
      for (const task of test.tasks) {
        const essay = (essays[task.task] ?? "").trim();
        // The examiner rejects anything under 50 words, and one unwritten task
        // must not take the other down with it.
        if (essay.split(/\s+/).filter(Boolean).length < 50) continue;
        payload[task.task] = {
          prompt: promptText(task),
          essay,
          visual: (task.visual as Visual) ?? null,
        };
      }
      const r = await api.writingFullTestSubmit(payload);
      setResult(r);
      setPhase("done");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not mark the paper.");
      setPhase("error");
    }
  };

  const reset = () => {
    setTest(null);
    setEssays({});
    setResult(null);
    setErrorMsg(null);
    setPhase("start");
  };

  const wordCounts = React.useMemo(() => {
    const counts: Partial<Record<TaskType, number>> = {};
    for (const [key, essay] of Object.entries(essays)) {
      counts[key as TaskType] = essay.trim()
        ? essay.trim().split(/\s+/).length
        : 0;
    }
    return counts;
  }, [essays]);

  const readyTasks = (test?.tasks ?? []).filter(
    (t) => (wordCounts[t.task] ?? 0) >= 50
  ).length;
  const timeLeft = PAPER_MINUTES * 60 - seconds;
  const activeTask = (test?.tasks ?? []).find((t) => t.task === active);

  return (
    <div className="mx-auto max-w-5xl">
      <Topbar title="Full Writing Test" />

      <button
        onClick={() => router.push("/writing")}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back to Writing
      </button>

      <AnimatePresence mode="wait">
        {phase === "start" && (
          <motion.div
            key="start"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="glass-strong mx-auto max-w-xl rounded-[28px] p-10 text-center shadow-soft"
          >
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-violet-500/20 to-fuchsia-500/10 text-violet-500">
              <PenLine className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Full Writing Test</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              A complete IELTS Academic Writing paper — a Task 1 chart report and
              a Task 2 essay, one hour, marked together for one band. Task 2 is
              worth twice Task 1, exactly as in the real exam.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate full test
            </Button>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="generating" exit={{ opacity: 0 }}>
            <div className="mb-6 text-center text-sm text-muted-foreground">
              Setting both tasks…
            </div>
            <WritingSkeleton />
          </motion.div>
        )}

        {phase === "marking" && (
          <motion.div key="marking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Marking both tasks" />
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div key="error" exit={{ opacity: 0 }} className="pt-10">
            <PracticeError
              title="Something went wrong"
              message={errorMsg ?? "Please try again."}
              onRetry={test ? submit : generate}
              onDismiss={reset}
              dismissLabel="Start over"
            />
          </motion.div>
        )}

        {phase === "done" && result && (
          <motion.div
            key="done"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-8"
            role="status"
            aria-live="polite"
          >
            <div className="glass-strong flex flex-col items-center gap-6 rounded-[28px] p-8 shadow-soft sm:flex-row sm:justify-between">
              <div className="flex items-center gap-6">
                <BandRing band={result.overall_band} size={120} label="Band" />
                <div>
                  <p className="text-sm text-muted-foreground">Writing paper</p>
                  {result.overall_band != null && (
                    <Badge className="mt-2">
                      Estimated band {formatBand(result.overall_band)}
                    </Badge>
                  )}
                </div>
              </div>
              <Button variant="secondary" onClick={generate}>
                <RotateCcw className="size-4" aria-hidden />
                New test
              </Button>
            </div>

            {(test?.tasks ?? []).map((task) => {
              const marked = result.tasks[task.task];
              if (!marked) return null;
              return (
                <section key={task.task} className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="accent" className="text-sm">
                      {task.label}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {marked.word_count} words
                    </span>
                  </div>
                  <BandFeedback
                    band={marked.band_score}
                    criteria={[
                      { label: "Task Response", value: marked.task_response },
                      { label: "Coherence & Cohesion", value: marked.coherence_cohesion },
                      { label: "Lexical Resource", value: marked.lexical_resource },
                      {
                        label: "Grammar Range & Accuracy",
                        value: marked.grammatical_range_accuracy,
                      },
                    ]}
                    feedback={
                      typeof marked.feedback === "string" ? marked.feedback : undefined
                    }
                    strengths={toStringArray(marked.strengths)}
                    weaknesses={toStringArray(marked.weaknesses)}
                    suggestions={toStringArray(marked.suggestions)}
                  />
                </section>
              );
            })}
          </motion.div>
        )}

        {phase === "writing" && test && activeTask && (
          <motion.div
            key="writing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="glass flex rounded-2xl p-1 shadow-soft">
                {test.tasks.map((task) => (
                  <button
                    key={task.task}
                    onClick={() => setActive(task.task)}
                    className={cn(
                      "rounded-xl px-4 py-2 text-sm font-medium transition-all",
                      active === task.task
                        ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {task.label}
                  </button>
                ))}
              </div>
              <span
                className={cn(
                  "flex items-center gap-1.5 font-mono text-xs",
                  timeLeft < 300 ? "text-danger" : "text-muted-foreground"
                )}
              >
                <Timer className="size-3.5" aria-hidden />
                {timeLeft >= 0
                  ? formatDuration(timeLeft)
                  : `-${formatDuration(-timeLeft)}`}
              </span>
            </div>

            <div className="glass rounded-[24px] p-6 shadow-soft">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <h3 className="font-display font-semibold">{activeTask.label}</h3>
                <span className="text-xs text-muted-foreground">
                  ~{activeTask.minutes} minutes · at least {activeTask.min_words} words
                </span>
              </div>
              <p className="whitespace-pre-wrap text-[15px] leading-[1.8] text-foreground/90">
                {promptText(activeTask)}
              </p>
              <Visuals visual={activeTask.visual} className="mt-5" />
            </div>

            <div className="glass rounded-[24px] p-1.5 shadow-soft">
              <div className="flex items-center justify-between px-4 py-2.5">
                <Badge
                  variant={
                    (wordCounts[active] ?? 0) >= activeTask.min_words
                      ? "success"
                      : (wordCounts[active] ?? 0) >= 50
                        ? "warning"
                        : "danger"
                  }
                >
                  {wordCounts[active] ?? 0} / {activeTask.min_words}+ words
                </Badge>
              </div>
              <Textarea
                value={essays[active] ?? ""}
                onChange={(e) =>
                  setEssays((prev) => ({ ...prev, [active]: e.target.value }))
                }
                placeholder="Write your answer…"
                rows={16}
                className="rounded-[20px] border-0 bg-transparent shadow-none focus:shadow-none"
                aria-label={`${activeTask.label} answer`}
              />
            </div>

            <div className="sticky bottom-4 flex justify-end">
              <Button
                size="lg"
                onClick={submit}
                disabled={readyTasks === 0}
                className="shadow-glow"
              >
                <CheckCheck className="size-4" aria-hidden />
                Submit test ({readyTasks}/{test.tasks.length})
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
