"use client";

import * as React from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { ArrowRight, GraduationCap, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fadeUp, staggerContainer } from "@/lib/motion";

/** The still stand-in: same footprint, no WebGL, nothing animating. */
function HeroOrb() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="relative flex items-center justify-center">
        <div
          aria-hidden
          className="absolute size-64 rounded-full bg-gradient-to-br from-primary/30 via-secondary/25 to-accent/20 blur-3xl sm:size-80"
        />
        <span className="glass relative flex size-32 items-center justify-center rounded-[38px] shadow-soft sm:size-40">
          <Sparkles className="size-14 text-primary sm:size-16" aria-hidden />
        </span>
      </div>
    </div>
  );
}

const RobotHero = dynamic(() => import("@/components/three/robot"), {
  ssr: false,
  loading: () => <HeroOrb />,
});

/**
 * Whether this visit gets the 3D robot at all.
 *
 * three + drei are ~875KB of JavaScript for one decorative mascot, and a
 * dynamic import only downloads when something renders it -- so a phone that
 * never mounts the Canvas never pays for the bundle. Two ways to opt out:
 *
 *   - `prefers-reduced-motion`, where a mascot that floats and tracks the
 *     pointer is exactly what the setting is asking us not to do;
 *   - narrow screens, which are also where the download costs most and where
 *     the hero is a single column with the robot below the copy anyway.
 *
 * Starts false so the first paint never waits on the decision, and the import
 * begins after hydration rather than competing with it.
 */
function useRobotAllowed() {
  const [allowed, setAllowed] = React.useState(false);

  React.useEffect(() => {
    const queries = [
      window.matchMedia("(prefers-reduced-motion: no-preference)"),
      window.matchMedia("(min-width: 1024px)"),
    ];
    const update = () => setAllowed(queries.every((q) => q.matches));

    // Wait for a quiet moment before the first mount. Mounting immediately
    // starts an 871KB download and a WebGL context while the page is still
    // hydrating and fetching fonts, which is the worst possible time to ask
    // for either. Idle costs the mascot a beat and costs the reader nothing.
    const idle = window.requestIdleCallback
      ? window.requestIdleCallback(update, { timeout: 2000 })
      : window.setTimeout(update, 700);

    queries.forEach((q) => q.addEventListener("change", update));
    return () => {
      if (window.cancelIdleCallback) window.cancelIdleCallback(idle as number);
      else window.clearTimeout(idle as number);
      queries.forEach((q) => q.removeEventListener("change", update));
    };
  }, []);

  return allowed;
}

export function Hero() {
  const robotAllowed = useRobotAllowed();

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
            Meet{" "}
            <span className="text-gradient animate-gradient-x bg-[length:200%_auto]">
              Oratio
            </span>
            , your AI IELTS instructor
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
          {robotAllowed ? <RobotHero className="h-full w-full" /> : <HeroOrb />}
        </motion.div>
      </div>
    </section>
  );
}
