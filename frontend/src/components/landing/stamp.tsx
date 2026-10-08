"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Chapter } from "@/components/landing/chapter";

/*
 * Real slips, the kind a Bangla-speaking student actually makes — so the page
 * shows what the marking is like instead of describing it.
 */
const CORRECTIONS = [
  {
    wrong: "I am agree with this opinion.",
    cut: "am ",
    why: "“Agree” is already the verb. It does not take “am”.",
    criterion: "Grammar",
  },
  {
    wrong: "Many students go abroad for higher study.",
    cut: "higher study",
    fix: "higher education",
    why: "“Higher study” is a Bangla-English phrase. Examiners read it as a word-choice slip.",
    criterion: "Lexical resource",
  },
  {
    wrong: "We should discuss about the problem.",
    cut: "about ",
    why: "“Discuss” takes its object directly: discuss the problem.",
    criterion: "Grammar",
  },
];

const CRITERIA = [
  { name: "Task response", band: "7.0" },
  { name: "Coherence & cohesion", band: "6.5" },
  { name: "Lexical resource", band: "7.0" },
  { name: "Grammatical range & accuracy", band: "6.5" },
];

function Sentence({ c }: { c: (typeof CORRECTIONS)[number] }) {
  const i = c.wrong.indexOf(c.cut);
  const before = c.wrong.slice(0, i);
  const after = c.wrong.slice(i + c.cut.length);
  return (
    <p className="font-display text-xl leading-relaxed sm:text-[1.4rem]">
      {before}
      <span className="text-sun line-through decoration-sun decoration-2">{c.cut}</span>
      {"fix" in c && c.fix && (
        <span className="ml-1 rounded-[3px] bg-primary/10 px-1 text-primary">{c.fix}</span>
      )}
      {after}
    </p>
  );
}

export function Stamp() {
  const reduce = useReducedMotion();

  return (
    <section id="stamp" className="relative scroll-mt-16 border-y border-border bg-card py-28 sm:py-40">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <Chapter n="০৩" label="The marking" />
        <h2 className="mt-10 max-w-4xl font-display text-4xl leading-[1.05] font-normal tracking-[-0.02em] sm:text-6xl">
          Not just a number. <em className="text-primary">The reason</em> for the number.
        </h2>

        <div className="mt-16 grid gap-12 lg:grid-cols-12 lg:gap-10">
          {/* the corrected page */}
          <div className="bg-khata relative rounded-2xl border border-border bg-background p-6 pl-[4.5rem] [--margin:3.25rem] sm:p-10 sm:pl-24 sm:[--margin:4.5rem] lg:col-span-7">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Your essay · paragraph 1
            </p>
            <div className="mt-6 space-y-9">
              {CORRECTIONS.map((c, i) => (
                <motion.div
                  key={c.wrong}
                  initial={{ opacity: 0, x: -10 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: "-80px" }}
                  transition={{ duration: 0.7, delay: i * 0.15, ease: [0.16, 1, 0.3, 1] }}
                >
                  <Sentence c={c} />
                  <p className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-muted-foreground">
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-sun">{c.criterion}</span>
                    {c.why}
                  </p>
                </motion.div>
              ))}
            </div>
          </div>

          {/* the passport page with the stamp */}
          <div className="relative lg:col-span-5">
            <div className="rounded-2xl border border-border bg-background p-6 sm:p-8">
              <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                <span>Writing · Task 2</span>
                <span>Page 07</span>
              </div>

              <div className="relative mt-8 flex justify-center py-4">
                <motion.div
                  initial={reduce ? false : { opacity: 0, scale: 1.7, rotate: -26 }}
                  whileInView={{ opacity: 1, scale: 1, rotate: -9 }}
                  viewport={{ once: true, margin: "-120px" }}
                  transition={{ type: "spring", stiffness: 320, damping: 17, mass: 0.9, delay: 0.2 }}
                  className="relative size-52 text-sun sm:size-60"
                >
                  <svg viewBox="0 0 200 200" className="absolute inset-0 size-full" aria-hidden>
                    <defs>
                      <path id="stamp-ring" d="M100,100 m-78,0 a78,78 0 1,1 156,0 a78,78 0 1,1 -156,0" />
                    </defs>
                    <circle cx="100" cy="100" r="96" fill="none" stroke="currentColor" strokeWidth="3" />
                    <circle cx="100" cy="100" r="64" fill="none" stroke="currentColor" strokeWidth="1.5" />
                    <text className="fill-current font-mono text-[11px] tracking-[0.32em] uppercase">
                      <textPath href="#stamp-ring">Oratio · Practice band · Writing ·</textPath>
                    </text>
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="font-mono text-[10px] uppercase tracking-[0.2em]">Band</span>
                    <span className="font-display text-6xl leading-none">7.0</span>
                  </div>
                </motion.div>
              </div>

              <dl className="mt-8 divide-y divide-border border-t border-border">
                {CRITERIA.map((c) => (
                  <div key={c.name} className="flex items-baseline justify-between gap-4 py-3">
                    <dt className="text-sm text-muted-foreground">{c.name}</dt>
                    <dd className="font-mono text-sm tabular-nums">{c.band}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Bands are practice estimates against the public IELTS band descriptors, not
              official results. Use them to see where you stand and what to fix.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
