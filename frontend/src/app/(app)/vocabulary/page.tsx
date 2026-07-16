"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw, Check, X } from "lucide-react";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "@/components/ui/progress";

interface Card {
  word: string;
  meaning: string;
  example: string;
}

const DECK: Card[] = [
  { word: "ubiquitous", meaning: "present or found everywhere", example: "Smartphones have become ubiquitous in modern society." },
  { word: "mitigate", meaning: "to make less severe or serious", example: "Governments must act to mitigate the effects of climate change." },
  { word: "exacerbate", meaning: "to make a problem worse", example: "Traffic congestion is exacerbated by poor urban planning." },
  { word: "paradigm", meaning: "a typical example or model of something", example: "Remote work represents a new paradigm in employment." },
  { word: "unprecedented", meaning: "never done or known before", example: "The pandemic caused unprecedented disruption to education." },
  { word: "detrimental", meaning: "causing harm or damage", example: "Excessive screen time can be detrimental to children's health." },
  { word: "advocate", meaning: "to publicly support or recommend", example: "Many experts advocate investing in renewable energy." },
  { word: "phenomenon", meaning: "a fact or situation that is observed to happen", example: "Urbanisation is a global phenomenon." },
  { word: "substantiate", meaning: "to provide evidence to support a claim", example: "The researcher substantiated her argument with recent data." },
  { word: "proliferation", meaning: "rapid increase in number or amount", example: "The proliferation of online courses has widened access to education." },
  { word: "compelling", meaning: "evoking interest or conviction powerfully", example: "There is compelling evidence that exercise improves mental health." },
  { word: "discrepancy", meaning: "a lack of agreement between facts", example: "There is a discrepancy between the two survey results." },
  { word: "feasible", meaning: "possible to do easily or conveniently", example: "Building more cycle lanes is a feasible solution to congestion." },
  { word: "inevitably", meaning: "in a way that cannot be avoided", example: "Technological change inevitably transforms the job market." },
  { word: "scrutinise", meaning: "to examine closely and critically", example: "Policy proposals should be scrutinised before implementation." },
];

type Verdict = "known" | "learning";

const STORAGE_KEY = "ai-ielts-vocab";
const emptySubscribe = () => () => {};

function loadVerdicts(): Record<string, Verdict> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export default function VocabularyPage() {
  const [index, setIndex] = React.useState(0);
  const [flipped, setFlipped] = React.useState(false);
  const mounted = React.useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
  const stored = React.useMemo(() => (mounted ? loadVerdicts() : {}), [mounted]);
  const [overrides, setOverrides] = React.useState<Record<string, Verdict> | null>(null);
  const verdicts = overrides ?? stored;

  const card = DECK[index];
  const knownCount = Object.values(verdicts).filter((v) => v === "known").length;
  const done = index >= DECK.length;

  const mark = (verdict: Verdict) => {
    const next = { ...verdicts, [card.word]: verdict };
    setOverrides(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setFlipped(false);
    setTimeout(() => setIndex((i) => i + 1), 150);
  };

  const restart = () => {
    setIndex(0);
    setFlipped(false);
  };

  return (
    <div className="mx-auto max-w-2xl">
      <Topbar title="Vocabulary" />

      <div className="mb-6 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">
            Card {Math.min(index + 1, DECK.length)} of {DECK.length}
          </span>
          <Badge variant="success">{knownCount} mastered</Badge>
        </div>
        <ProgressBar value={(index / DECK.length) * 100} />
      </div>

      <AnimatePresence mode="wait">
        {done ? (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="glass-strong rounded-[28px] p-10 text-center shadow-soft"
          >
            <div className="font-display text-5xl">🎉</div>
            <h2 className="mt-4 font-display text-2xl font-bold">Deck complete!</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              You marked {knownCount} of {DECK.length} words as mastered.
            </p>
            <Button size="lg" className="mt-8" onClick={restart}>
              <RotateCcw className="size-4" aria-hidden />
              Review again
            </Button>
          </motion.div>
        ) : (
          <motion.div
            key={card.word}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            transition={{ duration: 0.25 }}
          >
            <button
              onClick={() => setFlipped((f) => !f)}
              className="block w-full [perspective:1200px]"
              aria-label={flipped ? "Show word" : "Show meaning"}
            >
              <motion.div
                animate={{ rotateY: flipped ? 180 : 0 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                className="relative h-72 w-full [transform-style:preserve-3d]"
              >
                {/* Front */}
                <div className="glass-strong absolute inset-0 flex flex-col items-center justify-center rounded-[28px] p-8 shadow-soft [backface-visibility:hidden]">
                  <Badge variant="secondary" className="mb-4">
                    Tap to flip
                  </Badge>
                  <div className="font-display text-4xl font-bold text-gradient">
                    {card.word}
                  </div>
                  {verdicts[card.word] === "known" && (
                    <Badge variant="success" className="mt-4">
                      Previously mastered
                    </Badge>
                  )}
                </div>
                {/* Back */}
                <div className="glass-strong absolute inset-0 flex rotate-y-180 flex-col items-center justify-center rounded-[28px] p-8 text-center shadow-soft [backface-visibility:hidden] [transform:rotateY(180deg)]">
                  <p className="text-lg font-medium">{card.meaning}</p>
                  <p className="mt-4 text-sm italic text-muted-foreground">
                    “{card.example}”
                  </p>
                </div>
              </motion.div>
            </button>

            <div className="mt-6 flex justify-center gap-3">
              <Button variant="secondary" size="lg" onClick={() => mark("learning")}>
                <X className="size-4 text-danger" aria-hidden />
                Still learning
              </Button>
              <Button variant="success" size="lg" onClick={() => mark("known")}>
                <Check className="size-4" aria-hidden />
                I know this
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
