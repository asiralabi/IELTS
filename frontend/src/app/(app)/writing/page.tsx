"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Wand2, Timer, Maximize2, Minimize2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { TaskType, Visual, WritingResult } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { BandFeedback, toStringArray } from "@/components/practice/band-feedback";
import { Visuals } from "@/components/practice/visual";
import { PracticeError } from "@/components/practice/practice-error";
import { CambridgeNav } from "@/components/practice/cambridge-nav";
import { WritingSkeleton } from "@/components/practice/skill-skeleton";
import { markCambridgeSectionDone } from "@/lib/cambridge-progress";
import { cn, formatDuration } from "@/lib/utils";

const TASK_INFO: Record<TaskType, { label: string; minWords: number; minutes: number }> = {
  task1: { label: "Task 1 — Report / Letter", minWords: 150, minutes: 20 },
  task2: { label: "Task 2 — Essay", minWords: 250, minutes: 40 },
};

function isVisual(value: unknown): value is Visual {
  if (!value || typeof value !== "object") return false;
  const kind = (value as { kind?: unknown }).kind;
  if (kind === "image") {
    return typeof (value as { url?: unknown }).url === "string";
  }
  if (kind === "chart") {
    return Array.isArray((value as { series?: unknown }).series);
  }
  return false;
}

type Phase = "write" | "marking" | "feedback" | "error";

export default function WritingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const bookParam = searchParams.get("book");
  const testParam = searchParams.get("test");
  const taskParam = searchParams.get("task");

  const [taskType, setTaskType] = React.useState<TaskType>("task2");
  const [prompt, setPrompt] = React.useState("");
  const [visual, setVisual] = React.useState<Visual | null>(null);
  const [essay, setEssay] = React.useState("");
  const [phase, setPhase] = React.useState<Phase>("write");
  const [result, setResult] = React.useState<WritingResult | null>(null);
  const [focusMode, setFocusMode] = React.useState(false);
  const [seconds, setSeconds] = React.useState(0);
  const [generating, setGenerating] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  React.useEffect(() => {
    const testNum = Number(testParam);
    const taskNum = Number(taskParam);
    if (!bookParam || !Number.isFinite(testNum) || !Number.isFinite(taskNum)) return;
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      setGenerating(true);
      try {
        const t = await api.cambridgeWriting(bookParam, testNum, taskNum);
        if (cancelled) return;
        setPrompt(t.prompt);
        setVisual(t.visual ?? null);
        setTaskType(taskNum === 1 ? "task1" : "task2");
      } catch (err) {
        if (cancelled) return;
        toast.error(
          err instanceof Error ? err.message : "Could not load Cambridge task."
        );
      } finally {
        if (!cancelled) setGenerating(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [bookParam, testParam, taskParam]);

  const clearCambridgeParams = React.useCallback(() => {
    if (bookParam || testParam || taskParam) {
      router.replace("/writing");
    }
  }, [bookParam, testParam, taskParam, router]);

  const info = TASK_INFO[taskType];
  const wordCount = essay.trim() ? essay.trim().split(/\s+/).length : 0;
  const timeLeft = info.minutes * 60 - seconds;

  React.useEffect(() => {
    if (phase !== "write" || !essay) return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase, essay]);

  const generatePrompt = async () => {
    clearCambridgeParams();
    setGenerating(true);
    try {
      const q = await api.generateQuestion({
        section: "writing",
        question_type: taskType,
      });
      const text =
        (typeof q.question === "string" && q.question) ||
        (typeof q.prompt === "string" && (q.prompt as string)) ||
        JSON.stringify(q);
      setPrompt(text);
      const rawVisual = (q as Record<string, unknown>).visual;
      setVisual(isVisual(rawVisual) ? rawVisual : null);
      toast.success("New prompt generated!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate a prompt.");
    } finally {
      setGenerating(false);
    }
  };

  const submit = async () => {
    if (!prompt.trim()) {
      toast.error("Add a task prompt first (or generate one).");
      return;
    }
    if (wordCount < 50) {
      toast.error("You need at least 50 words for the AI to give useful feedback.");
      return;
    }
    setPhase("marking");
    setErrorMsg(null);
    try {
      const res = await api.submitWriting({
        task_type: taskType,
        prompt: prompt.trim(),
        essay: essay.trim(),
        visual: visual,
      });
      setResult(res);
      setPhase("feedback");
      if (bookParam && testParam && taskParam) {
        markCambridgeSectionDone(
          bookParam,
          Number(testParam),
          "writing",
          Number(taskParam)
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Evaluation failed.";
      setErrorMsg(msg);
      setPhase("error");
    }
  };

  const dismissError = () => {
    setErrorMsg(null);
    setPhase("write");
  };

  const restart = () => {
    clearCambridgeParams();
    setPhase("write");
    setResult(null);
    setEssay("");
    setSeconds(0);
    setVisual(null);
    setPrompt("");
  };

  const editPrompt = (next: string) => {
    setPrompt(next);
    if (visual) setVisual(null);
  };

  const taskNumForNav = taskParam ? Number(taskParam) : null;

  return (
    <div className="mx-auto max-w-5xl">
      {!focusMode && <Topbar title="Writing" />}

      {!focusMode && (
        <CambridgeNav
          bookId={bookParam}
          testNumber={testParam ? Number(testParam) : null}
          skillKey="task"
          n={taskNumForNav}
          maxN={2}
        />
      )}

      <AnimatePresence mode="wait">
        {generating && phase === "write" && !prompt && (
          <motion.div key="cambridge-loading" exit={{ opacity: 0 }}>
            <WritingSkeleton />
          </motion.div>
        )}

        {phase === "marking" && (
          <motion.div key="marking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Marking your writing" />
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div key="error" exit={{ opacity: 0 }} className="pt-10">
            <PracticeError
              title="Couldn't grade your writing"
              message={errorMsg ?? "The examiner call failed. Your essay is safe — please try again."}
              onRetry={submit}
              onDismiss={dismissError}
              dismissLabel="Back to essay"
            />
          </motion.div>
        )}

        {phase === "feedback" && result && (
          <motion.div
            key="feedback"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            role="status"
            aria-live="polite"
          >
            <div className="mb-6 flex items-center justify-between">
              <Badge variant="accent">{info.label}</Badge>
              <Button variant="secondary" size="sm" onClick={restart}>
                <RotateCcw className="size-4" aria-hidden />
                Write another
              </Button>
            </div>
            <BandFeedback
              band={result.band_score}
              criteria={[
                { label: "Task Response", value: result.task_response },
                { label: "Coherence & Cohesion", value: result.coherence_cohesion },
                { label: "Lexical Resource", value: result.lexical_resource },
                { label: "Grammar Range & Accuracy", value: result.grammatical_range_accuracy },
              ]}
              feedback={typeof result.feedback === "string" ? result.feedback : undefined}
              strengths={toStringArray(result.strengths)}
              weaknesses={toStringArray(result.weaknesses)}
              suggestions={toStringArray(result.suggestions)}
            />
          </motion.div>
        )}

        {phase === "write" && (
          <motion.div
            key="write"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-5"
          >
            {!focusMode && (
              <div className="flex flex-wrap items-center gap-3">
                <div className="glass flex rounded-2xl p-1 shadow-soft">
                  {(Object.keys(TASK_INFO) as TaskType[]).map((t) => (
                    <button
                      key={t}
                      onClick={() => setTaskType(t)}
                      className={cn(
                        "rounded-xl px-4 py-2 text-sm font-medium transition-all",
                        taskType === t
                          ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {TASK_INFO[t].label}
                    </button>
                  ))}
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={generatePrompt}
                  loading={generating}
                >
                  <Wand2 className="size-4" aria-hidden />
                  Generate AI prompt
                </Button>
              </div>
            )}

            {!focusMode && visual && <Visuals visual={visual} />}

            {!focusMode && (
              <Textarea
                value={prompt}
                onChange={(e) => editPrompt(e.target.value)}
                placeholder="Paste or generate the task prompt here…"
                rows={3}
                aria-label="Task prompt"
              />
            )}

            <div className="glass rounded-[24px] p-1.5 shadow-soft">
              <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  {focusMode && (
                    <div className="flex overflow-hidden rounded-xl border border-border/40">
                      {(Object.keys(TASK_INFO) as TaskType[]).map((t) => (
                        <button
                          key={t}
                          onClick={() => setTaskType(t)}
                          className={cn(
                            "px-2.5 py-1 text-xs font-medium transition-all",
                            taskType === t
                              ? "bg-primary/15 text-primary"
                              : "text-muted-foreground hover:text-foreground"
                          )}
                          aria-label={`Switch to ${TASK_INFO[t].label}`}
                        >
                          {t === "task1" ? "T1" : "T2"}
                        </button>
                      ))}
                    </div>
                  )}
                  <Badge
                    variant={
                      wordCount >= info.minWords
                        ? "success"
                        : wordCount >= 50
                          ? "warning"
                          : "danger"
                    }
                  >
                    {wordCount} / {info.minWords}+ words
                  </Badge>
                  <span
                    className={cn(
                      "flex items-center gap-1.5 font-mono text-xs",
                      timeLeft < 300 ? "text-danger" : "text-muted-foreground"
                    )}
                  >
                    <Timer className="size-3.5" aria-hidden />
                    {timeLeft >= 0 ? formatDuration(timeLeft) : `-${formatDuration(-timeLeft)}`}
                  </span>
                </div>
                <button
                  onClick={() => setFocusMode((f) => !f)}
                  aria-label={focusMode ? "Exit focus mode" : "Enter focus mode"}
                  className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {focusMode ? (
                    <>
                      <Minimize2 className="size-3.5" aria-hidden /> Exit focus
                    </>
                  ) : (
                    <>
                      <Maximize2 className="size-3.5" aria-hidden /> Focus mode
                    </>
                  )}
                </button>
              </div>
              <Textarea
                value={essay}
                onChange={(e) => setEssay(e.target.value)}
                placeholder="Start writing your answer…"
                rows={focusMode ? 22 : 14}
                className="rounded-[20px] border-0 bg-transparent shadow-none focus:shadow-none"
                aria-label="Essay"
              />
            </div>

            <div className="flex items-center justify-end gap-3">
              {wordCount > 0 && wordCount < 50 && (
                <span className="text-xs text-muted-foreground">
                  {50 - wordCount} more word{50 - wordCount === 1 ? "" : "s"} to unlock marking
                </span>
              )}
              <Button size="lg" onClick={submit} disabled={wordCount < 50}>
                Submit for AI marking
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
