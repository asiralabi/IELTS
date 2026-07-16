"use client";

import * as React from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpenCheck,
  ChevronDown,
  BookOpen,
  Headphones,
  PenLine,
  AlertTriangle,
  Search,
  X,
  CheckCircle2,
  Image as ImageIcon,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";
import { api, API_URL } from "@/lib/api";
import { useAuth } from "@/lib/store";
import type { CambridgeBook, CambridgeIndex } from "@/lib/types";
import { Topbar } from "@/components/shell/topbar";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  loadCambridgeProgress,
  isTestAttempted,
  type CambridgeProgress,
} from "@/lib/cambridge-progress";
import { cn } from "@/lib/utils";

type FilterMode = "all" | "visuals" | "audio";

interface TestSummary {
  reading: { passages: { n: number; has_visual: boolean }[] };
  listening: { parts: { n: number; has_visual: boolean; has_audio?: boolean }[] };
  writing: { tasks: { n: number; has_visual: boolean }[] };
}

/** Bookkeeping: cache per-test summaries so filters don't re-fetch. */
type SummaryCache = Record<string, TestSummary>;
const cacheKey = (bookId: string, test: number) => `${bookId}::${test}`;

async function fetchSummary(
  bookId: string,
  test: number,
  token: string | null
): Promise<TestSummary> {
  const res = await fetch(
    `${API_URL}/cambridge/${encodeURIComponent(bookId)}/${test}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  );
  if (!res.ok) throw new Error(`Summary ${res.status}`);
  return (await res.json()) as TestSummary;
}

export default function CambridgePage() {
  const [index, setIndex] = React.useState<CambridgeIndex | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");
  const [filter, setFilter] = React.useState<FilterMode>("all");
  const [progress, setProgress] = React.useState<CambridgeProgress>({});
  const [summaries, setSummaries] = React.useState<SummaryCache>({});
  const token = useAuth((s) => s.accessToken);

  React.useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      try {
        const data = await api.cambridgeIndex();
        if (!cancelled) setIndex(data);
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : "Could not load Cambridge index.";
        if (!cancelled) setError(msg);
        toast.error(msg);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    Promise.resolve().then(() => setProgress(loadCambridgeProgress()));
    const refresh = () => setProgress(loadCambridgeProgress());
    window.addEventListener("ai-ielts-cambridge-progress", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("ai-ielts-cambridge-progress", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const onToggleBook = React.useCallback(
    (bookId: string) => {
      setExpanded((cur) => (cur === bookId ? null : bookId));
      // Lazy-load summaries for filter/badges the first time a book is opened.
      const book = index?.books.find((b) => b.book_id === bookId);
      if (!book) return;
      Promise.resolve().then(async () => {
        const missing = book.tests.filter(
          (t) => !summaries[cacheKey(book.book_id, t.test_number)]
        );
        if (missing.length === 0) return;
        const results = await Promise.allSettled(
          missing.map((t) => fetchSummary(book.book_id, t.test_number, token))
        );
        setSummaries((prev) => {
          const next = { ...prev };
          missing.forEach((t, i) => {
            const r = results[i];
            if (r.status === "fulfilled") {
              next[cacheKey(book.book_id, t.test_number)] = r.value;
            }
          });
          return next;
        });
      });
    },
    [index, summaries, token]
  );

  const q = search.trim().toLowerCase();
  const visibleBooks = React.useMemo(() => {
    if (!index) return [];
    return index.books.filter((b) =>
      q ? b.book_title.toLowerCase().includes(q) : true
    );
  }, [index, q]);

  const filters: { id: FilterMode; label: string; icon: React.ReactNode }[] = [
    { id: "all", label: "All", icon: null },
    { id: "visuals", label: "Has visuals", icon: <ImageIcon className="size-3.5" aria-hidden /> },
    { id: "audio", label: "Has audio", icon: <Volume2 className="size-3.5" aria-hidden /> },
  ];

  return (
    <div className="mx-auto max-w-5xl">
      <Topbar title="Cambridge Tests" />

      <div className="glass-strong mb-6 flex items-start gap-4 rounded-[24px] p-5 shadow-soft">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-secondary/10 text-primary">
          <BookOpenCheck className="size-6" aria-hidden />
        </span>
        <div className="text-sm">
          <h2 className="mb-1 font-display text-lg font-semibold">
            Practise real Cambridge tests
          </h2>
          <p className="text-muted-foreground">
            The default practice pages use AI-generated questions so you can&rsquo;t
            memorise the answers. Use this page when you want to sit a real
            Cambridge IELTS test end-to-end. Answer keys are marked instantly.
          </p>
        </div>
      </div>

      {/* Search + filter toolbar */}
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="glass relative flex flex-1 items-center rounded-2xl px-3 shadow-soft">
          <Search className="size-4 text-muted-foreground" aria-hidden />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search Cambridge books…"
            aria-label="Search Cambridge books"
            className="border-0 bg-transparent shadow-none focus:shadow-none"
          />
          {search && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setSearch("")}
              className="mr-1 inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </div>
        <div
          role="group"
          aria-label="Filter tests"
          className="glass flex rounded-2xl p-1 shadow-soft"
        >
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              aria-pressed={filter === f.id}
              className={cn(
                "flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-medium transition-all",
                filter === f.id
                  ? "bg-gradient-to-r from-primary to-secondary text-white shadow-glow"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {f.icon}
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="glass flex items-center gap-3 rounded-2xl border border-danger/40 p-4 text-sm text-danger">
          <AlertTriangle className="size-4" aria-hidden />
          {error}
        </div>
      )}

      {!index && !error && (
        <div className="space-y-3" role="status" aria-live="polite">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-[24px]" />
          ))}
        </div>
      )}

      {index && (
        <div className="space-y-3">
          {visibleBooks.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {q
                ? `No books match “${search}”.`
                : "No Cambridge books ingested yet."}
            </p>
          )}
          {visibleBooks.map((book) => (
            <BookCard
              key={book.book_id}
              book={book}
              open={expanded === book.book_id}
              onToggle={() => onToggleBook(book.book_id)}
              filter={filter}
              progress={progress}
              summaries={summaries}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BookCard({
  book,
  open,
  onToggle,
  filter,
  progress,
  summaries,
}: {
  book: CambridgeBook;
  open: boolean;
  onToggle: () => void;
  filter: FilterMode;
  progress: CambridgeProgress;
  summaries: SummaryCache;
}) {
  const attemptedCount = book.tests.filter((t) =>
    isTestAttempted(progress, book.book_id, t.test_number)
  ).length;

  const filteredTests = React.useMemo(() => {
    if (filter === "all") return book.tests;
    return book.tests.filter((t) => {
      const s = summaries[cacheKey(book.book_id, t.test_number)];
      if (!s) return true; // don't hide before summary loads
      if (filter === "visuals") {
        return (
          s.reading.passages.some((p) => p.has_visual) ||
          s.listening.parts.some((p) => p.has_visual) ||
          s.writing.tasks.some((p) => p.has_visual)
        );
      }
      if (filter === "audio") {
        return s.listening.parts.some((p) => p.has_audio === true);
      }
      return true;
    });
  }, [book, filter, summaries]);

  return (
    <div className="glass overflow-hidden rounded-[24px] shadow-soft">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-muted/40"
      >
        <div className="flex flex-1 items-center gap-3">
          <div>
            <h3 className="font-display text-base font-semibold">{book.book_title}</h3>
            <p className="text-xs text-muted-foreground">
              {book.tests.length} test{book.tests.length === 1 ? "" : "s"} available
              {attemptedCount > 0 && ` · ${attemptedCount} attempted`}
            </p>
          </div>
          {attemptedCount > 0 && (
            <Badge variant="success" className="ml-1">
              <CheckCircle2 className="size-3" aria-hidden />
              {attemptedCount}
            </Badge>
          )}
        </div>
        <ChevronDown
          className={cn("size-5 shrink-0 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-border/60"
          >
            <ul className="divide-y divide-border/60">
              {filteredTests.map((t) => {
                const attempted = isTestAttempted(
                  progress,
                  book.book_id,
                  t.test_number
                );
                return (
                  <li
                    key={t.test_number}
                    className="flex flex-wrap items-center gap-3 px-5 py-3"
                  >
                    <Badge variant="outline" className="font-mono">
                      Test {t.test_number}
                    </Badge>
                    {attempted && (
                      <Badge variant="success">
                        <CheckCircle2 className="size-3" aria-hidden />
                        Completed
                      </Badge>
                    )}
                    <TestLaunchers
                      bookId={book.book_id}
                      testNumber={t.test_number}
                      readingPassages={t.reading_passages}
                      listeningParts={t.listening_parts}
                      writingTasks={t.writing_tasks}
                    />
                    {t.warnings.length > 0 && (
                      <span
                        className="ml-auto flex items-center gap-1 text-xs text-warning"
                        title={t.warnings.join("; ")}
                      >
                        <AlertTriangle className="size-3.5" aria-hidden />
                        {t.warnings.length} warning{t.warnings.length === 1 ? "" : "s"}
                      </span>
                    )}
                  </li>
                );
              })}
              {filteredTests.length === 0 && (
                <li className="px-5 py-4 text-xs text-muted-foreground">
                  No tests in this book match the current filter.
                </li>
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TestLaunchers({
  bookId,
  testNumber,
  readingPassages,
  listeningParts,
  writingTasks,
}: {
  bookId: string;
  testNumber: number;
  readingPassages: number;
  listeningParts: number;
  writingTasks: number;
}) {
  const params = (extra: string) =>
    `book=${encodeURIComponent(bookId)}&test=${testNumber}&${extra}`;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {Array.from({ length: readingPassages }).map((_, i) => (
        <LaunchLink
          key={`r-${i}`}
          href={`/reading?${params(`passage=${i + 1}`)}`}
          icon={<BookOpen className="size-3.5" aria-hidden />}
          label={`Reading ${i + 1}`}
        />
      ))}
      {Array.from({ length: listeningParts }).map((_, i) => (
        <LaunchLink
          key={`l-${i}`}
          href={`/listening?${params(`part=${i + 1}`)}`}
          icon={<Headphones className="size-3.5" aria-hidden />}
          label={`Listening ${i + 1}`}
        />
      ))}
      {Array.from({ length: writingTasks }).map((_, i) => (
        <LaunchLink
          key={`w-${i}`}
          href={`/writing?${params(`task=${i + 1}`)}`}
          icon={<PenLine className="size-3.5" aria-hidden />}
          label={`Writing ${i + 1}`}
        />
      ))}
    </div>
  );
}

function LaunchLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-1.5 rounded-xl bg-muted/70 px-2.5 py-1 text-xs font-medium text-foreground/80 transition-colors hover:bg-primary hover:text-primary-foreground"
    >
      {icon}
      {label}
    </Link>
  );
}
