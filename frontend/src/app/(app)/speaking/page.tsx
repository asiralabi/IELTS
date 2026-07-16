"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Square, Wand2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { SpeakingPart, SpeakingResult } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { BandFeedback, toStringArray } from "@/components/practice/band-feedback";
import { CueCard, isCueCardObject } from "@/components/practice/cue-card";
import { Part2Timer, SpeakingElapsedHint } from "@/components/practice/speaking-timers";
import { cn } from "@/lib/utils";

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

const PARTS: Array<{ id: SpeakingPart; label: string; hint: string }> = [
  { id: "part1", label: "Part 1", hint: "Introduction & everyday topics" },
  { id: "part2", label: "Part 2", hint: "Cue card long turn (2 min)" },
  { id: "part3", label: "Part 3", hint: "Abstract discussion" },
];

type Phase = "prep" | "marking" | "feedback";

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-14 items-center justify-center gap-1" aria-hidden>
      {Array.from({ length: 28 }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "w-1 origin-center rounded-full bg-gradient-to-t from-emerald-500 to-accent transition-all",
            active ? "animate-equalizer" : "scale-y-[0.2] opacity-40"
          )}
          style={{
            height: `${14 + ((i * 11) % 32)}px`,
            animationDelay: `${i * 0.06}s`,
          }}
        />
      ))}
    </div>
  );
}

export default function SpeakingPage() {
  const [part, setPart] = React.useState<SpeakingPart>("part1");
  // Store the raw question from the API — could be a string OR a cue-card
  // object (Part 2 backend schema is `{topic, bullets, closing}`).
  const [questionRaw, setQuestionRaw] = React.useState<unknown>("");
  const [questionText, setQuestionText] = React.useState("");
  const [transcript, setTranscript] = React.useState("");
  const [recording, setRecording] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>("prep");
  const [result, setResult] = React.useState<SpeakingResult | null>(null);
  const [generating, setGenerating] = React.useState(false);
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
      toast.info("Live transcription needs Chrome or Edge — type your answer below instead.");
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
      if (text) setTranscript((t) => (t ? t + " " : "") + text.trim());
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
  }, []);

  const toggleRecording = () => {
    if (recording) stopRecording();
    else startRecording();
  };

  const generateQuestion = async () => {
    setGenerating(true);
    try {
      const q = await api.generateQuestion({ section: "speaking", question_type: part });
      const raw = (q as Record<string, unknown>).question ?? q;
      setQuestionRaw(raw);
      if (typeof raw === "string") {
        setQuestionText(raw);
      } else if (isCueCardObject(raw)) {
        // Also keep a plain-text form so the submit payload has the prompt.
        const flat = [
          raw.topic,
          ...(Array.isArray(raw.bullets) ? raw.bullets.map((b) => `- ${b}`) : []),
          raw.closing,
        ]
          .filter(Boolean)
          .join("\n");
        setQuestionText(flat);
      } else {
        setQuestionText(JSON.stringify(raw));
      }
      toast.success("New question ready!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate a question.");
    } finally {
      setGenerating(false);
    }
  };

  const submit = async () => {
    if (!questionText.trim()) {
      toast.error("Generate or enter a question first.");
      return;
    }
    if (transcript.trim().split(/\s+/).length < 5) {
      toast.error("Your answer is too short to evaluate.");
      return;
    }
    stopRecording();
    setPhase("marking");
    try {
      const res = await api.submitSpeaking({
        part,
        question: questionText.trim(),
        transcript: transcript.trim(),
      });
      setResult(res);
      setPhase("feedback");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Evaluation failed.");
      setPhase("prep");
    }
  };

  const restart = () => {
    setPhase("prep");
    setResult(null);
    setTranscript("");
  };

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Speaking" />

      <AnimatePresence mode="wait">
        {phase === "marking" && (
          <motion.div key="marking" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading label="Assessing your speaking" />
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
              <Badge variant="success">{PARTS.find((p) => p.id === part)?.label}</Badge>
              <Button variant="secondary" size="sm" onClick={restart}>
                <RotateCcw className="size-4" aria-hidden />
                Answer another
              </Button>
            </div>
            <BandFeedback
              band={result.band_score}
              criteria={[
                { label: "Fluency & Coherence", value: result.fluency_coherence },
                { label: "Lexical Resource", value: result.lexical_resource },
                { label: "Grammar Range & Accuracy", value: result.grammatical_range_accuracy },
                { label: "Pronunciation", value: result.pronunciation },
              ]}
              feedback={typeof result.feedback === "string" ? result.feedback : undefined}
              strengths={toStringArray(result.strengths)}
              weaknesses={toStringArray(result.weaknesses)}
              suggestions={toStringArray(result.suggestions)}
            />
          </motion.div>
        )}

        {phase === "prep" && (
          <motion.div
            key="prep"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-5"
          >
            {/* Part selector */}
            <div className="grid gap-3 sm:grid-cols-3">
              {PARTS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPart(p.id)}
                  className={cn(
                    "glass rounded-[20px] p-4 text-left transition-all",
                    part === p.id
                      ? "border-primary/50 shadow-glow"
                      : "hover:border-primary/30 hover:shadow-soft"
                  )}
                >
                  <div className="font-display font-semibold">{p.label}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{p.hint}</div>
                </button>
              ))}
            </div>

            {/* Question */}
            <div className="glass rounded-[24px] p-6 shadow-soft">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="font-display font-semibold">Examiner question</h3>
                <div className="flex items-center gap-2">
                  {(part === "part1" || part === "part3") && (
                    <SpeakingElapsedHint active={recording} />
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={generateQuestion}
                    loading={generating}
                  >
                    <Wand2 className="size-4" aria-hidden />
                    Generate
                  </Button>
                </div>
              </div>

              {part === "part2" && isCueCardObject(questionRaw) ? (
                <CueCard question={questionRaw} />
              ) : (
                <Textarea
                  value={questionText}
                  onChange={(e) => {
                    setQuestionText(e.target.value);
                    setQuestionRaw(e.target.value);
                  }}
                  placeholder="Generate an AI question or type your own…"
                  rows={2}
                  aria-label="Speaking question"
                />
              )}
            </div>

            {/* Part 2 timer — prep + speaking countdowns */}
            {part === "part2" && (
              <Part2Timer
                onSpeakingStart={() => {
                  if (!recording) startRecording();
                }}
                onSpeakingEnd={() => stopRecording()}
              />
            )}

            {/* Recorder */}
            <div className="glass-strong rounded-[28px] p-8 text-center shadow-soft">
              <Waveform active={recording} />
              <motion.button
                onClick={toggleRecording}
                whileHover={{ scale: 1.06 }}
                whileTap={{ scale: 0.94 }}
                aria-label={recording ? "Stop recording" : "Start recording"}
                className={cn(
                  "mx-auto mt-4 flex size-20 items-center justify-center rounded-full text-white shadow-glow transition-colors",
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

            {/* Transcript */}
            <div className="glass rounded-[24px] p-6 shadow-soft">
              <h3 className="mb-3 font-display font-semibold">Your answer (transcript)</h3>
              <Textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder="Your spoken answer appears here — you can also edit or type it."
                rows={6}
                aria-label="Answer transcript"
              />
            </div>

            <div className="flex justify-end">
              <Button size="lg" onClick={submit} disabled={!transcript.trim()}>
                Submit for AI assessment
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
