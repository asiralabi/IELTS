"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ClipboardList,
  Headphones,
  BookOpen,
  PenLine,
  Mic,
  Send,
  CloudUpload,
  Flag,
} from "lucide-react";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
} from "recharts";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { MockExam, MockExamResult, PracticeQuestion, Visual } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ExaminerLoading } from "@/components/practice/examiner-loading";
import { QuestionList } from "@/components/practice/question-list";
import { Visuals } from "@/components/practice/visual";
import { BandRing } from "@/components/ui/progress";
import { cn, formatBand, formatDuration } from "@/lib/utils";

type Phase = "start" | "generating" | "exam" | "scoring" | "results";
type SectionId = "listening" | "reading" | "writing" | "speaking";

const SECTIONS: Array<{ id: SectionId; label: string; icon: typeof Headphones }> = [
  { id: "listening", label: "Listening", icon: Headphones },
  { id: "reading", label: "Reading", icon: BookOpen },
  { id: "writing", label: "Writing", icon: PenLine },
  { id: "speaking", label: "Speaking", icon: Mic },
];

const EXAM_MINUTES = 165;

function asQuestionText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (typeof obj.question === "string") return obj.question;
    return JSON.stringify(value, null, 2);
  }
  return String(value ?? "");
}

function extractVisual(value: unknown): Visual | null {
  if (!value || typeof value !== "object") return null;
  const raw = (value as { visual?: unknown }).visual;
  if (!raw || typeof raw !== "object") return null;
  const kind = (raw as { kind?: unknown }).kind;
  if (kind === "image" && typeof (raw as { url?: unknown }).url === "string") {
    return raw as Visual;
  }
  if (kind === "chart" && Array.isArray((raw as { series?: unknown }).series)) {
    return raw as Visual;
  }
  return null;
}

export default function MockTestPage() {
  const [phase, setPhase] = React.useState<Phase>("start");
  const [exam, setExam] = React.useState<MockExam | null>(null);
  const [section, setSection] = React.useState<SectionId>("listening");
  const [listeningAnswers, setListeningAnswers] = React.useState<Record<string, string>>({});
  const [readingAnswers, setReadingAnswers] = React.useState<Record<string, string>>({});
  const [essays, setEssays] = React.useState<Record<string, string>>({});
  const [transcripts, setTranscripts] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<MockExamResult | null>(null);
  const [seconds, setSeconds] = React.useState(0);
  const [saved, setSaved] = React.useState(false);
  const [flagged, setFlagged] = React.useState<Record<string, boolean>>({});

  React.useEffect(() => {
    if (phase !== "exam") return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase]);

  // Autosave pulse whenever answers change.
  const savedTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const pulseSaved = () => {
    setSaved(true);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSaved(false), 1500);
  };

  const generate = async () => {
    setPhase("generating");
    try {
      const e = await api.generateMockExam();
      setExam(e);
      setListeningAnswers({});
      setReadingAnswers({});
      setEssays({});
      setTranscripts({});
      setSeconds(0);
      setSection("listening");
      setPhase("exam");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate the exam.");
      setPhase("start");
    }
  };

  const submit = async () => {
    if (!exam) return;
    setPhase("scoring");
    try {
      const r = await api.submitMockExam(exam.id, {
        listening_answers: listeningAnswers,
        reading_answers: readingAnswers,
        essays,
        speaking_transcripts: transcripts,
      });
      setResult(r);
      setPhase("results");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Scoring failed.");
      setPhase("exam");
    }
  };

  const examData = (exam?.exam ?? {}) as Record<string, unknown>;
  const listening = examData.listening as
    | { title?: string; audio_script?: string; questions?: PracticeQuestion[] }
    | undefined;
  const reading = examData.reading as
    | { title?: string; passage?: string; questions?: PracticeQuestion[] }
    | undefined;
  const writing = (examData.writing ?? {}) as Record<string, unknown>;
  const speaking = (examData.speaking ?? {}) as Record<string, unknown>;

  const timeLeft = EXAM_MINUTES * 60 - seconds;
  const sectionBands = (result?.results?.section_bands ?? {}) as Record<string, number>;
  const radarData = SECTIONS.map((s) => ({
    skill: s.label,
    band: sectionBands[s.id] ?? 0,
  }));

  return (
    <div className="mx-auto max-w-5xl">
      <Topbar title="Mock Test" />

      <AnimatePresence mode="wait">
        {phase === "start" && (
          <motion.div
            key="start"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="glass-strong mx-auto max-w-xl rounded-[28px] p-10 text-center shadow-soft"
          >
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary/20 to-secondary/10 text-primary">
              <ClipboardList className="size-8" aria-hidden />
            </span>
            <h2 className="font-display text-2xl font-bold">Full AI Mock Exam</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
              All four skills in one sitting, generated at your target band.
              The AI examiner scores everything and returns your overall band.
            </p>
            <p className="mt-2 text-xs text-muted-foreground/70">
              Generation runs 7 AI tasks and can take a while on a local model.
            </p>
            <Button size="lg" className="mt-8" onClick={generate}>
              Generate my exam
            </Button>
          </motion.div>
        )}

        {(phase === "generating" || phase === "scoring") && (
          <motion.div key="loading" exit={{ opacity: 0 }} className="mx-auto max-w-lg pt-10">
            <ExaminerLoading
              label={phase === "generating" ? "Building your exam" : "Scoring all four skills"}
            />
          </motion.div>
        )}

        {phase === "exam" && exam && (
          <motion.div key="exam" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-5">
            {/* Exam header: navigator + timer + autosave */}
            <div className="glass-strong sticky top-3 z-30 flex flex-wrap items-center justify-between gap-3 rounded-[24px] p-3 shadow-soft">
              <div className="flex gap-1.5">
                {SECTIONS.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setSection(s.id)}
                    aria-current={section === s.id ? "step" : undefined}
                    className={cn(
                      "flex items-center gap-2 rounded-2xl px-3.5 py-2 text-sm font-medium transition-all",
                      section === s.id
                        ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <s.icon className="size-4" aria-hidden />
                    <span className="hidden sm:inline">{s.label}</span>
                    {flagged[s.id] && <Flag className="size-3 text-warning" aria-hidden />}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <AnimatePresence>
                  {saved && (
                    <motion.span
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0 }}
                      className="flex items-center gap-1 text-xs text-success"
                    >
                      <CloudUpload className="size-3.5" aria-hidden /> Saved
                    </motion.span>
                  )}
                </AnimatePresence>
                <button
                  onClick={() => setFlagged((f) => ({ ...f, [section]: !f[section] }))}
                  aria-label="Flag this section"
                  className={cn(
                    "flex size-9 items-center justify-center rounded-xl transition-colors",
                    flagged[section] ? "text-warning" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Flag className="size-4" aria-hidden />
                </button>
                <Badge variant={timeLeft < 900 ? "danger" : "outline"} className="font-mono">
                  {timeLeft >= 0 ? formatDuration(timeLeft) : "00:00"}
                </Badge>
                <Button size="sm" onClick={submit}>
                  <Send className="size-4" aria-hidden />
                  Submit
                </Button>
              </div>
            </div>

            {/* Section content */}
            <AnimatePresence mode="wait">
              <motion.div
                key={section}
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -16 }}
                transition={{ duration: 0.25 }}
                className="space-y-5"
              >
                {section === "listening" && listening && (
                  <>
                    <div className="glass rounded-[24px] p-6 shadow-soft">
                      <Badge variant="accent" className="mb-3">
                        Recording script
                      </Badge>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                        {listening.audio_script}
                      </p>
                    </div>
                    <QuestionList
                      questions={listening.questions ?? []}
                      answers={listeningAnswers}
                      onAnswer={(k, v) => {
                        setListeningAnswers((a) => ({ ...a, [k]: v }));
                        pulseSaved();
                      }}
                    />
                  </>
                )}

                {section === "reading" && reading && (
                  <div className="grid gap-6 lg:grid-cols-2">
                    <div className="glass max-h-[65vh] overflow-y-auto rounded-[24px] p-6 shadow-soft lg:sticky lg:top-24">
                      <Badge variant="secondary" className="mb-3">
                        {reading.title ?? "Passage"}
                      </Badge>
                      <p className="whitespace-pre-wrap text-[15px] leading-[1.8]">
                        {reading.passage}
                      </p>
                    </div>
                    <QuestionList
                      questions={reading.questions ?? []}
                      answers={readingAnswers}
                      onAnswer={(k, v) => {
                        setReadingAnswers((a) => ({ ...a, [k]: v }));
                        pulseSaved();
                      }}
                    />
                  </div>
                )}

                {section === "writing" &&
                  (["task1", "task2"] as const).map((t) => {
                    const taskVisual = extractVisual(writing[t]);
                    return (
                      <div key={t} className="glass rounded-[24px] p-6 shadow-soft">
                        <Badge variant="warning" className="mb-3">
                          {t === "task1" ? "Task 1 (150+ words)" : "Task 2 (250+ words)"}
                        </Badge>
                        <p className="mb-4 whitespace-pre-wrap text-sm font-medium leading-relaxed">
                          {asQuestionText(writing[t])}
                        </p>
                        {taskVisual && <Visuals visual={taskVisual} className="mb-4" />}
                        <Textarea
                          value={essays[t] ?? ""}
                          onChange={(e) => {
                            setEssays((es) => ({ ...es, [t]: e.target.value }));
                            pulseSaved();
                          }}
                          placeholder="Write your answer…"
                          rows={8}
                          aria-label={`${t} essay`}
                        />
                        <p className="mt-2 text-xs text-muted-foreground">
                          {essays[t]?.trim() ? essays[t].trim().split(/\s+/).length : 0} words
                        </p>
                      </div>
                    );
                  })}

                {section === "speaking" &&
                  (["part1", "part2", "part3"] as const).map((p) => (
                    <div key={p} className="glass rounded-[24px] p-6 shadow-soft">
                      <Badge variant="success" className="mb-3">
                        {p === "part1" ? "Part 1" : p === "part2" ? "Part 2 — Cue card" : "Part 3"}
                      </Badge>
                      <p className="mb-4 whitespace-pre-wrap text-sm font-medium leading-relaxed">
                        {asQuestionText(speaking[p])}
                      </p>
                      <Textarea
                        value={transcripts[p] ?? ""}
                        onChange={(e) => {
                          setTranscripts((tr) => ({ ...tr, [p]: e.target.value }));
                          pulseSaved();
                        }}
                        placeholder="Type (or dictate) what you would say…"
                        rows={5}
                        aria-label={`${p} answer`}
                      />
                    </div>
                  ))}
              </motion.div>
            </AnimatePresence>
          </motion.div>
        )}

        {phase === "results" && result && (
          <motion.div key="results" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
            <div className="glass-strong flex flex-col items-center gap-8 rounded-[28px] p-8 shadow-soft md:flex-row md:justify-around">
              <BandRing band={result.overall_band} size={170} label="Overall Band" />
              <div className="h-56 w-full max-w-sm">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={radarData} outerRadius="75%">
                    <PolarGrid stroke="currentColor" strokeOpacity={0.15} />
                    <PolarAngleAxis
                      dataKey="skill"
                      tick={{ fill: "currentColor", fontSize: 12, opacity: 0.7 }}
                    />
                    <Radar
                      dataKey="band"
                      stroke="#7C4DFF"
                      fill="#5B5CEB"
                      fillOpacity={0.35}
                      isAnimationActive
                    />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {SECTIONS.map((s, i) => (
                <motion.div
                  key={s.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15 * i }}
                  className="glass rounded-[24px] p-5 text-center shadow-soft"
                >
                  <s.icon className="mx-auto size-6 text-primary" aria-hidden />
                  <div className="mt-2 font-display text-2xl font-bold">
                    {formatBand(sectionBands[s.id] ?? null)}
                  </div>
                  <div className="text-xs text-muted-foreground">{s.label}</div>
                </motion.div>
              ))}
            </div>

            <div className="flex justify-center">
              <Button variant="secondary" onClick={() => setPhase("start")}>
                Take another mock test
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
