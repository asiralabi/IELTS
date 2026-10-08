"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Database, BookMarked } from "lucide-react";
import { api } from "@/lib/api";
import { Topbar } from "@/components/shell/topbar";
import { GlowCard } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fadeUp, staggerContainer } from "@/lib/motion";

const TIPS = [
  {
    title: "Band descriptors are your map",
    body: "Every score you get here is aligned to the four official criteria. Read your criterion breakdown before rewriting.",
  },
  {
    title: "Little and often beats cramming",
    body: "One writing task plus twenty minutes of vocabulary daily outperforms a weekend marathon.",
  },
  {
    title: "Recycle your mistakes",
    body: "Re-attempt an essay a week after feedback. If the same error appears, add it to your flashcards.",
  },
  {
    title: "Speak before you are ready",
    body: "Fluency grows from attempts, not preparation. Answer one speaking question aloud every day.",
  },
];

export default function ResourcesPage() {
  const [documents, setDocuments] = React.useState<number | null>(null);

  React.useEffect(() => {
    api.knowledgeStatus().then((s) => setDocuments(s.documents)).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-4xl">
      <Topbar title="Resources" />

      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-6">
        <motion.div variants={fadeUp}>
          <GlowCard className="p-7">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <span className="flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary">
                  <Database className="size-6" aria-hidden />
                </span>
                <div>
                  <h2 className="font-display font-medium">Reference library</h2>
                  <p className="text-sm text-muted-foreground">
                    The IELTS books and guides that marking and study plans cite.
                    The Oratio team curates it, so every student is marked against
                    the same sources.
                  </p>
                </div>
              </div>
              <Badge variant="accent">
                {documents == null ? "…" : `${documents} chunks indexed`}
              </Badge>
            </div>
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <h2 className="mb-4 flex items-center gap-2 font-display text-lg font-medium">
            <BookMarked className="size-5 text-primary" aria-hidden />
            Study smarter
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {TIPS.map((tip) => (
              <GlowCard key={tip.title} className="p-5">
                <h3 className="font-display text-sm font-medium">{tip.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{tip.body}</p>
              </GlowCard>
            ))}
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
