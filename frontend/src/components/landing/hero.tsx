"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { ArrowRight, GraduationCap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fadeUp, staggerContainer } from "@/lib/motion";

const RobotHero = dynamic(() => import("@/components/three/robot"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center">
      <div className="size-40 animate-pulse-glow rounded-full bg-primary/10" />
    </div>
  ),
});

export function Hero() {
  return (
    <section id="home" className="relative overflow-hidden pt-36 pb-20 sm:pt-44">
      {/* Ambient blurred orbs */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-32 left-1/4 size-[480px] animate-aurora rounded-full bg-primary/20 blur-[120px]" />
        <div className="absolute top-40 right-0 size-[400px] animate-aurora rounded-full bg-accent/20 blur-[120px] [animation-delay:-6s]" />
        <div className="absolute bottom-0 left-0 size-[360px] animate-aurora rounded-full bg-secondary/15 blur-[110px] [animation-delay:-3s]" />
      </div>

      <div className="mx-auto grid max-w-6xl items-center gap-10 px-6 lg:grid-cols-2">
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="text-center lg:text-left"
        >
          <motion.div variants={fadeUp} className="mb-6 inline-block">
            <Badge className="px-4 py-1.5 text-sm">
              <GraduationCap className="size-4" aria-hidden />
              AI-powered instructor &amp; examiner
            </Badge>
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="font-display text-4xl font-bold leading-[1.08] tracking-tight sm:text-6xl"
          >
            Your Personal{" "}
            <span className="text-gradient animate-gradient-x bg-[length:200%_auto]">
              AI IELTS
            </span>{" "}
            Instructor
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground lg:mx-0"
          >
            Practice. Learn. Improve. Achieve your dream IELTS band with an AI
            instructor that teaches, evaluates, explains mistakes, and creates
            unlimited IELTS-style exams.
          </motion.p>

          <motion.div
            variants={fadeUp}
            className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start"
          >
            <Link href="/register">
              <Button size="lg" className="w-full sm:w-auto">
                Start Free
                <ArrowRight className="size-4" aria-hidden />
              </Button>
            </Link>
            <Link href="/register">
              <Button variant="secondary" size="lg" className="w-full sm:w-auto">
                Take AI Mock Test
              </Button>
            </Link>
          </motion.div>

          <motion.div
            variants={fadeUp}
            className="mt-12 flex items-center justify-center gap-8 lg:justify-start"
          >
            {[
              ["4", "Skills covered"],
              ["∞", "AI-generated exams"],
              ["24/7", "Instant feedback"],
            ].map(([value, label]) => (
              <div key={label} className="text-center lg:text-left">
                <div className="font-display text-2xl font-bold text-gradient">
                  {value}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
              </div>
            ))}
          </motion.div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
          className="relative h-[380px] sm:h-[480px]"
        >
          <RobotHero className="h-full w-full" />
        </motion.div>
      </div>
    </section>
  );
}
