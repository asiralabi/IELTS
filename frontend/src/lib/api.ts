"use client";

import { useAuth } from "./store";
import type {
  CambridgeIndex,
  CambridgeWritingTask,
  ChatMessage,
  ChatReply,
  ChatSession,
  CheckResult,
  FullListeningTest,
  FullTestResult,
  GeneratedQuestion,
  MockExam,
  MockExamResult,
  PracticeSet,
  Progress,
  Section,
  SpeakingHistoryItem,
  SpeakingResult,
  StudyPlan,
  TaskType,
  TokenPair,
  User,
  Visual,
  WeaknessProfile,
  WritingHistoryItem,
  WritingResult,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// Local qwen3:4b inference is slow — examiner calls can take several minutes,
// and mock-exam generation fans out into 7 LLM calls.
const LLM_TIMEOUT_MS = 30 * 60 * 1000;
const DEFAULT_TIMEOUT_MS = 30 * 1000;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function refreshTokens(): Promise<boolean> {
  const { refreshToken, setTokens, logout } = useAuth.getState();
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      logout();
      return false;
    }
    const data: TokenPair = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData | URLSearchParams;
  auth?: boolean;
  slow?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const { method = "GET", body, form, auth = true, slow = false } = opts;
  const headers: Record<string, string> = {};
  if (auth) {
    const token = useAuth.getState().accessToken;
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    slow ? LLM_TIMEOUT_MS : DEFAULT_TIMEOUT_MS
  );

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : form,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(408, "The AI is taking too long to respond. Please try again.");
    }
    throw new ApiError(0, "Cannot reach the server. Is the backend running?");
  }
  clearTimeout(timer);

  if (res.status === 401 && auth && !retried) {
    const refreshed = await refreshTokens();
    if (refreshed) return request<T>(path, opts, true);
    useAuth.getState().logout();
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (data.detail) detail = JSON.stringify(data.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// Authenticated binary GET (used for the neural Listening audio). First-time
// synthesis on the backend can take several seconds, so it gets the long timeout.
async function requestBlob(path: string, retried = false): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = useAuth.getState().accessToken;
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LLM_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { headers, signal: controller.signal });
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(408, "The audio is taking too long to synthesize. Please try again.");
    }
    throw new ApiError(0, "Cannot reach the server. Is the backend running?");
  }
  clearTimeout(timer);

  if (res.status === 401 && !retried) {
    const refreshed = await refreshTokens();
    if (refreshed) return requestBlob(path, true);
    useAuth.getState().logout();
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

export const api = {
  // --- auth ---
  register: (payload: {
    email: string;
    password: string;
    full_name?: string;
    target_band?: number;
  }) => request<User>("/auth/register", { method: "POST", body: payload, auth: false }),

  login: (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    return request<TokenPair>("/auth/login", { method: "POST", form, auth: false });
  },

  me: () => request<User>("/auth/me"),

  // --- chat ---
  chat: (message: string, session_id?: number | null) =>
    request<ChatReply>("/chat", {
      method: "POST",
      body: { message, session_id: session_id ?? null },
      slow: true,
    }),
  chatSessions: () => request<ChatSession[]>("/chat/sessions"),
  chatHistory: (sessionId: number) =>
    request<ChatMessage[]>(`/chat/sessions/${sessionId}`),

  // --- questions ---
  generateQuestion: (payload: {
    section: Section;
    question_type?: string;
    difficulty?: string;
    topic?: string;
  }) =>
    request<GeneratedQuestion>("/questions/generate", {
      method: "POST",
      body: payload,
      slow: true,
    }),

  // --- writing ---
  submitWriting: (payload: {
    task_type: TaskType;
    prompt: string;
    essay: string;
    visual?: Visual | null;
  }) =>
    request<WritingResult>("/writing/submit", { method: "POST", body: payload, slow: true }),
  writingHistory: () => request<WritingHistoryItem[]>("/writing/history"),

  // --- speaking ---
  submitSpeaking: (payload: { part: string; question: string; transcript: string }) => {
    const form = new FormData();
    form.set("part", payload.part);
    form.set("question", payload.question);
    form.set("transcript", payload.transcript);
    return request<SpeakingResult>("/speaking/submit", { method: "POST", form, slow: true });
  },
  speakingHistory: () => request<SpeakingHistoryItem[]>("/speaking/history"),

  // --- reading / listening ---
  readingPractice: (payload: {
    question_types?: string[];
    difficulty?: string;
    topic?: string;
  } = {}) =>
    request<PracticeSet>("/reading/practice", { method: "POST", body: payload, slow: true }),
  readingCheck: (practice_id: number, answers: Record<string, string>) =>
    request<CheckResult>("/reading/check", {
      method: "POST",
      body: { practice_id, answers },
      slow: true,
    }),
  listeningPractice: (payload: {
    question_types?: string[];
    difficulty?: string;
    topic?: string;
  } = {}) =>
    request<PracticeSet>("/listening/practice", { method: "POST", body: payload, slow: true }),
  listeningCheck: (practice_id: number, answers: Record<string, string>) =>
    request<CheckResult>("/listening/check", {
      method: "POST",
      body: { practice_id, answers },
      slow: true,
    }),
  listeningFullTest: (difficulty?: string) =>
    request<FullListeningTest>("/listening/full-test", {
      method: "POST",
      body: { difficulty: difficulty ?? null },
      slow: true,
    }),
  listeningFullTestCheck: (practice_id: number, answers: Record<string, string>) =>
    request<FullTestResult>("/listening/full-test/check", {
      method: "POST",
      body: { practice_id, answers },
      slow: true,
    }),
  listeningAudio: (practice_id: number, part?: number) =>
    requestBlob(
      `/listening/audio/${practice_id}${part != null ? `?part=${part}` : ""}`
    ),

  // --- mock exam ---
  generateMockExam: () =>
    request<MockExam>("/mock-exam/generate", { method: "POST", slow: true }),
  submitMockExam: (
    examId: number,
    payload: {
      listening_answers?: Record<string, string>;
      reading_answers?: Record<string, string>;
      essays?: Record<string, string>;
      speaking_transcripts?: Record<string, string>;
    }
  ) =>
    request<MockExamResult>(`/mock-exam/${examId}/submit`, {
      method: "POST",
      body: payload,
      slow: true,
    }),
  getMockExam: (examId: number) => request<MockExam>(`/mock-exam/${examId}`),

  // --- progress ---
  progress: () => request<Progress>("/progress"),
  weaknesses: () => request<WeaknessProfile>("/progress/weaknesses", { slow: true }),
  studyPlan: () => request<StudyPlan>("/progress/study-plan", { slow: true }),

  // --- cambridge (opt-in real-test flow) ---
  cambridgeIndex: () => request<CambridgeIndex>("/cambridge/index"),
  cambridgeReading: (book_id: string, test_number: number, passage: number) =>
    request<PracticeSet>(
      `/cambridge/${encodeURIComponent(book_id)}/${test_number}/reading?passage=${passage}`
    ),
  cambridgeListening: (book_id: string, test_number: number, part: number) =>
    request<PracticeSet>(
      `/cambridge/${encodeURIComponent(book_id)}/${test_number}/listening?part=${part}`
    ),
  cambridgeWriting: (book_id: string, test_number: number, task: number) =>
    request<CambridgeWritingTask>(
      `/cambridge/${encodeURIComponent(book_id)}/${test_number}/writing?task=${task}`
    ),

  // --- knowledge ---
  knowledgeStatus: () => request<{ documents: number }>("/knowledge/status"),
  ingestPdf: (file: File) => {
    const form = new FormData();
    form.set("file", file);
    return request<{ chunks_indexed: number }>("/knowledge/ingest", {
      method: "POST",
      form,
      slow: true,
    });
  },
};
