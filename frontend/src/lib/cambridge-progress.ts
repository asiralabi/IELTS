"use client";

/**
 * Local progress tracking for Cambridge tests.
 * Persisted in localStorage under `ai-ielts-cambridge-progress`.
 *
 * Shape:
 *   { [bookId]: { [testNumber]: { reading?: {done, timestamp, n?}, listening?: ..., writing?: ... } } }
 */

export type CambridgeSkill = "reading" | "listening" | "writing";

export interface SectionProgress {
  done: true;
  timestamp: number;
  /** Passage / part / task number, when known. */
  n?: number;
}

export type TestProgress = Partial<Record<CambridgeSkill, SectionProgress>>;

export type CambridgeProgress = Record<string, Record<string, TestProgress>>;

const STORAGE_KEY = "ai-ielts-cambridge-progress";

export function loadCambridgeProgress(): CambridgeProgress {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object") return parsed as CambridgeProgress;
    return {};
  } catch {
    return {};
  }
}

function saveCambridgeProgress(value: CambridgeProgress): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    window.dispatchEvent(new CustomEvent("ai-ielts-cambridge-progress"));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

export function markCambridgeSectionDone(
  bookId: string,
  testNumber: number,
  skill: CambridgeSkill,
  n?: number
): void {
  const all = loadCambridgeProgress();
  const forBook = all[bookId] ?? {};
  const forTest = forBook[String(testNumber)] ?? {};
  forTest[skill] = { done: true, timestamp: Date.now(), n };
  forBook[String(testNumber)] = forTest;
  all[bookId] = forBook;
  saveCambridgeProgress(all);
}

export function isTestAttempted(
  progress: CambridgeProgress,
  bookId: string,
  testNumber: number
): boolean {
  const forTest = progress[bookId]?.[String(testNumber)];
  if (!forTest) return false;
  return Boolean(forTest.reading || forTest.listening || forTest.writing);
}
