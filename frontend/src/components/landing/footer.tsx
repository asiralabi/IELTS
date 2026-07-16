"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { fadeUp, staggerContainer } from "@/lib/motion";

export function Footer() {
  return (
    <footer id="about" className="relative mt-12 pb-10">
      <div className="mx-auto max-w-6xl px-6">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
          className="glass-strong overflow-hidden rounded-[28px] p-10 text-center shadow-soft"
        >
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 bg-mesh"
          />
          <motion.h2
            variants={fadeUp}
            className="font-display text-2xl font-bold tracking-tight sm:text-4xl"
          >
            Ready to meet your <span className="text-gradient">AI examiner</span>?
          </motion.h2>
          <motion.p variants={fadeUp} className="mx-auto mt-3 max-w-xl text-muted-foreground">
            Join learners who stopped guessing their band score and started
            improving it.
          </motion.p>
          <motion.div variants={fadeUp} className="mt-8">
            <Link
              href="/register"
              className="inline-flex h-13 items-center justify-center rounded-[20px] bg-gradient-to-r from-primary via-secondary to-primary bg-[length:200%_auto] px-8 font-medium text-white shadow-lift transition-all hover:bg-[position:100%_50%] hover:shadow-glow"
            >
              Start Free Today
            </Link>
          </motion.div>
        </motion.div>

        <div className="mt-10 flex flex-col items-center justify-between gap-4 text-sm text-muted-foreground sm:flex-row">
          <div className="flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary">
              <Sparkles className="size-4 text-white" aria-hidden />
            </span>
            <span className="font-display font-semibold text-foreground">AI IELTS</span>
          </div>
          <p>Built with an AI instructor, examiner &amp; mentor at its core.</p>
          <p>© {new Date().getFullYear()} AI IELTS</p>
        </div>
      </div>
    </footer>
  );
}
