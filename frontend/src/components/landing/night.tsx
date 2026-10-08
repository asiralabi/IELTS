"use client";

import * as React from "react";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { Chapter } from "@/components/landing/chapter";

const PASSAGE =
  "It is 1:40 in the morning. The ceiling fan is the only sound in the room. You have a Cambridge book open at Test 3, a timer on your phone set to sixty minutes, and an essay you have read four times. Nobody can tell you whether it is a six or a seven.";

function Word({
  word,
  index,
  total,
  progress,
}: {
  word: string;
  index: number;
  total: number;
  progress: MotionValue<number>;
}) {
  const start = index / total;
  const opacity = useTransform(progress, [start, start + 1 / total], [0.16, 1]);
  return (
    <motion.span style={{ opacity }} className="inline">
      {word}{" "}
    </motion.span>
  );
}

const NOTES = [
  {
    k: "The coaching centre",
    v: "Fees that cost months of savings, and a class of forty where your essay gets two minutes.",
  },
  {
    k: "The mock test",
    v: "On one Friday, across the city, through traffic, if there is still a seat.",
  },
  {
    k: "The feedback",
    v: "A number on a sheet, a week later. Not why. Not what to change.",
  },
];

export function Night() {
  const ref = React.useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "end 0.55"] });
  const words = PASSAGE.split(" ");

  return (
    <section id="night" className="relative scroll-mt-16 overflow-hidden bg-[#111814] py-28 text-[#efe9dc] sm:py-40">
      {/* the clock on the wall */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-6 right-[-2%] font-mono text-[9rem] leading-none font-medium tracking-tighter text-white/[0.035] select-none sm:text-[16rem] lg:text-[22rem]"
      >
        01:40
      </div>

      <div className="relative mx-auto max-w-7xl px-5 sm:px-8">
        <Chapter n="০১" label="The night before" tone="inverse" />

        <div ref={ref} className="mt-12 max-w-5xl">
          <p className="font-display text-[1.75rem] leading-[1.32] tracking-[-0.012em] sm:text-[2.6rem] lg:text-[3.15rem]">
            {reduce
              ? PASSAGE
              : words.map((w, i) => (
                  <Word key={i} word={w} index={i} total={words.length} progress={scrollYProgress} />
                ))}
          </p>
        </div>

        <div className="mt-20 grid gap-10 border-t border-white/10 pt-10 md:grid-cols-3 md:gap-8">
          {NOTES.map((n, i) => (
            <motion.div
              key={n.k}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.8, delay: i * 0.12, ease: [0.16, 1, 0.3, 1] }}
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sun">{n.k}</p>
              <p className="mt-3 max-w-[34ch] leading-relaxed text-[#efe9dc]/70">{n.v}</p>
            </motion.div>
          ))}
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 1 }}
          className="mt-24 max-w-2xl font-display text-2xl italic leading-snug text-[#efe9dc]/85 sm:text-3xl"
        >
          Every year, tens of thousands of students leave Bangladesh to study abroad.
          Most of them sit the test that night — alone, at a desk, guessing.
          <span className="not-italic text-[#8fd3ae]"> Oratio was made for that desk.</span>
        </motion.p>
      </div>
    </section>
  );
}
