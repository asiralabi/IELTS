"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { FileUp, Database, BookMarked } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
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
  const [uploading, setUploading] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    api.knowledgeStatus().then((s) => setDocuments(s.documents)).catch(() => {});
  }, []);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const res = await api.ingestPdf(file);
      toast.success(`Indexed ${res.chunks_indexed} chunks from ${file.name}`);
      const s = await api.knowledgeStatus();
      setDocuments(s.documents);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

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
                  <h2 className="font-display font-semibold">AI Knowledge Base</h2>
                  <p className="text-sm text-muted-foreground">
                    Upload IELTS books or guides (PDF) — the AI examiner cites them
                    when marking.
                  </p>
                </div>
              </div>
              <Badge variant="accent">
                {documents == null ? "…" : `${documents} chunks indexed`}
              </Badge>
            </div>
            <div className="mt-5">
              <input
                ref={fileRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload(f);
                }}
              />
              <Button
                variant="secondary"
                loading={uploading}
                onClick={() => fileRef.current?.click()}
              >
                <FileUp className="size-4" aria-hidden />
                Upload a PDF
              </Button>
            </div>
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <h2 className="mb-4 flex items-center gap-2 font-display text-lg font-semibold">
            <BookMarked className="size-5 text-primary" aria-hidden />
            Study smarter
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {TIPS.map((tip) => (
              <GlowCard key={tip.title} className="p-5">
                <h3 className="font-display text-sm font-semibold">{tip.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{tip.body}</p>
              </GlowCard>
            ))}
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
