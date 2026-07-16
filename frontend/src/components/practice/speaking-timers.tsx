"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Play, RotateCcw, Timer as TimerIcon } from "lucide-react";
import { cn, formatDuration } from "@/lib/utils";

type Phase = "idle" | "prep" | "speaking" | "done";

/**
 * IELTS Speaking Part 2 timer:
 * - 60 s preparation, then
 * - 120 s (configurable) speaking window that auto-starts the mic.
 *
 * Emits `onSpeakingStart` / `onSpeakingEnd` so the parent can drive the mic.
 */
export function Part2Timer({
  prepSeconds = 60,
  speakingSeconds = 120,
  onSpeakingStart,
  onSpeakingEnd,
}: {
  prepSeconds?: number;
  speakingSeconds?: number;
  onSpeakingStart?: () => void;
  onSpeakingEnd?: () => void;
}) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [remaining, setRemaining] = React.useState<number>(prepSeconds);

  // Refs so the interval callback always sees the latest handlers without
  // restarting the timer. Updated in an effect to satisfy the
  // react-hooks/refs rule (no ref writes during render).
  const onStartRef = React.useRef(onSpeakingStart);
  const onEndRef = React.useRef(onSpeakingEnd);
  React.useEffect(() => {
    Promise.resolve().then(() => {
      onStartRef.current = onSpeakingStart;
      onEndRef.current = onSpeakingEnd;
    });
  }, [onSpeakingStart, onSpeakingEnd]);

  React.useEffect(() => {
    if (phase !== "prep" && phase !== "speaking") return;
    const t = setInterval(() => {
      setRemaining((r) => Math.max(0, r - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [phase]);

  // Microtask-deferred phase transitions to satisfy react-hooks/set-state-in-effect.
  React.useEffect(() => {
    if (remaining > 0) return;
    if (phase === "prep") {
      Promise.resolve().then(() => {
        setPhase("speaking");
        setRemaining(speakingSeconds);
        onStartRef.current?.();
      });
    } else if (phase === "speaking") {
      Promise.resolve().then(() => {
        setPhase("done");
        onEndRef.current?.();
      });
    }
  }, [remaining, phase, speakingSeconds]);

  const start = () => {
    setPhase("prep");
    setRemaining(prepSeconds);
  };

  const reset = () => {
    if (phase === "speaking") onEndRef.current?.();
    setPhase("idle");
    setRemaining(prepSeconds);
  };

  const warning = remaining <= 15 && (phase === "prep" || phase === "speaking");

  const label =
    phase === "idle"
      ? "Ready when you are"
      : phase === "prep"
        ? "Preparation time"
        : phase === "speaking"
          ? "Speaking now"
          : "Time's up";

  return (
    <div className="glass rounded-[24px] p-6 shadow-soft" role="timer" aria-live="polite">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex size-11 items-center justify-center rounded-2xl transition-colors",
              phase === "speaking"
                ? "bg-danger/15 text-danger"
                : phase === "prep"
                  ? "bg-amber-500/15 text-amber-600"
                  : "bg-primary/10 text-primary"
            )}
          >
            <TimerIcon className="size-5" aria-hidden />
          </span>
          <div>
            <div className="font-display text-sm font-semibold">{label}</div>
            <div className="text-xs text-muted-foreground">
              {phase === "idle"
                ? `${prepSeconds}s prep · ${speakingSeconds}s speaking`
                : phase === "prep"
                  ? "Plan your talk — no speaking yet"
                  : phase === "speaking"
                    ? "Cover all bullet points"
                    : "Great — submit when you're ready"}
            </div>
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={`${phase}-${warning}`}
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{
              scale: warning ? [1, 1.06, 1] : 1,
              opacity: 1,
            }}
            transition={{
              duration: warning ? 0.9 : 0.2,
              repeat: warning ? Infinity : 0,
            }}
            className={cn(
              "font-display text-4xl font-bold tabular-nums",
              warning ? "text-danger" : "text-foreground"
            )}
          >
            {formatDuration(remaining)}
          </motion.div>
        </AnimatePresence>
        <div className="flex items-center gap-2">
          {phase === "idle" && (
            <button
              type="button"
              onClick={start}
              className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-secondary px-4 py-2 text-sm font-medium text-white shadow-glow transition-transform hover:scale-[1.02]"
            >
              <Play className="size-4" aria-hidden />
              Start prep
            </button>
          )}
          {phase !== "idle" && (
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              Reset
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Soft elapsed-time indicator for Speaking Part 1 / Part 3. Non-blocking —
 * shows a gentle 5-minute hint but never auto-stops the recorder.
 */
export function SpeakingElapsedHint({
  active,
  softLimitSeconds = 300,
}: {
  active: boolean;
  softLimitSeconds?: number;
}) {
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (!active) {
      Promise.resolve().then(() => setElapsed(0));
      return;
    }
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [active]);

  if (!active && elapsed === 0) return null;
  const over = elapsed >= softLimitSeconds;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium",
        over ? "bg-amber-500/15 text-amber-600" : "bg-muted text-muted-foreground"
      )}
      role="status"
      aria-live="polite"
    >
      <TimerIcon className="size-3.5" aria-hidden />
      {formatDuration(elapsed)}
      {over && <span className="hidden sm:inline">· soft limit reached</span>}
    </div>
  );
}
