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
import { NeuralAudioPlayer } from "@/components/practice/neural-audio-player";
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

// The real paper is sat one section at a time, each on its own clock, and you
// cannot go back to a section you have left. A single 165-minute countdown let
// a student spend two hours on Reading and skip Listening entirely, which is
// the one thing a mock test must not allow — the whole point is to find out
// whether they can work at the exam's pace.
const SECTION_MINUTES: Record<SectionId, number> = {
  listening: 30,
  reading: 60,
  writing: 60,
  speaking: 15,
};
const SECTION_ORDER: SectionId[] = ["listening", "reading", "writing", "speaking"];
const EXAM_MINUTES = SECTION_ORDER.reduce((t, s) => t + SECTION_MINUTES[s], 0);

function asQuestionText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (typeof obj.question === "string") return obj.question;
    return JSON.stringify(value, null, 2);
  }
  return String(value ?? "");
}

// A pooled mock exam serves whole papers — four listening parts, three reading
// passages, numbered straight through. A cold pool falls back to one practice
// set per section. Both collapse to the same list so the exam renders once.
type ExamSection = {
  key: string;
  label: string;
  body?: string;
  title?: string;
  visual?: Visual;
  visuals?: Visual[];
  questions: PracticeQuestion[];
};

function toSections(
  paper: unknown,
  listKey: "parts" | "passages",
  indexKey: "part" | "passage_number",
  bodyKey: "audio_script" | "passage",
  noun: string
): ExamSection[] {
  if (!paper || typeof paper !== "object") return [];
  const obj = paper as Record<string, unknown>;
  const list = Array.isArray(obj[listKey])
    ? (obj[listKey] as Record<string, unknown>[])
    : [obj];
  return list.map((section, i) => ({
    key: `${noun}-${section[indexKey] ?? i + 1}`,
    label: `${noun} ${section[indexKey] ?? i + 1}`,
    body: typeof section[bodyKey] === "string" ? (section[bodyKey] as string) : undefined,
    title: typeof section.title === "string" ? section.title : undefined,
    visual: (section.visual as Visual) ?? undefined,
    visuals: (section.visuals as Visual[]) ?? undefined,
    questions: Array.isArray(section.questions)
      ? (section.questions as PracticeQuestion[])
      : [],
  }));
}

/** The part number out of a section key like "Part 3". */
function partNumber(key: string): number {
  const m = /(\d+)/.exec(key);
  return m ? Number(m[1]) : 1;
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
  // Which question the student is on, so the figure can light that
  // blank. One at a time, so one piece of state covers every section.
  const [activeGap, setActiveGap] = React.useState<string | null>(null);
  const [essays, setEssays] = React.useState<Record<string, string>>({});
  const [transcripts, setTranscripts] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<MockExamResult | null>(null);
  const [seconds, setSeconds] = React.useState(0);
  const [saved, setSaved] = React.useState(false);
  const [flagged, setFlagged] = React.useState<Record<string, boolean>>({});
  // How many times each Listening part has been played. The real exam plays
  // each recording ONCE, so this is one, not the practice page's two.
  const [plays, setPlays] = React.useState<Record<string, number>>({});

  // Sections already sat. The exam never returns to one, exactly as the real
  // test never hands a paper back.
  const [closed, setClosed] = React.useState<SectionId[]>([]);
  // When the current section's clock started, on the same elapsed-seconds
  // scale as `seconds`, so both timers stay in step through a re-render.
  const [sectionFrom, setSectionFrom] = React.useState(0);

  const sectionLeft = SECTION_MINUTES[section] * 60 - (seconds - sectionFrom);

  /** Close the current section and open the next. Time is not carried over —
   * minutes saved on Listening do not buy minutes on Reading, and the real
   * exam is the same. */
  const closeSection = React.useCallback(() => {
    setClosed((done) => (done.includes(section) ? done : [...done, section]));
    const next = SECTION_ORDER[SECTION_ORDER.indexOf(section) + 1];
    if (next) {
      setSection(next);
      setSectionFrom(seconds);
    }
  }, [section, seconds]);

  // The clock decides the transition, on the tick that crosses zero — not a
  // separate effect watching the derived value, which would be setting state
  // from a render pass. `elapsed` lives in a ref so the interval can read the
  // real count without being torn down and rebuilt every second.
  const elapsed = React.useRef(0);

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
      setPlays({});
      elapsed.current = 0;
      setSection("listening");
      setClosed([]);
      setSectionFrom(0);
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

  // The exam clock reads the current section and the current `submit` through
  // a ref refreshed after every render — the standard latest-ref pattern. It
  // keeps the interval out of the dependency list, so the countdown is not
  // torn down and rebuilt on every keystroke, and it keeps the writes out of
  // the render pass.
  const live = React.useRef({ section, sectionFrom, closeSection, submit });
  React.useEffect(() => {
    live.current = { section, sectionFrom, closeSection, submit };
  });

  React.useEffect(() => {
    if (phase !== "exam") return;
    const t = setInterval(() => {
      elapsed.current += 1;
      setSeconds(elapsed.current);
      const state = live.current;
      if (
        SECTION_MINUTES[state.section] * 60 - (elapsed.current - state.sectionFrom) >
        0
      ) {
        return;
      }
      // Out of time. The last section ending is the end of the exam, so it
      // submits rather than leaving the student at a dead paper.
      if (SECTION_ORDER.indexOf(state.section) === SECTION_ORDER.length - 1) {
        void state.submit();
      } else {
        state.closeSection();
      }
    }, 1000);
    return () => clearInterval(t);
  }, [phase]);

  const examData = (exam?.exam ?? {}) as Record<string, unknown>;
  const listeningParts = React.useMemo(
    () => toSections(examData.listening, "parts", "part", "audio_script", "Part"),
    [examData.listening]
  );
  const readingPassages = React.useMemo(
    () =>
      toSections(examData.reading, "passages", "passage_number", "passage", "Passage"),
    [examData.reading]
  );
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
              Full papers are written in the background ahead of time. If they
              are not ready yet you get a shorter exam, scaled to the same band.
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
                {/* A navigator, not a menu. A section already sat is closed and
                    one not yet reached has not opened — the same as the real
                    exam, where the paper you are on is the only paper you
                    have. Disabled rather than hidden so the student can see
                    where they are in the test. */}
                {SECTIONS.map((s) => {
                  const done = closed.includes(s.id);
                  const current = section === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => setSection(s.id)}
                      disabled={!current}
                      aria-current={current ? "step" : undefined}
                      title={
                        done
                          ? `${s.label} is finished — the exam does not go back`
                          : current
                            ? undefined
                            : `${s.label} opens when the section before it ends`
                      }
                      className={cn(
                        "flex items-center gap-2 rounded-2xl px-3.5 py-2 text-sm font-medium transition-all",
                        current
                          ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                          : done
                            ? "text-muted-foreground/70 line-through"
                            : "text-muted-foreground/40",
                        !current && "cursor-not-allowed"
                      )}
                    >
                      <s.icon className="size-4" aria-hidden />
                      <span className="hidden sm:inline">{s.label}</span>
                      {flagged[s.id] && <Flag className="size-3 text-warning" aria-hidden />}
                    </button>
                  );
                })}
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
                {/* The SECTION clock leads, because that is the one the
                    student is racing. The whole-exam figure stays beside it,
                    smaller, so they can still see how much test is left. */}
                <Badge
                  variant={sectionLeft < 300 ? "danger" : "outline"}
                  className="font-mono tabular-nums"
                >
                  {SECTIONS.find((s) => s.id === section)?.label}{" "}
                  {sectionLeft >= 0 ? formatDuration(sectionLeft) : "00:00"}
                </Badge>
                <span className="hidden font-mono text-xs tabular-nums text-muted-foreground sm:inline">
                  {timeLeft >= 0 ? formatDuration(timeLeft) : "00:00"} total
                </span>
                {SECTION_ORDER.indexOf(section) < SECTION_ORDER.length - 1 && (
                  <Button size="sm" variant="ghost" onClick={closeSection}>
                    Finish section
                  </Button>
                )}
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
                {section === "listening" &&
                  listeningParts.map((part) => (
                    <div key={part.key} className="space-y-4">
                      <div className="glass rounded-[24px] p-6 shadow-soft">
                        <Badge variant="accent" className="mb-3">
                          {listeningParts.length > 1 ? part.label : "Recording script"}
                        </Badge>
                        {part.title && (
                          <h3 className="mb-2 font-display text-lg font-semibold">
                            {part.title}
                          </h3>
                        )}
                        {/* The recording, NOT the transcript.
                            The exam printed `audio_script` here, so a student
                            sat the Listening paper by reading it — a reading
                            test with a different name on it. IELTS plays each
                            part once; the transcript is for the report
                            afterwards, not for the exam. */}
                        {part.body && exam?.id ? (
                          <div className="flex flex-wrap items-center justify-between gap-4">
                            <NeuralAudioPlayer
                              part={partNumber(part.key)}
                              disabled={phase !== "exam"}
                              canPlay={() => (plays[part.key] ?? 0) < 1}
                              onPlayStart={() =>
                                setPlays((p) => ({
                                  ...p,
                                  [part.key]: (p[part.key] ?? 0) + 1,
                                }))
                              }
                              fetchAudio={() =>
                                api.mockExamAudio(exam.id, partNumber(part.key))
                              }
                            />
                            <Badge
                              variant={plays[part.key] ? "danger" : "accent"}
                            >
                              {plays[part.key]
                                ? "Played — the exam plays each part once"
                                : "Plays once"}
                            </Badge>
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                            {part.body}
                          </p>
                        )}
                        <Visuals
                          activeGap={activeGap}
                          visual={part.visual}
                          visuals={part.visuals}
                          className="mt-4"
                        />
                      </div>
                      <QuestionList
                        onActiveQuestion={setActiveGap}
                        questions={part.questions}
                        answers={listeningAnswers}
                        onAnswer={(k, v) => {
                          setListeningAnswers((a) => ({ ...a, [k]: v }));
                          pulseSaved();
                        }}
                      />
                    </div>
                  ))}

                {section === "reading" &&
                  readingPassages.map((passage) => (
                    <div key={passage.key} className="grid gap-6 lg:grid-cols-2">
                      <div className="glass max-h-[65vh] overflow-y-auto rounded-[24px] p-6 shadow-soft lg:sticky lg:top-24">
                        <Badge variant="secondary" className="mb-3">
                          {readingPassages.length > 1 ? passage.label : "Passage"}
                        </Badge>
                        {passage.title && (
                          <h3 className="mb-2 font-display text-lg font-semibold">
                            {passage.title}
                          </h3>
                        )}
                        <p className="whitespace-pre-wrap text-[15px] leading-[1.8]">
                          {passage.body}
                        </p>
                        <Visuals
                          activeGap={activeGap}
                          visual={passage.visual}
                          visuals={passage.visuals}
                          className="mt-4"
                        />
                      </div>
                      <QuestionList
                        onActiveQuestion={setActiveGap}
                        questions={passage.questions}
                        answers={readingAnswers}
                        onAnswer={(k, v) => {
                          setReadingAnswers((a) => ({ ...a, [k]: v }));
                          pulseSaved();
                        }}
                      />
                    </div>
                  ))}

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
                        {taskVisual && <Visuals
                    activeGap={activeGap} visual={taskVisual} className="mb-4" />}
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
