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
  // Echoed back only when the server did the transcribing. A full interview
  // sends its own transcripts up and still holds them.
  transcript?: string;
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

/** A floor plan given as a grid of cells rather than coordinates.
 *
 * Each cell is a single letter (a room the student must identify), the
 * reserved word "corridor", a room name to print, or "" for space outside
 * the building. Cells holding the same value side by side are one room, so
 * rooms share walls by construction and can never overlap.
 */
export interface VisualPlan {
  kind: "plan";
  title: string;
  grid: string[][];
  entrance?: { side: "top" | "bottom" | "left" | "right"; index?: number; label?: string };
}

/** A flow chart given as an ordered list of steps rather than boxes and arrows.
 *
 * The steps ARE the process: the renderer draws one box per step, top to
 * bottom, and an arrow between each pair, so a chart can never come back with
 * a box pointing at nothing. A step may carry `__<n>__` where question N's
 * answer goes, which renders as the numbered gap the exam prints.
 */
export interface VisualFlow {
  kind: "flow";
  title: string;
  steps: string[];
}

/** One part of a labelled diagram: a drawn shape, not a placed one.
 *
 * `form` names a shape the renderer knows how to draw; `id` is what a callout
 * points at. No part carries a coordinate — where it lands comes from the
 * layout and from its position in the list, which is why a generated diagram
 * can never overlap itself or fall off the canvas.
 */
export interface VisualDiagramPart {
  id: string;
  form: string;
  name?: string;
  /** Scene layout only: which cell of the coarse placement grid this part
   * occupies, and how many cells it spans. A real exam diagram places its
   * features in two dimensions; a single stacked column makes every subject
   * look the same. The grid is what keeps two parts from overlapping. */
  col?: number;
  row?: number;
  w?: number;
  h?: number;
  /** Apparatus only: hang this part off the side of `to` instead of stacking it. */
  attach?: "left" | "right" | "top" | "bottom";
  to?: string;
  /** Tree only: the node this one descends from. */
  parent?: string;
  /** Scene only: draw this part INSIDE the named part, which is what makes a
   * cross-section a cross-section — a yolk in a shell, frames in a hive, gas
   * in a cylinder. Its `col`/`row` then position it on a 3x3 sub-grid of the
   * container instead of on the main grid. */
  in?: string;
}

/** A drawn connection between two parts — the thing that makes an assembly
 * read as one machine rather than a row of separate objects. */
export interface VisualDiagramLink {
  from: string;
  to: string;
  style?: "pipe" | "arrow" | "line";
  label?: string;
}

/** A callout: the text the exam prints at the end of a leader line. */
export interface VisualDiagramLabel {
  at: string;
  text: string;
  side?: "left" | "right" | "top" | "bottom";
}

/** A labelled diagram — the figure IELTS prints for `diagram_label_completion`.
 *
 * The payload states what the parts ARE and what order they sit in; every
 * coordinate, every leader line and every label position is derived by the
 * renderer. `layout` picks which derivation runs: an apparatus stacks its
 * parts into an assembly, a section bands them top to bottom, a cycle sends
 * them clockwise, a tree hangs them off their parents, and a panel lays them
 * across a device face. Part names and callout text may carry `__<n>__`, which
 * renders as the numbered blank the student writes into.
 */
export interface VisualDiagram {
  kind: "diagram";
  title: string;
  layout: "scene" | "apparatus" | "layers" | "cycle" | "tree" | "panel";
  parts: VisualDiagramPart[];
  labels: VisualDiagramLabel[];
  links?: VisualDiagramLink[];
}

/** One headed group of a printed notes block. */
export interface VisualNotesSection {
  heading?: string;
  lines: string[];
}

/** The printed notes block and the printed summary — one shape, two typographies.
 *
 * Cambridge prints these constantly ("Complete the notes below", "Complete the
 * summary below") and the engine could not draw either: every note and summary
 * item had to carry its own context inline and the student never saw the block
 * the rubric named. A notes block is headed groups of short lines; a summary is
 * the same content set as flowing prose. Both gap identically, so both are this
 * one kind — a second schema would only be a second place for the numbering to
 * go wrong. A line may carry `__<n>__` where question N's answer goes.
 */
export interface VisualNotes {
  kind: "notes";
  style: "notes" | "summary";
  title: string;
  sections: VisualNotesSection[];
}

/** One of the small drawings a picture-choice question offers. */
export interface VisualPictureChoice {
  letter: string;
  layout: VisualDiagram["layout"];
  parts: VisualDiagramPart[];
  labels?: VisualDiagramLabel[];
}

/** "Which diagram shows ...? A, B or C" — two to four small line drawings.
 *
 * The diagram vocabulary again, at small size and in a row: a choice is a
 * diagram body without a kind of its own. Nothing here is interactive, because
 * the student answers with a letter using the option buttons the question
 * already carries.
 */
export interface VisualPicture {
  kind: "picture";
  title: string;
  choices: VisualPictureChoice[];
}

export type Visual =
  | VisualImage
  | VisualChart
  | VisualMap
  | VisualPlan
  | VisualFlow
  | VisualDiagram
  | VisualNotes
  | VisualPicture;

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

// Passage counts vary per generation, so a passage carries the question range
// it actually owns rather than the caller deriving it from a fixed size.
export interface FullTestPassage {
  passage_number: number;
  title?: string;
  passage?: string;
  visual?: Visual;
  visuals?: Visual[];
  questions?: PracticeQuestion[];
}

export interface FullReadingTest {
  practice_id: number;
  title?: string;
  kind?: string;
  passages: FullTestPassage[];
}

// Writing and Speaking papers carry no answer key, so unlike Reading and
// Listening they are never marked server-side against a stored copy — the
// tasks the student was shown come back with the answers.
export interface FullWritingTask {
  task: TaskType;
  label: string;
  minutes: number;
  min_words: number;
  question?: unknown;
  visual?: Visual;
  [key: string]: unknown;
}

export interface FullWritingTest {
  kind?: string;
  title?: string;
  tasks: FullWritingTask[];
}

export interface FullWritingTestResult {
  tasks: Partial<Record<TaskType, WritingResult>>;
  overall_band: number | null;
}

export interface FullSpeakingPart {
  part: SpeakingPart;
  label: string;
  minutes: number;
  question?: unknown;
  [key: string]: unknown;
}

export interface FullSpeakingTest {
  kind?: string;
  title?: string;
  parts: FullSpeakingPart[];
}

export interface FullSpeakingTestResult {
  parts: Partial<Record<SpeakingPart, SpeakingResult>>;
  overall_band: number | null;
}

export interface FullTestSectionResult {
  part?: number;
  passage_number?: number;
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
  parts?: FullTestSectionResult[];
  passages?: FullTestSectionResult[];
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

export interface FeedbackEntry {
  id: number;
  user_id: number | null;
  email: string;
  message: string;
  rating: number | null;
  page: string | null;
  created_at: string;
}
