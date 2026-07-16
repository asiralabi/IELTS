"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  Headphones,
  BookOpen,
  PenLine,
  Mic,
  Layers,
  ArrowUpRight,
} from "lucide-react";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { cn } from "@/lib/utils";

const modules = [
  {
    icon: Headphones,
    title: "Listening",
    body: "AI-scripted recordings with authentic question types and instant scoring.",
    tint: "from-sky-500/15 to-blue-500/10 text-sky-500",
    glow: "hover:shadow-[0_20px_50px_-16px_rgb(56_189_248/0.45)]",
  },
  {
    icon: BookOpen,
    title: "Reading",
    body: "Academic passages, synced questions, highlights and a built-in dictionary.",
    tint: "from-violet-500/15 to-purple-500/10 text-violet-500",
    glow: "hover:shadow-[0_20px_50px_-16px_rgb(124_77_255/0.45)]",
  },
  {
    icon: PenLine,
    title: "Writing",
    body: "Focus-mode editor with live word count and full examiner feedback.",
    tint: "from-orange-500/15 to-amber-500/10 text-orange-500",
    glow: "hover:shadow-[0_20px_50px_-16px_rgb(249_115_22/0.45)]",
  },
  {
    icon: Mic,
    title: "Speaking",
    body: "Answer real Part 1–3 questions and get pronunciation-aware band scores.",
    tint: "from-emerald-500/15 to-green-500/10 text-emerald-500",
    glow: "hover:shadow-[0_20px_50px_-16px_rgb(34_197_94/0.45)]",
  },
  {
    icon: Layers,
    title: "Vocabulary",
    body: "Smart flashcards built from the words you actually get wrong.",
    tint: "from-pink-500/15 to-rose-500/10 text-pink-500",
    glow: "hover:shadow-[0_20px_50px_-16px_rgb(236_72_153/0.45)]",
  },
];

export function Modules() {
  return (
    <section id="modules" className="relative py-24">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-mesh" />
      <div className="mx-auto max-w-6xl px-6">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          className="text-center"
        >
          <motion.h2
            variants={fadeUp}
            className="font-display text-3xl font-bold tracking-tight sm:text-5xl"
          >
            Master every <span className="text-gradient">skill</span>
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="mx-auto mt-4 max-w-2xl text-muted-foreground"
          >
            Five practice modules, one intelligent examiner.
          </motion.p>
        </motion.div>

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
        >
          {modules.map((m) => (
            <motion.div key={m.title} variants={fadeUp}>
              <Link href="/register" className="block h-full">
                <motion.div
                  whileHover={{ y: -8, rotate: 2 }}
                  transition={{ type: "spring", stiffness: 280, damping: 18 }}
                  className={cn(
                    "group glass h-full rounded-[28px] p-6 shadow-soft transition-shadow duration-300",
                    m.glow
                  )}
                >
                  <div className="flex items-start justify-between">
                    <div
                      className={cn(
                        "inline-flex size-13 items-center justify-center rounded-2xl bg-gradient-to-br p-3 transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6",
                        m.tint
                      )}
                    >
                      <m.icon className="size-6" aria-hidden />
                    </div>
                    <ArrowUpRight className="size-5 text-muted-foreground opacity-0 transition-all duration-300 group-hover:translate-x-0.5 group-hover:opacity-100" />
                  </div>
                  <h3 className="mt-4 font-display text-xl font-semibold">
                    {m.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {m.body}
                  </p>
                </motion.div>
              </Link>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
