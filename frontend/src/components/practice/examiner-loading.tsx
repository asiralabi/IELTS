"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles } from "lucide-react";

const messages = [
  "Reading your response…",
  "Checking task achievement…",
  "Analysing coherence and cohesion…",
  "Evaluating vocabulary range…",
  "Reviewing grammar accuracy…",
  "Comparing against band descriptors…",
  "Writing detailed feedback…",
];

export function ExaminerLoading({ label = "AI examiner at work" }: { label?: string }) {
  const [idx, setIdx] = React.useState(0);

  React.useEffect(() => {
    const t = setInterval(() => setIdx((i) => (i + 1) % messages.length), 6000);
    return () => clearInterval(t);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="glass-strong flex flex-col items-center rounded-[28px] p-10 text-center shadow-soft"
      role="status"
      aria-live="polite"
    >
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
        className="relative mb-6 flex size-20 items-center justify-center"
      >
        <span className="absolute inset-0 rounded-full border-2 border-dashed border-primary/40" />
        <motion.span
          animate={{ scale: [1, 1.15, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
          className="flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-secondary shadow-glow"
        >
          <Sparkles className="size-7 text-white" aria-hidden />
        </motion.span>
      </motion.div>

      <h3 className="font-display text-lg font-semibold">{label}</h3>
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
        Marking runs on a local AI model and can take a few minutes. Feel free
        to keep this tab open.
      </p>
    </motion.div>
  );
}
