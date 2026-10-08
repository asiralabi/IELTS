"use client";

import * as React from "react";
import { motion, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from "framer-motion";
import { Chapter } from "@/components/landing/chapter";
import { cn } from "@/lib/utils";

/* ── the four specimens: each stop shows a small piece of the real thing ── */

function ListeningSpecimen() {
  const bars = [0.4, 0.7, 0.55, 0.9, 0.35, 0.65, 1, 0.5, 0.8, 0.45, 0.7, 0.3, 0.6, 0.85, 0.4, 0.75, 0.5, 0.95, 0.35, 0.6];
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        <span>Part 1 · Recording</span>
        <span className="tabular-nums">02:14</span>
      </div>
      <div className="mt-4 flex h-12 items-center gap-[3px]" aria-hidden>
        {bars.map((h, i) => (
          <span
            key={i}
            className={cn("w-full origin-center rounded-full animate-equalizer", i < 9 ? "bg-primary" : "bg-foreground/15")}
            style={{ height: `${h * 100}%`, animationDelay: `${(i % 7) * -0.13}s`, animationDuration: `${1 + (i % 4) * 0.2}s` }}
          />
        ))}
      </div>
      <p className="mt-4 text-sm">
        The library opens at <span className="inline-block min-w-16 border-b border-dashed border-foreground/50 text-center font-mono text-primary">8.30</span> on weekdays.
      </p>
    </div>
  );
}

function ReadingSpecimen() {
  return (
    <div className="rounded-xl border border-border bg-background p-4 text-[13px] leading-relaxed text-muted-foreground">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em]">Passage 2 · Paragraph C</p>
      <p className="mt-3">
        Mangrove roots trap silt carried down by the rivers, and over decades{" "}
        <mark className="rounded-[2px] bg-sun/15 px-0.5 text-foreground">the forest slowly builds new land</mark>{" "}
        along the edge of the delta.
      </p>
      <p className="mt-3 border-t border-border pt-3 text-foreground">
        14. The mangroves help to create land. <span className="ml-1 font-mono text-[11px] text-primary">TRUE</span>
      </p>
    </div>
  );
}

function WritingSpecimen() {
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Task 2 · Opinion essay</p>
      <p className="mt-3 font-display text-[15px] leading-relaxed">
        Some people believe that studying abroad is the best way to prepare for a career. To what extent do you agree?
      </p>
      <div className="mt-4 flex items-center gap-3">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-[84%] rounded-full bg-primary" />
        </div>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">271 / 250</span>
      </div>
    </div>
  );
}

function SpeakingSpecimen() {
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        <span>Part 2 · Cue card</span>
        <span className="flex items-center gap-1.5 text-sun">
          <span className="size-1.5 rounded-full bg-sun animate-pulse-glow" aria-hidden /> Rec 01:12
        </span>
      </div>
      <p className="mt-3 font-display text-[15px]">Describe a place you would like to visit one day.</p>
      <ul className="mt-2 space-y-0.5 text-[13px] text-muted-foreground">
        <li>— where it is</li>
        <li>— how you heard about it</li>
        <li>— and explain why you want to go there</li>
      </ul>
    </div>
  );
}

const STOPS = [
  {
    code: "LST",
    name: "Listening",
    facts: "4 parts · 40 questions · about 30 minutes",
    body: "Recordings with the accents you will actually hear, played once, like the real test. Your answers are checked the moment the last part ends.",
    Specimen: ListeningSpecimen,
  },
  {
    code: "RDG",
    name: "Reading",
    facts: "3 passages · 40 questions · 60 minutes",
    body: "Long academic passages with every question type: True / False / Not Given, matching headings, gap fills. See which line held the answer you missed.",
    Specimen: ReadingSpecimen,
  },
  {
    code: "WRT",
    name: "Writing",
    facts: "2 tasks · 60 minutes · 150 and 250 words",
    body: "Write under the clock, then get a band on all four criteria, with the sentences that cost you marks underlined and rewritten.",
    Specimen: WritingSpecimen,
  },
  {
    code: "SPK",
    name: "Speaking",
    facts: "3 parts · 11 to 14 minutes",
    body: "Answer Part 1, the cue card and the follow-up discussion out loud. Your answer is transcribed and marked for fluency, vocabulary, grammar and pronunciation.",
    Specimen: SpeakingSpecimen,
  },
];

function Stop({
  stop,
  index,
  progress,
}: {
  stop: (typeof STOPS)[number];
  index: number;
  progress: MotionValue<number>;
}) {
  const at = (index + 0.35) / STOPS.length;
  const reached = useTransform(progress, [at - 0.04, at], [0, 1]);
  const ring = useTransform(reached, (v) => (v > 0.5 ? "var(--primary)" : "var(--border)"));
  const { Specimen } = stop;

  return (
    <div className="relative grid gap-8 pb-24 pl-12 last:pb-0 sm:pl-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)] lg:gap-14">
      {/* the waypoint on the route */}
      <motion.span
        aria-hidden
        style={{ borderColor: ring }}
        className="absolute top-1 left-[9px] flex size-[22px] items-center justify-center rounded-full border-2 bg-background sm:left-[25px]"
      >
        <motion.span style={{ scale: reached }} className="size-2 rounded-full bg-primary" />
      </motion.span>

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-100px" }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      >
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
          Stop {index + 1} · <span className="text-sun">{stop.code}</span>
        </p>
        <h3 className="mt-3 font-display text-4xl font-normal tracking-tight sm:text-5xl">{stop.name}</h3>
        <p className="mt-3 font-mono text-xs text-primary">{stop.facts}</p>
        <p className="mt-5 max-w-[48ch] leading-relaxed text-muted-foreground">{stop.body}</p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-100px" }}
        transition={{ duration: 0.9, delay: 0.12, ease: [0.16, 1, 0.3, 1] }}
        className="lg:pt-8"
      >
        <Specimen />
      </motion.div>
    </div>
  );
}

export function Route() {
  const ref = React.useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.6", "end 0.6"] });
  const progress = useSpring(scrollYProgress, { stiffness: 120, damping: 28, mass: 0.4 });
  const line = reduce ? scrollYProgress : progress;
  const planeTop = useTransform(line, (v) => `${Math.min(100, Math.max(0, v * 100))}%`);

  return (
    <section id="route" className="relative scroll-mt-16 py-28 sm:py-40">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <Chapter n="০২" label="The route" />
        <div className="mt-10 grid gap-8 lg:grid-cols-12">
          <h2 className="font-display text-4xl leading-[1.05] font-normal tracking-[-0.02em] sm:text-6xl lg:col-span-7">
            Four stops between your desk and the departure gate.
          </h2>
          <p className="max-w-[46ch] self-end leading-relaxed text-muted-foreground lg:col-span-4 lg:col-start-9">
            The test is the same everywhere in Bangladesh, from Chattogram to Sylhet. So is the
            practice: each section timed and laid out the way you will meet it on the day.
          </p>
        </div>

        <div ref={ref} className="relative mt-20">
          {/* the route itself: a dashed track, the travelled part in ink */}
          <div aria-hidden className="absolute top-0 bottom-0 left-[19px] w-px sm:left-[35px]">
            <div className="absolute inset-0 bg-[repeating-linear-gradient(to_bottom,var(--border)_0,var(--border)_6px,transparent_6px,transparent_12px)]" />
            <motion.div style={{ scaleY: line }} className="absolute inset-0 origin-top bg-primary" />
            <motion.div
              style={{ top: planeTop }}
              className="absolute left-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sun shadow-[0_0_0_5px_var(--background)]"
            />
          </div>

          {STOPS.map((s, i) => (
            <Stop key={s.code} stop={s} index={i} progress={line} />
          ))}
        </div>
      </div>
    </section>
  );
}
