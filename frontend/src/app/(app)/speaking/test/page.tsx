"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Square, RotateCcw, CheckCheck, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type {
  FullSpeakingPart,
  FullSpeakingTest,
  FullSpeakingTestResult,
  SpeakingPart,
} from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { BandFeedback, toStringArray } from "@/components/practice/band-feedback";
import { CueCard, isCueCardObject } from "@/components/practice/cue-card";
import { Part2Timer } from "@/components/practice/speaking-timers";
import { PracticeError } from "@/components/practice/practice-error";
import { WritingSkeleton } from "@/components/practice/skill-skeleton";
import { BandRing } from "@/components/ui/progress";
import { cn, formatBand } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */
type SpeechRecognitionLike = {
  new (): {
    continuous: boolean;
    interimResults: boolean;
    lang: string;
    onresult: (event: any) => void;
    onerror: (event: any) => void;
    onend: () => void;
    start(): void;
    stop(): void;
  };
};

function getSpeechRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

type Phase = "start" | "generating" | "interview" | "marking" | "done" | "error";

// The examiner needs enough speech to place a band; below this the transcript
// is a fragment, not an answer.
const MIN_WORDS = 5;

function questionLines(part: FullSpeakingPart): string[] {
  const q = part.question;
  if (typeof q === "string") return [q];
  if (Array.isArray(q)) {
    return q.flatMap((entry) => {
      if (typeof entry === "string") return [entry];
      const topic = (entry as { topic?: unknown }).topic;
      const questions = (entry as { questions?: unknown }).questions;
      const asked = Array.isArray(questions) ? questions.map(String) : [];
      return typeof topic === "string" ? [`${topic}:`, ...asked] : asked;
    });
  }
  return [];
}

export default function SpeakingTestPage() {
  const router = useRouter();
  const [phase, setPhase] = React.useState<Phase>("start");
  const [test, setTest] = React.useState<FullSpeakingTest | null>(null);
  const [active, setActive] = React.useState<SpeakingPart>("part1");
  const [transcripts, setTranscripts] = React.useState<
    Partial<Record<SpeakingPart, string>>
  >({});
  const [result, setResult] = React.useState<FullSpeakingTestResult | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);
  const [recording, setRecording] = React.useState(false);
  const recognitionRef = React.useRef<InstanceType<SpeechRecognitionLike> | null>(null);
  const supported = React.useMemo(() => getSpeechRecognition() !== null, []);

  React.useEffect(() => {
    return () => recognitionRef.current?.stop();
  }, []);

  const stopRecording = React.useCallback(() => {
    recognitionRef.current?.stop();
    setRecording(false);
  }, []);

  const startRecording = React.useCallback(() => {
    const SR = getSpeechRecognition();
    if (!SR) {
      toast.info("Live transcription needs Chrome or Edge — type your answer instead.");
      return;
    }
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = "en-US";
    rec.onresult = (event: any) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) text += event.results[i][0].transcript + " ";
      }
      if (!text) return;
      setTranscripts((prev) => ({
        ...prev,
        [active]: (prev[active] ? prev[active] + " " : "") + text.trim(),
      }));
    };
    rec.onerror = (event: any) => {
      if (event.error === "not-allowed") {
        toast.error("Microphone access denied — type your answer instead.");
      }
      setRecording(false);
    };
    rec.onend = () => setRecording(false);
    recognitionRef.current = rec;
    rec.start();
    setRecording(true);
  }, [active]);

  // Switching parts mid-recording would file the new part's speech under the
  // old one — the recogniser is bound to whichever part was active.
  const selectPart = (part: SpeakingPart) => {
    stopRecording();
    setActive(part);
  };

  const generate = async () => {
    setPhase("generating");
    setErrorMsg(null);
    try {
      const t = await api.speakingFullTest();
      setTest(t);
      setTranscripts({});
      setResult(null);
      setActive((t.parts[0]?.part as SpeakingPart) ?? "part1");
      setPhase("interview");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not generate the interview.");
      setPhase("error");
    }
  };

  const submit = async () => {
    if (!test) return;
    stopRecording();
    setPhase("marking");
    setErrorMsg(null);
    try {
      const payload: Partial<
        Record<SpeakingPart, { question: unknown; transcript: string }>
      > = {};
      for (const part of test.parts) {
        const transcript = (transcripts[part.part] ?? "").trim();
        // One unanswered part must not take the answered ones down with it.
        if (transcript.split(/\s+/).filter(Boolean).length < MIN_WORDS) continue;
        payload[part.part] = { question: part.question ?? "", transcript };
      }
      const r = await api.speakingFullTestSubmit(payload);
      setResult(r);
      setPhase("done");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not mark the interview.");
      setPhase("error");
    }
  };

  const reset = () => {
    setTest(null);
    setTranscripts({});
    setResult(null);
    setErrorMsg(null);
    setPhase("start");
  };

  const answered = (test?.parts ?? []).filter(
    (p) =>
      (transcripts[p.part] ?? "").trim().split(/\s+/).filter(Boolean).length >=
      MIN_WORDS
  ).length;
  const activePart = (test?.parts ?? []).find((p) => p.part === active);

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Full Speaking Test" />

      <button
        onClick={() => router.push("/speaking")}
        className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back to Speaking
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
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-emerald-500/20 to-accent/10 text-emerald-500">
              <Mic className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Full Speaking Test</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              A complete IELTS Speaking interview — the introduction, the cue-card
              long turn and the abstract discussion, about 14 minutes, marked
              together for one band.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate full test
            </Button>
          </motion.div>
        )}

        {phase === "generating" && (
          <motion.div key="generating" exit={{ opacity: 0 }}>
            <div className="mb-6 text-center text-sm text-muted-foreground">
              Setting all three parts…
            </div>
            <WritingSkeleton />
          </motion.div>
        )}

        {phase === "marking" && (
          <motion.div key="marking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Assessing the whole interview" />
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
                  <p className="text-sm text-muted-foreground">Speaking interview</p>
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

            {(test?.parts ?? []).map((part) => {
              const marked = result.parts[part.part];
              if (!marked) return null;
              return (
                <section key={part.part} className="space-y-4">
                  <Badge variant="success" className="text-sm">
                    {part.label}
                  </Badge>
                  <BandFeedback
                    band={marked.band_score}
                    criteria={[
                      { label: "Fluency & Coherence", value: marked.fluency_coherence },
                      { label: "Lexical Resource", value: marked.lexical_resource },
                      {
                        label: "Grammar Range & Accuracy",
                        value: marked.grammatical_range_accuracy,
                      },
                      { label: "Pronunciation", value: marked.pronunciation },
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

        {phase === "interview" && test && activePart && (
          <motion.div
            key="interview"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="space-y-5"
          >
            <div className="grid gap-3 sm:grid-cols-3">
              {test.parts.map((part) => (
                <button
                  key={part.part}
                  onClick={() => selectPart(part.part)}
                  className={cn(
                    "glass rounded-[20px] p-4 text-left transition-all",
                    active === part.part
                      ? "border-primary/50 shadow-glow"
                      : "hover:border-primary/30 hover:shadow-soft"
                  )}
                >
                  <div className="font-display font-semibold">{part.label}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    ~{part.minutes} minutes
                  </div>
                </button>
              ))}
            </div>

            <div className="glass rounded-[24px] p-6 shadow-soft">
              <h3 className="mb-3 font-display font-semibold">Examiner question</h3>
              {isCueCardObject(activePart.question) ? (
                <CueCard question={activePart.question} />
              ) : (
                <ul className="space-y-2 text-[15px] leading-relaxed text-foreground/90">
                  {questionLines(activePart).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
            </div>

            {active === "part2" && (
              <Part2Timer
                onSpeakingStart={() => {
                  if (!recording) startRecording();
                }}
                onSpeakingEnd={() => stopRecording()}
              />
            )}

            <div className="glass-strong rounded-[28px] p-8 text-center shadow-soft">
              <motion.button
                onClick={() => (recording ? stopRecording() : startRecording())}
                whileHover={{ scale: 1.06 }}
                whileTap={{ scale: 0.94 }}
                aria-label={recording ? "Stop recording" : "Start recording"}
                className={cn(
                  "mx-auto flex size-20 items-center justify-center rounded-full text-white shadow-glow transition-colors",
                  recording
                    ? "bg-danger animate-pulse-glow"
                    : "bg-gradient-to-br from-emerald-500 to-accent"
                )}
              >
                {recording ? <Square className="size-7" /> : <Mic className="size-8" />}
              </motion.button>
              <p className="mt-4 text-sm text-muted-foreground">
                {recording
                  ? "Listening… speak naturally, then press stop."
                  : supported
                    ? "Press the microphone and answer out loud — we transcribe as you speak."
                    : "Live transcription is unavailable in this browser — type your answer below."}
              </p>
            </div>

            <div className="glass rounded-[24px] p-6 shadow-soft">
              <h3 className="mb-3 font-display font-semibold">
                Your answer — {activePart.label}
              </h3>
              <Textarea
                value={transcripts[active] ?? ""}
                onChange={(e) =>
                  setTranscripts((prev) => ({ ...prev, [active]: e.target.value }))
                }
                placeholder="Type (or dictate) what you would say…"
                rows={7}
                aria-label={`${activePart.label} transcript`}
              />
            </div>

            <div className="sticky bottom-4 flex justify-end">
              <Button
                size="lg"
                onClick={submit}
                disabled={answered === 0}
                className="shadow-glow"
              >
                <CheckCheck className="size-4" aria-hidden />
                Submit test ({answered}/{test.parts.length})
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
