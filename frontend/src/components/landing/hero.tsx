"use client";

import * as React from "react";
import Link from "next/link";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { DepartureBoard } from "@/components/landing/departure-board";

const ease = [0.16, 1, 0.3, 1] as const;

function Line({ children, delay }: { children: React.ReactNode; delay: number }) {
  // Each line rises out of its own mask, like type set one line at a time.
  return (
    <span className="block overflow-hidden pb-[0.08em]">
      <motion.span
        className="block"
        initial={{ y: "105%" }}
        animate={{ y: 0 }}
        transition={{ duration: 1, delay, ease }}
      >
        {children}
      </motion.span>
    </span>
  );
}

export function Hero() {
  const ref = React.useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  // The sun climbs as you scroll away from Bangladesh.
  const sunY = useTransform(scrollYProgress, [0, 1], ["0%", reduce ? "0%" : "-18%"]);
  const boardY = useTransform(scrollYProgress, [0, 1], [0, reduce ? 0 : -40]);

  return (
    <section ref={ref} id="home" className="relative overflow-hidden">
      {/* paper half */}
      <div className="relative z-10 mx-auto max-w-7xl px-5 pt-32 sm:px-8 sm:pt-40 lg:pt-44">
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.1 }}
          className="flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground"
        >
          <span className="inline-block size-2 rounded-full bg-sun" aria-hidden />
          Bangladesh · Departures · For students
        </motion.p>

        <div className="mt-8 grid gap-10 lg:grid-cols-12 lg:items-end">
          <h1 className="font-display text-[2.6rem] leading-[1.02] font-normal tracking-[-0.025em] sm:text-6xl lg:col-span-8 lg:text-[5.4rem]">
            <Line delay={0.15}>Somewhere in Bangladesh,</Line>
            <Line delay={0.27}>
              a bag is <em className="text-primary">half-packed.</em>
            </Line>
          </h1>

          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.55, ease }}
            className="lg:col-span-4 lg:pb-3"
          >
            <p className="max-w-[44ch] text-[1.05rem] leading-relaxed text-muted-foreground">
              The offer letter is close. The visa file is open. Between you and the
              seat on that plane sits one IELTS score. Oratio is where you practise
              for it: full mock tests at home, a band for every skill, and every
              mistake explained.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Link
                href="/register"
                className="group inline-flex h-12 items-center gap-2 rounded-xl bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-secondary dark:hover:bg-primary/85"
              >
                Start your first mock test
                <ArrowRight
                  className="size-4 transition-transform duration-300 group-hover:translate-x-0.5"
                  strokeWidth={1.8}
                  aria-hidden
                />
              </Link>
              <a
                href="#night"
                className="inline-flex h-12 items-center px-2 text-sm font-medium text-foreground underline decoration-border decoration-1 underline-offset-[6px] transition-colors hover:decoration-sun"
              >
                Read the story first
              </a>
            </div>
          </motion.div>
        </div>
      </div>

      {/* green half, with the sun on its horizon */}
      <div className="relative mt-24 sm:mt-32 lg:mt-36">
        <motion.div
          aria-hidden
          style={{ y: sunY }}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 1.4, delay: 0.3, ease }}
          className="absolute -top-20 right-[6%] size-44 rounded-full bg-sun sm:-top-28 sm:size-72 lg:-top-36 lg:right-[9%] lg:size-[24rem]"
        />
        <div className="relative bg-secondary pt-14 pb-20 sm:pt-20 sm:pb-28">
          <motion.div style={{ y: boardY }} className="relative mx-auto max-w-7xl px-5 sm:px-8">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 0.7, ease }}
          >
            <DepartureBoard />
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-[0.16em] text-[#efe9dc]/50 sm:text-[11px]">
              <span>Target bands shown are typical asks, not guarantees. Check your university.</span>
              <span className="flex items-center gap-2">
                Scroll for the story
                <motion.span
                  aria-hidden
                  animate={reduce ? undefined : { y: [0, 4, 0] }}
                  transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
                >
                  ↓
                </motion.span>
              </span>
            </div>
          </motion.div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
