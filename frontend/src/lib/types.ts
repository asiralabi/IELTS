export type Section = "reading" | "listening" | "writing" | "speaking";
export type TaskType = "task1" | "task2";
export type SpeakingPart = "part1" | "part2" | "part3";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  target_band: number | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

export interface ChatReply {
  session_id: number;
  reply: string;
}

export interface ChatSession {
  id: number;
  title: string;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface WritingResult {
  id: number;
  band_score: number | null;
  task_response?: number | null;
  coherence_cohesion?: number | null;
  lexical_resource?: number | null;
  grammatical_range_accuracy?: number | null;
  estimated_final_band?: number | null;
  feedback?: string;
  strengths?: string[];
  weaknesses?: string[];
  suggestions?: string[];
  corrections?: unknown;
  word_count: number;
  [key: string]: unknown;
}

export interface WritingHistoryItem {
  id: number;
  task_type: TaskType;
  band_score: number | null;
  word_count: number;
  created_at: string;
}

export interface SpeakingResult {
  id: number;
  transcript: string;
  band_score: number | null;
  fluency_coherence?: number | null;
  lexical_resource?: number | null;
  grammatical_range_accuracy?: number | null;
  pronunciation?: number | null;
  feedback?: string;
  [key: string]: unknown;
}

export interface SpeakingHistoryItem {
  id: number;
  part: string;
  band_score: number | null;
  created_at: string;
}

export interface VisualImage {
  kind: "image";
  url: string;
  alt: string;
  caption?: string;
}

export interface VisualChartSeries {
  name: string;
  data: Array<number | [string, number]>;
}

export interface VisualChart {
  kind: "chart";
  chart_type: "bar" | "line" | "pie" | "table";
  title: string;
  x_label?: string;
  y_label?: string;
  series: VisualChartSeries[];
}

export interface VisualMapFeature {
  label: string;
  x: number;
  y: number;
  shape?: "room" | "point";
  fixed?: boolean;
}

export interface VisualMapPath {
  points: Array<[number, number]>;
  label?: string;
}

export interface VisualMap {
  kind: "map";
  title: string;
  width?: number;
  height?: number;
  features: VisualMapFeature[];
  paths?: VisualMapPath[];
}

export type Visual = VisualImage | VisualChart | VisualMap;

export interface PracticeQuestion {
  id?: string;
  number?: number;
  type?: string;
  question?: string;
  text?: string;
  options?: string[] | Record<string, string>;
  visual?: Visual;
  visuals?: Visual[];
  [key: string]: unknown;
}

export interface PracticeSet {
  practice_id: number;
  title?: string;
  passage?: string;
  audio_script?: string;
  questions?: PracticeQuestion[];
  visual?: Visual;
  visuals?: Visual[];
  note?: string;
  source?: string;
  [key: string]: unknown;
}

export interface FullTestPart {
  part: number;
  title?: string;
  audio_script?: string;
  visual?: Visual;
  visuals?: Visual[];
  questions?: PracticeQuestion[];
}

export interface FullListeningTest {
  practice_id: number;
  title?: string;
  kind?: string;
  parts: FullTestPart[];
}

export interface FullTestPartResult {
  part: number;
  title?: string;
  score: number | null;
  total: number | null;
  results?: Array<{
    number?: number;
    correct?: boolean;
    student_answer?: string;
    correct_answer?: string;
    explanation?: string;
  }>;
}

export interface FullTestResult {
  score: number | null;
  total: number | null;
  band_estimate?: number | null;
  parts?: FullTestPartResult[];
  results?: Array<{
    number?: number;
    correct?: boolean;
    student_answer?: string;
    correct_answer?: string;
    explanation?: string;
  }>;
}

export interface CambridgeTestSummary {
  test_number: number;
  reading_passages: number;
  listening_parts: number;
  writing_tasks: number;
  warnings: string[];
}

export interface CambridgeBook {
  book_id: string;
  book_title: string;
  tests: CambridgeTestSummary[];
}

export interface CambridgeIndex {
  books: CambridgeBook[];
}

export interface CambridgeWritingTask {
  task: number;
  prompt: string;
  source: string;
  visual?: Visual;
  visuals?: Visual[];
}

export interface CheckResult {
  score: number | null;
  total: number | null;
  band_estimate?: number | null;
  results?: unknown;
  feedback?: string;
  [key: string]: unknown;
}

export interface MockExam {
  id: number;
  status?: "generated" | "scored";
  exam: Record<string, unknown>;
  results?: Record<string, unknown> | null;
  overall_band?: number | null;
  created_at?: string;
}

export interface MockExamResult {
  overall_band: number | null;
  results: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SkillProgress {
  latest_band: number | null;
  average_band: number | null;
}

export interface Progress {
  counts: {
    writing_submissions: number;
    speaking_submissions: number;
    reading_attempts: number;
    listening_attempts: number;
    mock_exams: number;
  };
  skills: {
    writing: SkillProgress;
    speaking: SkillProgress;
    reading: SkillProgress;
    listening: SkillProgress;
    mock_exam: SkillProgress;
  };
  target_band: number | null;
  timeline: Array<{
    type: "writing" | "speaking" | "reading_practice" | "listening_practice";
    id: number;
    band?: number | null;
    score?: number | null;
    total?: number | null;
    created_at: string;
  }>;
}

export interface GeneratedQuestion {
  id: number;
  section?: Section;
  question_type?: string;
  question?: string;
  [key: string]: unknown;
}

export interface StudyPlanDay {
  day: number;
  focus: string;
  tasks: string[];
}

export interface StudyPlan {
  summary: string;
  priorities: string[];
  study_plan: StudyPlanDay[];
  resources?: string[];
}

export type WeaknessCriterion =
  | "grammar"
  | "vocabulary"
  | "coherence"
  | "pronunciation"
  | "fluency"
  | "task_response"
  | "reading_comprehension"
  | "listening_accuracy";

export type WeaknessProfile = {
  [K in WeaknessCriterion]: boolean;
} & {
  details: { [K in WeaknessCriterion]: string };
};
