"use client";

import { motion } from "framer-motion";
import type { PracticeQuestion } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Visuals } from "@/components/practice/visual";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function questionKey(q: PracticeQuestion, index: number): string {
  if (typeof q.id === "string" && q.id) return q.id;
  if (typeof q.number === "number") return String(q.number);
  return String(index + 1);
}

function optionEntries(
  options: PracticeQuestion["options"]
): Array<[string, string]> {
  if (!options) return [];
  if (Array.isArray(options)) {
    return options.map((o, i) => [String.fromCharCode(65 + i), String(o)]);
  }
  return Object.entries(options).map(([k, v]) => [k, String(v)]);
}

export function QuestionList({
  questions,
  answers,
  onAnswer,
  disabled,
  results,
}: {
  questions: PracticeQuestion[];
  answers: Record<string, string>;
  onAnswer: (key: string, value: string) => void;
  disabled?: boolean;
  results?: Record<string, { correct?: boolean; correct_answer?: string }> | null;
}) {
  return (
    <motion.ol
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
      className="space-y-5"
    >
      {questions.map((q, i) => {
        const key = questionKey(q, i);
        const text =
          (typeof q.question === "string" && q.question) ||
          (typeof q.text === "string" && q.text) ||
          `Question ${key}`;
        const opts = optionEntries(q.options);
        const verdict = results?.[key];

        return (
          <motion.li
            key={key}
            variants={fadeUp}
            className={cn(
              "glass rounded-[20px] p-5 shadow-soft transition-shadow",
              verdict?.correct === true && "border-success/40",
              verdict?.correct === false && "border-danger/40"
            )}
          >
            <p className="text-sm font-medium leading-relaxed">
              <span className="mr-2 inline-flex size-6 items-center justify-center rounded-lg bg-primary/10 text-xs font-semibold text-primary">
                {key.replace(/^Q/i, "")}
              </span>
              {text}
            </p>

            <Visuals visual={q.visual} visuals={q.visuals} className="mt-3" />

            {opts.length > 0 ? (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {opts.map(([letter, label]) => {
                  const selected = answers[key] === letter;
                  return (
                    <button
                      key={letter}
                      type="button"
                      disabled={disabled}
                      onClick={() => onAnswer(key, letter)}
                      className={cn(
                        "flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left text-sm transition-all",
                        selected
                          ? "border-primary/50 bg-primary/10 text-foreground shadow-glow"
                          : "border-border text-muted-foreground hover:border-primary/30 hover:bg-muted"
                      )}
                    >
                      <span
                        className={cn(
                          "flex size-6 shrink-0 items-center justify-center rounded-lg text-xs font-semibold",
                          selected ? "bg-primary text-white" : "bg-muted"
                        )}
                      >
                        {letter}
                      </span>
                      {label}
                    </button>
                  );
                })}
              </div>
            ) : (
              <Input
                value={answers[key] ?? ""}
                onChange={(e) => onAnswer(key, e.target.value)}
                disabled={disabled}
                placeholder="Type your answer…"
                className="mt-3"
                aria-label={`Answer to question ${key}`}
              />
            )}

            {verdict && verdict.correct === false && verdict.correct_answer && (
              <p className="mt-2 text-xs text-danger">
                Correct answer: <span className="font-medium">{verdict.correct_answer}</span>
              </p>
            )}
          </motion.li>
        );
      })}
    </motion.ol>
  );
}
