"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Headphones,
  RotateCcw,
  CheckCheck,
  Eye,
  EyeOff,
  FileText,
  ArrowLeft,
} from "lucide-react";
import { api } from "@/lib/api";
import type { FullListeningTest, FullTestResult } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { QuestionList } from "@/components/practice/question-list";
import { Visuals } from "@/components/practice/visual";
import { PracticeError } from "@/components/practice/practice-error";
import { ListeningSkeleton } from "@/components/practice/skill-skeleton";
import { NeuralAudioPlayer } from "@/components/practice/neural-audio-player";
import { BandRing } from "@/components/ui/progress";
import { formatBand } from "@/lib/utils";

type Phase = "start" | "generating" | "answering" | "checking" | "done" | "error";

export default function ListeningTestPage() {
  const router = useRouter();
  const [phase, setPhase] = React.useState<Phase>("start");
  const [test, setTest] = React.useState<FullListeningTest | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<FullTestResult | null>(null);
  const [openTranscripts, setOpenTranscripts] = React.useState<Record<number, boolean>>({});
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  const generate = async () => {
    setPhase("generating");
    setErrorMsg(null);
    try {
      const t = await api.listeningFullTest();
      setTest(t);
      setAnswers({});
      setResult(null);
      setOpenTranscripts({});
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
      const r = await api.listeningFullTestCheck(test.practice_id, answers);
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
    setOpenTranscripts({});
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
    () => (test?.parts ?? []).reduce((n, p) => n + (p.questions?.length ?? 0), 0),
    [test]
  );

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Full Listening Test" />

      <button
        onClick={() => router.push("/listening")}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back to Listening
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
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-sky-500/20 to-blue-500/10 text-sky-500">
              <Headphones className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Full Listening Test</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              A complete IELTS Listening test — 4 parts, 40 questions, each with
              its own recording and figures. The AI writes the whole test,
              multi-voice neural narration plays each recording, and you get a
              band score at the end.
            </p>
            <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground/80">
              Generating all four parts takes a minute or two.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate full test
            </Button>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="generating" exit={{ opacity: 0 }}>
            <div className="mb-6 text-center text-sm text-muted-foreground">
              Writing 4 parts, 40 questions, scripts and figures…
            </div>
            <ListeningSkeleton />
          </motion.div>
        )}

        {phase === "checking" && (
          <motion.div key="checking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Marking all 40 answers" />
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
            className="space-y-6"
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
                {result.parts && result.parts.length > 0 && (
                  <div className="mt-6 grid gap-3 sm:grid-cols-4">
                    {result.parts.map((p) => (
                      <div
                        key={p.part}
                        className="rounded-2xl bg-muted/50 px-4 py-3 text-center"
                      >
                        <div className="text-xs text-muted-foreground">Part {p.part}</div>
                        <div className="font-display text-lg font-semibold">
                          {p.score ?? "—"}/{p.total ?? 10}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}

            {(test.parts ?? []).map((part) => {
              const questions = part.questions ?? [];
              const transcriptOpen = !!openTranscripts[part.part];
              return (
                <section key={part.part} className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant="accent" className="text-sm">
                      Part {part.part}
                    </Badge>
                    {part.title && (
                      <h3 className="font-display text-lg font-semibold">{part.title}</h3>
                    )}
                    <span className="text-xs text-muted-foreground">
                      Questions {(part.part - 1) * 10 + 1}–{(part.part - 1) * 10 + questions.length}
                    </span>
                  </div>

                  {part.audio_script ? (
                    <>
                      <div className="glass flex flex-wrap items-center justify-between gap-4 rounded-[24px] p-6 shadow-soft">
                        <div className="flex items-center gap-4">
                          <NeuralAudioPlayer
                            practiceId={test.practice_id}
                            part={part.part}
                            disabled={phase === "done"}
                          />
                          <span className="text-xs text-muted-foreground">
                            Recording {part.part} of 4
                          </span>
                        </div>
                        <button
                          onClick={() =>
                            setOpenTranscripts((o) => ({ ...o, [part.part]: !o[part.part] }))
                          }
                          className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          {transcriptOpen ? (
                            <>
                              <EyeOff className="size-3.5" aria-hidden /> Hide transcript
                            </>
                          ) : (
                            <>
                              <Eye className="size-3.5" aria-hidden /> Show transcript
                            </>
                          )}
                        </button>
                      </div>

                      {transcriptOpen && (
                        <div className="glass overflow-hidden rounded-[24px] p-6 shadow-soft">
                          <Badge variant="secondary" className="mb-3">
                            Transcript
                          </Badge>
                          <div className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                            {part.audio_script}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="glass flex items-start gap-3 rounded-[24px] p-5 shadow-soft">
                      <FileText className="mt-0.5 size-5 shrink-0 text-amber-500" aria-hidden />
                      <p className="text-sm text-muted-foreground">
                        No recording for this part — answer from the printed material below.
                      </p>
                    </div>
                  )}

                  <Visuals visual={part.visual} visuals={part.visuals} />

                  <QuestionList
                    questions={questions}
                    answers={answers}
                    onAnswer={(k, v) => setAnswers((a) => ({ ...a, [k]: v }))}
                    disabled={phase === "done"}
                    results={phase === "done" ? verdicts : null}
                  />
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
