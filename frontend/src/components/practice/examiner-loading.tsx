"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LogoMark } from "@/components/brand/logo";

const messages = [
  "Reading your response…",
  "Checking task achievement…",
  "Analysing coherence and cohesion…",
  "Evaluating vocabulary range…",
  "Reviewing grammar accuracy…",
  "Comparing against band descriptors…",
  "Writing detailed feedback…",
];

export function ExaminerLoading({ label = "Marking your answer" }: { label?: string }) {
  const [idx, setIdx] = React.useState(0);

  React.useEffect(() => {
    const t = setInterval(() => setIdx((i) => (i + 1) % messages.length), 6000);
    return () => clearInterval(t);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="glass-strong flex flex-col items-center rounded-2xl p-10 text-center shadow-soft"
      role="status"
      aria-live="polite"
    >
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
        className="relative mb-6 flex size-20 items-center justify-center"
      >
        <span className="absolute inset-0 rounded-full border-2 border-dashed border-primary/40" />
        <span className="flex size-14 items-center justify-center rounded-full bg-card text-foreground">
          <LogoMark className="size-8" />
        </span>
      </motion.div>

      <h3 className="font-display text-2xl">{label}</h3>
      <div className="mt-2 h-6">
        <AnimatePresence mode="wait">
          <motion.p
            key={idx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="text-sm text-muted-foreground"
          >
            {messages[idx]}
          </motion.p>
        </AnimatePresence>
      </div>
      <p className="mt-4 max-w-xs text-xs text-muted-foreground/70">
        Marking takes a minute or two. You can keep this tab open and come
        back to it.
      </p>
    </motion.div>
  );
}
