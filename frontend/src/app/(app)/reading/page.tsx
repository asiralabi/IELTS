"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, RotateCcw, CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { CheckResult, PracticeSet } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { QuestionList } from "@/components/practice/question-list";
import { Visuals } from "@/components/practice/visual";
import { PracticeError } from "@/components/practice/practice-error";
import { CambridgeNav } from "@/components/practice/cambridge-nav";
import { ReadingSkeleton } from "@/components/practice/skill-skeleton";
import { BandRing } from "@/components/ui/progress";
import { markCambridgeSectionDone } from "@/lib/cambridge-progress";
import { cn, formatBand } from "@/lib/utils";

type Phase = "start" | "generating" | "answering" | "checking" | "done" | "error";
type ErrorKind = "generate" | "check";
type MobileTab = "passage" | "questions";

export default function ReadingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const bookParam = searchParams.get("book");
  const testParam = searchParams.get("test");
  const passageParam = searchParams.get("passage");

  const [phase, setPhase] = React.useState<Phase>("start");
  const [practice, setPractice] = React.useState<PracticeSet | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<CheckResult | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [errorKind, setErrorKind] = React.useState<ErrorKind>("generate");
  const [mobileTab, setMobileTab] = React.useState<MobileTab>("passage");

  React.useEffect(() => {
    const testNum = Number(testParam);
    const passageNum = Number(passageParam);
    if (!bookParam || !Number.isFinite(testNum) || !Number.isFinite(passageNum)) return;
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      setPhase("generating");
      setErrorMsg(null);
      try {
        const p = await api.cambridgeReading(bookParam, testNum, passageNum);
        if (cancelled) return;
        setPractice(p);
        setAnswers({});
        setResult(null);
        setPhase("answering");
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "Could not load Cambridge passage.";
        setErrorMsg(msg);
        setErrorKind("generate");
        setPhase("error");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [bookParam, testParam, passageParam]);

  const clearCambridgeParams = React.useCallback(() => {
    if (bookParam || testParam || passageParam) {
      router.replace("/reading");
    }
  }, [bookParam, testParam, passageParam, router]);

  const generate = async () => {
    clearCambridgeParams();
    setPhase("generating");
    setErrorMsg(null);
    try {
      const p = await api.readingPractice();
      setPractice(p);
      setAnswers({});
      setResult(null);
      setPhase("answering");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not generate a passage.";
      setErrorMsg(msg);
      setErrorKind("generate");
      setPhase("error");
    }
  };

  const check = async () => {
    if (!practice) return;
    setPhase("checking");
    setErrorMsg(null);
    try {
      const r = await api.readingCheck(practice.practice_id, answers);
      setResult(r);
      setPhase("done");
      if (bookParam && testParam && passageParam) {
        markCambridgeSectionDone(
          bookParam,
          Number(testParam),
          "reading",
          Number(passageParam)
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not check answers.";
      setErrorMsg(msg);
      setErrorKind("check");
      setPhase("error");
    }
  };

  const retry = () => {
    if (errorKind === "check") check();
    else generate();
  };

  const resetToStart = () => {
    clearCambridgeParams();
    setPractice(null);
    setAnswers({});
    setResult(null);
    setErrorMsg(null);
    setPhase("start");
  };

  const questions = practice?.questions ?? [];
  const passageNum = passageParam ? Number(passageParam) : null;

  return (
    <div className="mx-auto max-w-6xl">
      <Topbar title="Reading" />

      <CambridgeNav
        bookId={bookParam}
        testNumber={testParam ? Number(testParam) : null}
        skillKey="passage"
        n={passageNum}
      />

      <AnimatePresence mode="wait">
        {phase === "start" && (
          <motion.div
            key="start"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="glass-strong mx-auto max-w-xl rounded-[28px] p-10 text-center shadow-soft"
          >
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-violet-500/20 to-purple-500/10 text-violet-500">
              <BookOpen className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Academic Reading Practice</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              The AI will write a fresh IELTS-style passage with authentic
              question types, then mark your answers instantly.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate a passage
            </Button>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="loading" exit={{ opacity: 0 }}>
            <ReadingSkeleton />
          </motion.div>
        )}

        {phase === "checking" && (
          <motion.div key="checking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Checking your answers" />
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div key="error" exit={{ opacity: 0 }} className="pt-10">
            <PracticeError
              title={
                errorKind === "check"
                  ? "Couldn't check your answers"
                  : "Couldn't load a passage"
              }
              message={errorMsg ?? "Something went wrong. Please try again."}
              onRetry={retry}
              onDismiss={resetToStart}
              dismissLabel={errorKind === "check" ? "Back to questions" : "Start over"}
            />
          </motion.div>
        )}

        {(phase === "answering" || phase === "done") && practice && (
          <motion.div
            key="practice"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-6"
            role="region"
            aria-live="polite"
          >
            {phase === "done" && result && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="glass-strong flex flex-col items-center gap-6 rounded-[28px] p-8 shadow-soft sm:flex-row sm:justify-between"
                role="status"
                aria-live="polite"
              >
                <div className="flex items-center gap-6">
                  <BandRing
                    band={result.band_estimate ?? null}
                    size={110}
                    label="Band est."
                  />
                  <div>
                    <div className="font-display text-3xl font-bold">
                      {result.score ?? "—"}/{result.total ?? questions.length}
                    </div>
                    <p className="text-sm text-muted-foreground">correct answers</p>
                    {result.band_estimate != null && (
                      <Badge className="mt-2">
                        Estimated band {formatBand(result.band_estimate)}
                      </Badge>
                    )}
                  </div>
                </div>
                <Button variant="secondary" onClick={generate}>
                  <RotateCcw className="size-4" aria-hidden />
                  New passage
                </Button>
              </motion.div>
            )}

            {/* Mobile tab switcher — hidden at lg+ where side-by-side works. */}
            <div
              role="tablist"
              aria-label="Passage and questions"
              className="glass flex rounded-2xl p-1 shadow-soft lg:hidden"
            >
              {(
                [
                  { id: "passage", label: "Passage" },
                  { id: "questions", label: "Questions" },
                ] as { id: MobileTab; label: string }[]
              ).map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={mobileTab === t.id}
                  aria-controls={`panel-${t.id}`}
                  id={`tab-${t.id}`}
                  onClick={() => setMobileTab(t.id)}
                  className={cn(
                    "flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-all",
                    mobileTab === t.id
                      ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              {/* Passage */}
              <div
                id="panel-passage"
                role="tabpanel"
                aria-labelledby="tab-passage"
                className={cn(
                  "glass max-h-[70vh] overflow-y-auto rounded-[24px] p-7 shadow-soft lg:sticky lg:top-6 lg:block",
                  mobileTab === "passage" ? "block" : "hidden lg:block"
                )}
              >
                <Badge variant="secondary" className="mb-3">
                  Passage
                </Badge>
                <h2 className="font-display text-xl font-semibold">
                  {practice.title ?? "Reading Passage"}
                </h2>
                <div className="mt-4 whitespace-pre-wrap text-[15px] leading-[1.8] text-foreground/90">
                  {practice.passage}
                </div>
                <Visuals
                  visual={practice.visual}
                  visuals={practice.visuals}
                  className="mt-5"
                />
              </div>

              {/* Questions */}
              <div
                id="panel-questions"
                role="tabpanel"
                aria-labelledby="tab-questions"
                className={cn(
                  "lg:block",
                  mobileTab === "questions" ? "block" : "hidden lg:block"
                )}
              >
                <QuestionList
                  questions={questions}
                  answers={answers}
                  onAnswer={(k, v) => setAnswers((a) => ({ ...a, [k]: v }))}
                  disabled={phase === "done"}
                />
                {phase === "answering" && (
                  <div className="mt-6 flex justify-end">
                    <Button
                      size="lg"
                      onClick={check}
                      disabled={Object.keys(answers).length === 0}
                    >
                      <CheckCheck className="size-4" aria-hidden />
                      Check answers
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
