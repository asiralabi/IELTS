"use client";

import { motion } from "framer-motion";
import { Chapter } from "@/components/landing/chapter";

const ITEMS = [
  { item: "Full mock exams", note: "All four skills in one sitting, timed like the real day." },
  { item: "Cambridge practice tests", note: "Sit the past papers from the Cambridge IELTS books, section by section." },
  { item: "A band for every answer", note: "Writing and Speaking marked on all four criteria." },
  { item: "Every mistake explained", note: "What went wrong, why, and the sentence rewritten." },
  { item: "A study plan from your scores", note: "What to practise this week, built from where you lost marks." },
  { item: "Vocabulary flashcards", note: "Academic words on cards. Mark the ones you know, come back for the rest." },
  { item: "Ask Oratio, any hour", note: "Grammar, vocabulary or strategy questions, answered at 2 a.m. too." },
  { item: "Your distance to the target", note: "Your band for each skill and how far you are from the score you need, on one page." },
];

function Tick({ delay }: { delay: number }) {
  return (
    <svg viewBox="0 0 24 24" className="size-5 text-primary" aria-hidden>
      <rect x="2.5" y="2.5" width="19" height="19" rx="3" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1.2" />
      <motion.path
        d="M7 12.5l3.2 3.2L17.5 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        whileInView={{ pathLength: 1 }}
        viewport={{ once: true, margin: "-40px" }}
        transition={{ duration: 0.45, delay, ease: "easeOut" }}
      />
    </svg>
  );
}

export function Pack() {
  return (
    <section id="pack" className="relative scroll-mt-16 py-28 sm:py-40">
      <div className="mx-auto grid max-w-7xl gap-14 px-5 sm:px-8 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <div className="lg:sticky lg:top-28">
            <Chapter n="০৪" label="What you carry" />
            <h2 className="mt-10 font-display text-4xl leading-[1.05] font-normal tracking-[-0.02em] sm:text-6xl">
              Pack light. <br />
              <em className="text-primary">Pack the right things.</em>
            </h2>
            <p className="mt-6 max-w-[42ch] leading-relaxed text-muted-foreground">
              Everything below comes with a free account. No coaching batch to join, no
              Friday queue, no waiting a week to find out how you did.
            </p>
          </div>
        </div>

        <div className="lg:col-span-6 lg:col-start-7">
          <div className="flex items-baseline justify-between border-b-2 border-foreground pb-3 font-mono text-[11px] uppercase tracking-[0.18em]">
            <span>Packing list</span>
            <span className="text-muted-foreground">{ITEMS.length} items</span>
          </div>
          <ol>
            {ITEMS.map((it, i) => (
              <motion.li
                key={it.item}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                className="group grid grid-cols-[2rem_1fr_auto] items-start gap-4 border-b border-border py-5"
              >
                <span className="pt-1 font-mono text-xs tabular-nums text-muted-foreground">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="text-lg font-medium tracking-tight">{it.item}</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{it.note}</p>
                </div>
                <span className="pt-1">
                  <Tick delay={0.25} />
                </span>
              </motion.li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
