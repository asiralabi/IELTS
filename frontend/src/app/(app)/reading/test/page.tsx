"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, RotateCcw, CheckCheck, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { FullReadingTest, FullTestResult } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { QuestionList } from "@/components/practice/question-list";
import { Visuals } from "@/components/practice/visual";
import { PracticeError } from "@/components/practice/practice-error";
import { ReadingSkeleton } from "@/components/practice/skill-skeleton";
import { BandRing } from "@/components/ui/progress";
import { formatBand } from "@/lib/utils";

type Phase = "start" | "generating" | "answering" | "checking" | "done" | "error";

export default function ReadingTestPage() {
  const router = useRouter();
  const [phase, setPhase] = React.useState<Phase>("start");
  const [test, setTest] = React.useState<FullReadingTest | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, string>>({});
  // Which question the student is on, so the figure can light that
  // blank. One at a time, so one piece of state covers every section.
  const [activeGap, setActiveGap] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<FullTestResult | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  const generate = async () => {
    setPhase("generating");
    setErrorMsg(null);
    try {
      const t = await api.readingFullTest();
      setTest(t);
      setAnswers({});
      setResult(null);
      setPhase("answering");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not generate the test.");
      setPhase("error");
    }
  };

  const submit = async () => {
    if (!test) return;
    setPhase("checking");
    setErrorMsg(null);
    try {
      const r = await api.readingFullTestCheck(test.practice_id, answers);
      setResult(r);
      setPhase("done");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not mark the test.");
      setPhase("error");
    }
  };

  const reset = () => {
    setTest(null);
    setAnswers({});
    setResult(null);
    setErrorMsg(null);
    setPhase("start");
  };

  const verdicts = React.useMemo(() => {
    const map: Record<string, { correct?: boolean; correct_answer?: string }> = {};
    for (const row of result?.results ?? []) {
      if (row.number != null) {
        map[String(row.number)] = {
          correct: row.correct,
          correct_answer: row.correct_answer,
        };
      }
    }
    return map;
  }, [result]);

  const totalQuestions = React.useMemo(
    () => (test?.passages ?? []).reduce((n, p) => n + (p.questions?.length ?? 0), 0),
    [test]
  );

  return (
    <div className="mx-auto max-w-5xl">
      <Topbar title="Full Reading Test" />

      <button
        onClick={() => router.push("/reading")}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back to Reading
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
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-emerald-500/20 to-teal-500/10 text-emerald-500">
              <BookOpen className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Full Reading Test</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              A complete IELTS Academic Reading paper — three passages that get
              harder as you go, numbered straight through, marked together for
              one band score.
            </p>
            <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground/80">
              Writing all three passages takes a few minutes.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate full test
            </Button>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="generating" exit={{ opacity: 0 }}>
            <div className="mb-6 text-center text-sm text-muted-foreground">
              Writing three passages and their questions…
            </div>
            <ReadingSkeleton />
          </motion.div>
        )}

        {phase === "checking" && (
          <motion.div key="checking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label={`Marking all ${totalQuestions} answers`} />
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

        {(phase === "answering" || phase === "done") && test && (
          <motion.div
            key="test"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-8"
            role="region"
            aria-live="polite"
          >
            {phase === "done" && result && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="glass-strong rounded-[28px] p-8 shadow-soft"
              >
                <div className="flex flex-col items-center gap-6 sm:flex-row sm:justify-between">
                  <div className="flex items-center gap-6">
                    <BandRing band={result.band_estimate ?? null} size={120} label="Band" />
                    <div>
                      <div className="font-display text-3xl font-bold">
                        {result.score ?? "—"}/{result.total ?? totalQuestions}
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
                    New test
                  </Button>
                </div>
                {result.passages && result.passages.length > 0 && (
                  <div className="mt-6 grid gap-3 sm:grid-cols-3">
                    {result.passages.map((p) => (
                      <div
                        key={p.passage_number}
                        className="rounded-2xl bg-muted/50 px-4 py-3 text-center"
                      >
                        <div className="text-xs text-muted-foreground">
                          Passage {p.passage_number}
                        </div>
                        <div className="font-display text-lg font-semibold">
                          {p.score ?? "—"}/{p.total ?? "—"}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}

            {(test.passages ?? []).map((passage) => {
              const questions = passage.questions ?? [];
              const first = questions[0]?.number;
              const last = questions[questions.length - 1]?.number;
              return (
                <section key={passage.passage_number} className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="accent" className="text-sm">
                      Passage {passage.passage_number}
                    </Badge>
                    {passage.title && (
                      <h3 className="font-display text-lg font-semibold">{passage.title}</h3>
                    )}
                    {first != null && last != null && (
                      <span className="text-xs text-muted-foreground">
                        Questions {first}–{last}
                      </span>
                    )}
                  </div>

                  <div className="grid gap-6 lg:grid-cols-2">
                    <div className="glass max-h-[70vh] overflow-y-auto rounded-[24px] p-7 shadow-soft lg:sticky lg:top-6">
                      <div className="whitespace-pre-wrap text-[15px] leading-[1.8] text-foreground/90">
                        {passage.passage}
                      </div>
                      <Visuals
                        activeGap={activeGap}
                        visual={passage.visual}
                        visuals={passage.visuals}
                        className="mt-5"
                      />
                    </div>

                    <QuestionList
                      onActiveQuestion={setActiveGap}
                      questions={questions}
                      answers={answers}
                      onAnswer={(k, v) => setAnswers((a) => ({ ...a, [k]: v }))}
                      disabled={phase === "done"}
                      results={phase === "done" ? verdicts : null}
                    />
                  </div>
                </section>
              );
            })}

            {phase === "answering" && (
              <div className="sticky bottom-4 flex justify-end">
                <Button
                  size="lg"
                  onClick={submit}
                  disabled={Object.keys(answers).length === 0}
                  className="shadow-glow"
                >
                  <CheckCheck className="size-4" aria-hidden />
                  Submit test ({Object.keys(answers).length}/{totalQuestions})
                </Button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
