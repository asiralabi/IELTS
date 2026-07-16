"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Headphones, RotateCcw, CheckCheck, Eye, EyeOff, Info, FileText } from "lucide-react";
import { toast } from "sonner";
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
import { ListeningSkeleton } from "@/components/practice/skill-skeleton";
import { NeuralAudioPlayer } from "@/components/practice/neural-audio-player";
import { BandRing } from "@/components/ui/progress";
import { markCambridgeSectionDone } from "@/lib/cambridge-progress";
import { formatBand } from "@/lib/utils";

type Phase = "start" | "generating" | "answering" | "checking" | "done" | "error";
type ErrorKind = "generate" | "check";

export default function ListeningPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const bookParam = searchParams.get("book");
  const testParam = searchParams.get("test");
  const partParam = searchParams.get("part");

  const [phase, setPhase] = React.useState<Phase>("start");
  const [practice, setPractice] = React.useState<PracticeSet | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<CheckResult | null>(null);
  const [playsUsed, setPlaysUsed] = React.useState(0);
  const [showScript, setShowScript] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [errorKind, setErrorKind] = React.useState<ErrorKind>("generate");

  React.useEffect(() => {
    const testNum = Number(testParam);
    const partNum = Number(partParam);
    if (!bookParam || !Number.isFinite(testNum) || !Number.isFinite(partNum)) return;
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      setPhase("generating");
      setErrorMsg(null);
      try {
        const p = await api.cambridgeListening(bookParam, testNum, partNum);
        if (cancelled) return;
        setPractice(p);
        setAnswers({});
        setResult(null);
        setPlaysUsed(0);
        setShowScript(false);
        setPhase("answering");
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "Could not load Cambridge listening.";
        setErrorMsg(msg);
        setErrorKind("generate");
        setPhase("error");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [bookParam, testParam, partParam]);

  const clearCambridgeParams = React.useCallback(() => {
    if (bookParam || testParam || partParam) {
      router.replace("/listening");
    }
  }, [bookParam, testParam, partParam, router]);

  const generate = async () => {
    clearCambridgeParams();
    setPhase("generating");
    setErrorMsg(null);
    try {
      const p = await api.listeningPractice();
      setPractice(p);
      setAnswers({});
      setResult(null);
      setPlaysUsed(0);
      setShowScript(false);
      setPhase("answering");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not generate a recording.";
      setErrorMsg(msg);
      setErrorKind("generate");
      setPhase("error");
    }
  };

  const canPlay = () => {
    if (playsUsed >= 2) {
      toast.warning("IELTS rules: you have used both plays. Answer from memory!");
      return false;
    }
    return true;
  };

  const check = async () => {
    if (!practice) return;
    setPhase("checking");
    setErrorMsg(null);
    try {
      const r = await api.listeningCheck(practice.practice_id, answers);
      setResult(r);
      // Don't auto-reveal the transcript — the button stays available so the
      // user can view it deliberately. (The button is unlocked once graded.)
      setPhase("done");
      if (bookParam && testParam && partParam) {
        markCambridgeSectionDone(
          bookParam,
          Number(testParam),
          "listening",
          Number(partParam)
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
    setPlaysUsed(0);
    setShowScript(false);
    setErrorMsg(null);
    setPhase("start");
  };

  const questions = practice?.questions ?? [];
  const partNum = partParam ? Number(partParam) : null;

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Listening" />

      <CambridgeNav
        bookId={bookParam}
        testNumber={testParam ? Number(testParam) : null}
        skillKey="part"
        n={partNum}
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
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-sky-500/20 to-blue-500/10 text-sky-500">
              <Headphones className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Listening Practice</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              The AI writes an IELTS-style recording script, multi-voice neural
              narration reads it aloud, and — just like the real test — you only
              get two plays.
            </p>
            <div className="mt-8 flex flex-col items-center gap-3">
              <Button size="lg" onClick={generate}>
                Generate a recording
              </Button>
              <button
                onClick={() => router.push("/listening/test")}
                className="text-sm font-medium text-primary transition-colors hover:text-primary/80"
              >
                Or take a full test — 4 parts, 40 questions →
              </button>
            </div>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="generating" exit={{ opacity: 0 }}>
            <ListeningSkeleton />
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
                  : "Couldn't load a recording"
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
              >
                <div className="flex items-center gap-6">
                  <BandRing band={result.band_estimate ?? null} size={110} label="Band est." />
                  <div>
                    <div className="font-display text-3xl font-bold">
                      {result.score ?? "—"}/{result.total ?? questions.length}
                    </div>
                    <p className="text-sm text-muted-foreground">correct answers</p>
                    {result.band_estimate != null && (
                      <Badge className="mt-2">Estimated band {formatBand(result.band_estimate)}</Badge>
                    )}
                  </div>
                </div>
                <Button variant="secondary" onClick={generate}>
                  <RotateCcw className="size-4" aria-hidden />
                  New recording
                </Button>
              </motion.div>
            )}

            {/* Paper-based test — no audio available (Cambridge scanned PDFs, etc.) */}
            {!practice.audio_script && (
              <div className="glass-strong flex flex-col gap-3 rounded-[24px] p-6 shadow-soft sm:flex-row sm:items-start">
                <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 text-amber-500">
                  <FileText className="size-5" aria-hidden />
                </span>
                <div className="flex-1">
                  <h3 className="font-display text-base font-semibold">
                    Paper-based Cambridge test
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {practice.note ??
                      "Audio isn't included with this Cambridge test — the questions test the same skills using the visuals and prompts below. Read carefully and answer as directed."}
                  </p>
                </div>
              </div>
            )}

            {/* Player — only when there's an audio script to read */}
            {practice.audio_script && (
              <>
                <div className="glass flex flex-wrap items-center justify-between gap-4 rounded-[24px] p-6 shadow-soft">
                  <NeuralAudioPlayer
                    practiceId={practice.practice_id}
                    disabled={phase === "done"}
                    canPlay={canPlay}
                    onPlayStart={() => setPlaysUsed((n) => n + 1)}
                  />
                  <div className="flex items-center gap-3">
                    <Badge variant={playsUsed >= 2 ? "danger" : "accent"}>
                      Plays used: {playsUsed}/2
                    </Badge>
                    <button
                      onClick={() => setShowScript((s) => !s)}
                      className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      {showScript ? (
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
                </div>

                {showScript && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="glass overflow-hidden rounded-[24px] p-6 shadow-soft"
                  >
                    <Badge variant="secondary" className="mb-3">
                      Transcript
                    </Badge>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                      {practice.audio_script}
                    </div>
                  </motion.div>
                )}
              </>
            )}

            {practice.note && practice.audio_script && (
              <div className="glass flex items-start gap-3 rounded-[24px] p-4 text-sm shadow-soft">
                <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                <span className="text-muted-foreground">{practice.note}</span>
              </div>
            )}

            <Visuals visual={practice.visual} visuals={practice.visuals} />

            <QuestionList
              questions={questions}
              answers={answers}
              onAnswer={(k, v) => setAnswers((a) => ({ ...a, [k]: v }))}
              disabled={phase === "done"}
            />

            {phase === "answering" && (
              <div className="flex justify-end">
                <Button size="lg" onClick={check} disabled={Object.keys(answers).length === 0}>
                  <CheckCheck className="size-4" aria-hidden />
                  Check answers
                </Button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
