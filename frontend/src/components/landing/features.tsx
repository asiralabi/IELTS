"use client";

import { motion } from "framer-motion";
import {
  Bot,
  ClipboardCheck,
  LineChart,
  MessageSquareText,
  ScrollText,
  Target,
} from "lucide-react";
import { GlowCard } from "@/components/ui/card";
import { fadeUp, staggerContainer } from "@/lib/motion";

const features = [
  {
    icon: Bot,
    title: "AI Instructor",
    body: "Chat with a tutor that explains grammar, vocabulary and strategy — and remembers your session.",
  },
  {
    icon: ClipboardCheck,
    title: "Real Examiner Scoring",
    body: "Essays and speaking answers are marked against official band descriptors with criterion-level scores.",
  },
  {
    icon: ScrollText,
    title: "Unlimited Mock Exams",
    body: "Generate full four-skill IELTS exams on demand, targeted at your goal band.",
  },
  {
    icon: MessageSquareText,
    title: "Mistake Explanations",
    body: "Every error is broken down: what went wrong, why, and exactly how to fix it.",
  },
  {
    icon: LineChart,
    title: "Progress Analytics",
    body: "Band trajectories, skill radars and weakness heatmaps — see improvement, not guesswork.",
  },
  {
    icon: Target,
    title: "Personal Study Plan",
    body: "An adaptive plan built from your weaknesses, updated as your scores evolve.",
  },
];

export function Features() {
  return (
    <section id="features" className="relative py-24">
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
            Everything you need to reach{" "}
            <span className="text-gradient">Band 9</span>
          </motion.h2>
          <motion.p
            variants={fadeUp}
            className="mx-auto mt-4 max-w-2xl text-muted-foreground"
          >
            A complete preparation system — teacher, examiner and mentor in one
            intelligent platform.
          </motion.p>
        </motion.div>

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
        >
          {features.map((f) => (
            <motion.div key={f.title} variants={fadeUp}>
              <GlowCard className="h-full p-6">
                <div className="mb-4 inline-flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/15 to-secondary/15 text-primary transition-transform duration-300 group-hover:scale-110">
                  <f.icon className="size-6" aria-hidden />
                </div>
                <h3 className="font-display text-lg font-semibold">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {f.body}
                </p>
              </GlowCard>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
