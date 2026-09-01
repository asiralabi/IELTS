"use client";

import { Fragment } from "react";
import type { ReactNode } from "react";
import type {
  VisualDiagram,
  VisualDiagramLabel,
  VisualDiagramLink,
  VisualDiagramPart,
  VisualPicture,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// The labelled diagram — the figure the exam prints for diagram labelling, and
// the one the engine could not draw at all until now. `prompts.py` used to
// answer `diagram_label_completion` with the floor plan's grid, so a
// "Cross-section of a Sewing Machine" rendered as seven text boxes in a Tetris
// shape. A grid is the right figure for a building and the wrong one for a
// machine.
//
// The payload states only what the parts ARE and what ORDER they sit in.
// Every coordinate below is derived from that, which is the same bargain the
// plan strikes with its grid and the flow chart with its step list: nothing
// the generator returns can come out overlapping, off-canvas, or pointing at
// a part that is not drawn.
//
// Drawn as exam line art: thin strokes in the reading colour, opaque paper
// fills so a leader line never shows through a shape, dotted leaders, and
// numbered blanks printed the way Cambridge prints them ("23 ..........").
// ---------------------------------------------------------------------------

const GAP_RE = /__(\d+)__/g;

/** Canvas. Wide enough for a drawing between two columns of callouts. */
const W = 820;
const PAD = 16;
/** Callout gutters.
 *
 * Wide enough for a SENTENCE, because that is what the exam prints in one.
 * Cambridge 9 Test 3 hangs "Whole tower can be raised for 23 .......... and
 * the extraction of seaweed from the blades" off the top-left of the undersea
 * turbine, and Cambridge 11 Test 1 prints seven such callouts around the
 * Falkirk Wheel. A gutter sized for "Thread guide" turned every one of those
 * into a line that ran off the page, so the model was told to write six-word
 * labels instead and the figure lost the passage context that makes it a
 * reading question rather than a picture.
 */
const GUTTER = 214;
/** Room a wrapped callout line takes, and the widest line one may print. */
const CALLOUT_LINE_H = 16;
const CALLOUT_W = GUTTER - 30;
const DRAW_L = PAD + GUTTER;
const DRAW_R = W - PAD - GUTTER;
const DRAW_W = DRAW_R - DRAW_L;
const CX = (DRAW_L + DRAW_R) / 2;

/** Narrowest the figure is allowed to render before it scrolls instead. */
const MIN_W = 620;

const TITLE_H = 34;
/** Vertical room a callout needs before it collides with the one above it. */
const LABEL_GAP = 30;

/** What a layout hands back. `x0`/`x1` are the horizontal bounds it actually
 * drew within — the bare (small) canvas crops to them, and a layout that does
 * not say gets the assembly gutters. */
type Drawn = {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
  x0?: number;
  x1?: number;
};

type Anchor = {
  id: string;
  x: number;
  y: number;
  left: number;
  right: number;
  /** A side something else is already attached on. A callout sent here would
   * have to end past the attachment, next to the attachment's OWN callout, and
   * the student cannot tell which of the two lines means which part. */
  avoid?: "left" | "right";
};

export function DiagramBlock({
  visual,
  className,
  bare = false,
}: {
  visual: VisualDiagram;
  className?: string;
  /** Drop the card, the title and the legibility floor. Used when several
   * small drawings sit side by side as the choices of one question, where the
   * 620px floor would push each of them off the row. */
  bare?: boolean;
}) {
  const layout = visual.layout ?? "apparatus";
  const drawn =
    layout === "scene"
      ? scene(visual)
      : layout === "layers"
      ? layers(visual)
      : layout === "cycle"
        ? cycle(visual)
        : layout === "tree"
          ? tree(visual)
          : layout === "panel"
            ? panel(visual)
            : apparatus(visual);

  const callouts = placeLabels(visual.labels ?? [], drawn.anchors, drawn.height);
  const height = Math.max(drawn.height, callouts.height) + PAD;

  // A bare canvas is rendered a quarter the width of a full one, so its text
  // would land at ~4px — the same illegibility MIN_W guards against, which
  // `bare` deliberately drops. Cropping to the drawing instead doubles
  // everything without touching a layout constant.
  //
  // The bounds come from the LAYOUT, never from a constant: a scene draws to
  // a different x-range than an assembly, and cropping it to the assembly's
  // gutters chopped the nozzle in half and ran the tank off the right edge.
  const cropped = bare && (visual.labels ?? []).length === 0;
  const x0 = drawn.x0 ?? DRAW_L;
  const x1 = drawn.x1 ?? DRAW_R;
  const canvas = (
    <svg
      viewBox={cropped ? `${x0} 0 ${x1 - x0} ${height}` : `0 0 ${W} ${height}`}
      style={bare ? undefined : { minWidth: MIN_W }}
      className="mx-auto block w-full max-w-[720px] text-foreground"
      role="img"
      aria-label={visual.title || "Labelled diagram"}
    >
      <Defs />
      {drawn.body}
      {callouts.body}
    </svg>
  );
  if (bare) return canvas;

  return (
    <figure
      className={cn(
        "rounded-[20px] border border-border/70 bg-card px-4 py-3 shadow-soft",
        className
      )}
      aria-label={`Diagram: ${visual.title}`}
    >
      {visual.title && (
        <figcaption className="mb-1 text-center text-sm font-semibold tracking-tight text-foreground">
          {visual.title}
        </figcaption>
      )}
      {/* A diagram scales with its column, and a label scales with it: at the
          300px a narrow practice column can give, 13px figure text renders at
          6px and fringes into colour. Below the floor the figure scrolls
          sideways instead of shrinking further — the same bargain wide tables
          strike. */}
      <div className="overflow-x-auto">{canvas}</div>
    </figure>
  );
}

/** Shared pattern and marker definitions. Duplicated ids in one document are
 * harmless — every reference resolves to the first — but they are emitted once
 * per figure so a bare canvas rendered on its own still has them. */
function Defs() {
  return (
    <>
      <defs>
          {/* Ground and rock hatching, the exam's one texture. */}
          <pattern
            id="dg-hatch"
            width="8"
            height="8"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="currentColor"
              strokeWidth="1"
              opacity="0.45"
            />
          </pattern>
        <marker
          id="dg-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
        </marker>
      </defs>
    </>
  );
}

// ---------------------------------------------------------------------------
// Picture choice — "Which diagram shows ...? A, B or C"
//
// Two to four small line drawings in a row, lettered underneath. The student
// answers with the letter, using the option buttons the question already
// carries, so nothing here is interactive: these are the pictures, not the
// input.

export function PictureBlock({
  visual,
  className,
}: {
  visual: VisualPicture;
  className?: string;
}) {
  const choices = visual.choices ?? [];
  return (
    <figure
      className={cn(
        "rounded-[20px] border border-border/70 bg-card px-4 py-3 shadow-soft",
        className
      )}
      aria-label={`Pictures: ${visual.title}`}
    >
      {visual.title && (
        <figcaption className="mb-2 text-center text-sm font-semibold tracking-tight text-foreground">
          {visual.title}
        </figcaption>
      )}
      <div className="overflow-x-auto">
        <div
          className="grid gap-3"
          style={{
            gridTemplateColumns: `repeat(${Math.max(choices.length, 1)}, minmax(150px, 1fr))`,
            minWidth: Math.max(choices.length, 1) * 160,
          }}
        >
          {choices.map((choice) => (
            <div
              key={choice.letter}
              className="rounded-xl border border-border/60 px-2 py-2"
            >
              <DiagramBlock
                bare
                visual={{
                  kind: "diagram",
                  title: "",
                  layout: choice.layout,
                  parts: choice.parts,
                  labels: choice.labels ?? [],
                }}
              />
              <p className="mt-1 text-center text-sm font-semibold text-foreground">
                {choice.letter}
              </p>
            </div>
          ))}
        </div>
      </div>
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Shared drawing helpers
// ---------------------------------------------------------------------------

/** Every shape is stroked in the reading colour and filled with paper, so a
 * leader line passing behind it is hidden rather than drawn through it. */
const SHAPE = {
  fill: "var(--card, #fff)",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinejoin: "round" as const,
};

/** One line of figure text.
 *
 * Painted stroke-first, so the paper colour lays a halo behind the glyphs: a
 * label that lands on a leader line or on hatching stays readable without the
 * layout having to route around it.
 */
function text(
  content: ReactNode,
  x: number,
  y: number,
  opts: { size?: number; anchor?: "start" | "middle" | "end"; bold?: boolean } = {}
) {
  return (
    <text
      x={x}
      y={y}
      textAnchor={opts.anchor ?? "middle"}
      fontSize={opts.size ?? 13}
      fontWeight={opts.bold ? 600 : 400}
      fill="currentColor"
      stroke="var(--card, #fff)"
      // 2px, not 3: a heavier halo eats so far into an 11px glyph that
      // subpixel antialiasing fringes the strokes orange, and the figure's
      // in-shape names came out a different colour from its callouts.
      strokeWidth={2}
      strokeLinejoin="round"
      paintOrder="stroke"
      dominantBaseline="middle"
    >
      {content}
    </text>
  );
}

/** Split a label into its printed words and its numbered blanks.
 *
 * The exam prints a blank as its question number followed by a dotted rule, so
 * `__23__` becomes a bold 23 and a run of dots — the same thing the student
 * sees on paper, and the reason a diagram gap is recognisable as a gap without
 * any colour.
 */
function gapText(raw: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(GAP_RE.source, "g");
  while ((m = re.exec(raw))) {
    if (m.index > last) out.push(raw.slice(last, m.index));
    // `data-gap` is what lets the student's current question light its own
    // blank — see the `[data-active-gap]` rules in globals.css. A figure is
    // printed once and asked about five times, so without it "Label 3" means
    // hunting for a small 3 among four others while a clock runs.
    out.push(
      <Fragment key={`${m.index}-${m[1]}`}>
        <tspan className="gap-mark" data-gap={m[1]} fontWeight={700}>
          {m[1]}
        </tspan>
        <tspan letterSpacing="1.5" opacity="0.7">
          {" "}
          ..........
        </tspan>
      </Fragment>
    );
    last = m.index + m[0].length;
  }
  if (last < raw.length) out.push(raw.slice(last));
  return out.length ? out : [raw];
}

/** Round a computed coordinate to two decimals.
 *
 * Trig is implementation-defined: Math.sin gives Node and Chromium answers
 * that differ in the last bits, so a raw `A194.00000000000003,...` arc path
 * rendered on the server does not match the one React builds in the browser
 * and the whole figure fails hydration. Rounding also shrinks the markup.
 */
function r2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Does this text hold a blank? A gap label is wider than a plain one. */
function hasGap(raw: string): boolean {
  return new RegExp(GAP_RE.source).test(raw);
}

/** Greedy wrap on a character budget derived from the box width.
 *
 * SVG will not wrap text, and a part name is short enough that measuring it
 * properly is not worth a canvas round-trip: at 13px the average glyph is
 * ~6.4px wide, which is close enough that a two-word name never overflows.
 */
function wrap(raw: string, width: number, size = 13): string[] {
  const budget = Math.max(4, Math.floor(width / (size * 0.52)));
  const words = raw.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > budget && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [raw];
}

/** Wrap a callout, counting a blank at the width it actually PRINTS.
 *
 * `__23__` is six characters in the payload and about thirteen on the page —
 * a bold number, a space and a ten-dot rule. Measuring the payload instead of
 * the print is what let a callout ending in a gap overrun its gutter even
 * after the gutter was widened.
 */
function wrapCallout(raw: string, width: number, size = 13): string[] {
  const budget = Math.max(6, Math.floor(width / (size * 0.52)));
  // Tokenise the PAYLOAD so a blank stays one token: wrapping the printed form
  // could break "23 .........." across two lines, leaving a bare number on one
  // and a rule of dots on the next.
  const tokens = raw.split(/\s+/).filter(Boolean);
  const printedLen = (t: string) =>
    t.replace(/__(\d+)__/g, (_m, n: string) => `${n} ..........`).length;

  const lines: string[] = [];
  let line = "";
  let width_ = 0;
  for (const token of tokens) {
    const add = printedLen(token);
    if (line && width_ + 1 + add > budget) {
      lines.push(line);
      line = token;
      width_ = add;
    } else {
      line = line ? `${line} ${token}` : token;
      width_ = line ? width_ + (width_ ? 1 : 0) + add : add;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [raw];
}

/** The smallest a printed name may shrink before it is dropped instead.
 *
 * 🔬 A name was drawn at its centre whatever the shape measured, so a part
 * 30 wide and 7 high still printed "horizontal tunnels" across everything
 * around it. Six of those made a termite mound unreadable. The exam prints no
 * name it cannot fit, and an orientation name is the cheapest thing on the
 * figure to lose — the same trade `blank_self_answering_labels` makes when it
 * rubs one out: losing it costs the student a hint, keeping it costs them the
 * drawing. */
const NAME_MIN_SIZE = 9;

function inShape(
  raw: string,
  x: number,
  y: number,
  width: number,
  size = 13,
  /** The height the name has to fit inside. Unbounded when not given, which
   * is the layouts that print into a band sized by its own contents. */
  height = Infinity
) {
  // `wrap` keeps a word that is longer than the whole budget on a line of its
  // own rather than breaking it, so "Grinder" in a 55-wide box comes back as
  // one line that prints wider than the shape it is in. Measuring the widest
  // line is what catches that; measuring the count of lines never could.
  const widest = (ls: string[], at: number) =>
    Math.max(...ls.map((l) => l.length * at * 0.55));
  const fits = (ls: string[], at: number) =>
    ls.length * (at + 3) <= height - 4 && widest(ls, at) <= width - 8;

  let chosen = size;
  let lines = wrap(raw, width - 12, chosen);
  // Shrink before dropping: one step down usually fits a two-word name that
  // overran by a few pixels.
  while (!fits(lines, chosen) && chosen > NAME_MIN_SIZE) {
    chosen -= 1;
    lines = wrap(raw, width - 12, chosen);
  }
  if (!fits(lines, chosen)) return null;
  const top = y - ((lines.length - 1) * (chosen + 3)) / 2;
  return lines.map((line, i) => (
    <Fragment key={i}>
      {text(gapText(line), x, top + i * (chosen + 3), { size: chosen })}
    </Fragment>
  ));
}

// ---------------------------------------------------------------------------
// Callout placement — shared by every layout.
//
// A label names the part it points at; which SIDE it lands on and how far down
// the margin it sits are worked out here. Labels are pushed apart until none
// overlaps its neighbour, so a figure with six callouts on one side stays
// readable instead of printing them on top of each other.
// ---------------------------------------------------------------------------

function placeLabels(
  labels: VisualDiagramLabel[],
  anchors: Anchor[],
  drawnHeight: number
): { body: ReactNode; height: number } {
  const byId = new Map(anchors.map((a) => [a.id, a]));
  const sides: Record<"left" | "right", { label: VisualDiagramLabel; a: Anchor }[]> =
    { left: [], right: [] };

  let flip = 0;
  for (const label of labels) {
    const a = byId.get(label.at);
    if (!a) continue;
    // An explicit side is honoured; otherwise labels alternate, which keeps a
    // drawing with many parts from growing one very long column.
    let side: "left" | "right";
    // Which half of the canvas the part sits in decides, whenever it sits
    // clearly in one. A leader that crosses the whole drawing to reach a
    // gutter on the far side reads as part of the machine.
    const offset = a.x - W / 2;
    if (Math.abs(offset) > 60) side = offset < 0 ? "left" : "right";
    else if (label.side === "left" || label.side === "right") side = label.side;
    else side = flip++ % 2 === 0 ? "right" : "left";
    // The renderer has the last word on geometry, the way it does everywhere
    // else in this file: a requested side that is blocked is swapped, not
    // honoured into an unreadable figure.
    if (a.avoid === side) side = side === "left" ? "right" : "left";
    sides[side].push({ label, a });
  }

  const body: ReactNode[] = [];
  let lowest = drawnHeight;

  for (const side of ["left", "right"] as const) {
    const items = [...sides[side]]
      .sort((p, q) => p.a.y - q.a.y)
      .map((item) => ({ ...item, lines: wrapCallout(item.label.text, CALLOUT_W) }));
    // Spread: start at each callout's own height, then walk down enforcing
    // clearance for the WHOLE wrapped block rather than a single line — a
    // three-line callout that only reserved one line's height printed its
    // second and third lines through the callout below it.
    const ys: number[] = [];
    let prev = -Infinity;
    for (const item of items) {
      const half = ((item.lines.length - 1) * CALLOUT_LINE_H) / 2;
      const y = Math.max(item.a.y, prev + half + LABEL_GAP, TITLE_H + half);
      ys.push(y);
      prev = y + half;
    }
    items.forEach((item, i) => {
      const y = ys[i];
      const half = ((item.lines.length - 1) * CALLOUT_LINE_H) / 2;
      lowest = Math.max(lowest, y + half + 14);
      // Cambridge LEFT-ALIGNS both columns of callouts — the left column too,
      // where the ragged edge falls on the drawing side. Right-aligning the
      // left column (which is what an `end` anchor does) staircases the text
      // away from the leader and reads as a caption, not a callout.
      const tx = side === "left" ? PAD : W - PAD - GUTTER + 26;
      // The leader leaves from just past the longest line, not from a fixed
      // gutter edge, so a short callout is not left trailing a metre of dots.
      const blockW = Math.max(
        ...item.lines.map(
          (l) =>
            l.replace(GAP_RE, (_m, n: string) => `${n} ..........`).length * 6.8
        )
      );
      const leaderX =
        side === "left"
          ? Math.min(PAD + blockW + 10, DRAW_L - 6)
          : W - PAD - GUTTER + 26 - 10;
      const edge = side === "left" ? item.a.left : item.a.right;
      body.push(
        <Fragment key={`${side}-${i}-${item.label.at}`}>
          {/* Leader: out of the callout horizontally, then to the part's edge.
              Two segments rather than one diagonal, because a diagonal across
              a drawing reads as part of the machine. It leaves the block at
              its vertical middle, which is where the exam draws it from. */}
          <polyline
            points={`${leaderX},${y} ${side === "left" ? leaderX + 14 : leaderX - 14},${y} ${edge},${item.a.y}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.75"
          />
          <circle cx={edge} cy={item.a.y} r="2.4" fill="currentColor" />
          {item.lines.map((line, j) => (
            <Fragment key={`t-${j}`}>
              {text(gapText(line), tx, y - half + j * CALLOUT_LINE_H, {
                anchor: "start",
                size: 13,
              })}
            </Fragment>
          ))}
        </Fragment>
      );
    });
  }

  return { body: <>{body}</>, height: lowest + PAD };
}

// ---------------------------------------------------------------------------
// Layout: apparatus — a cross-section or mechanism.
//
// The commonest reading diagram by a distance ("An Undersea Turbine", "How a
// boat is lifted on the Falkirk Wheel", "How the 1670 lever-based device
// worked"). Parts are listed top to bottom and stacked into one assembly;
// anything with `attach` hangs off the side of the part it names, joined by a
// short pipe, so an assembly reads as one machine.
// ---------------------------------------------------------------------------

/** Natural height and width of each drawable form, before the stack is scaled. */
const FORM_BOX: Record<string, { h: number; w: number }> = {
  ground: { h: 26, w: DRAW_W },
  platform: { h: 20, w: 230 },
  pipe: { h: 40, w: 30 },
  disc: { h: 86, w: 86 },
  rotor: { h: 108, w: 150 },
  dome: { h: 52, w: 130 },
  funnel: { h: 72, w: 150 },
  coil: { h: 74, w: 80 },
  valve: { h: 44, w: 58 },
  tank: { h: 104, w: 132 },
  chamber: { h: 96, w: 158 },
  column: { h: 130, w: 62 },
  liquid: { h: 70, w: 138 },
  box: { h: 80, w: 128 },
  // The forms the real subject list needs. Measured from what the exam
  // actually prints: a beehive, a soda can, a fire extinguisher, a Ferris
  // wheel, a zip fastener, a solar heating system, an undersea turbine, soil
  // layers, an egg cross-section, a Mars probe. Every one of those is a
  // RECOGNISABLE object, and a vocabulary of vessels draws them all alike.
  oval: { h: 104, w: 132 },
  canister: { h: 128, w: 84 },
  nozzle: { h: 44, w: 70 },
  hose: { h: 70, w: 90 },
  handle: { h: 40, w: 90 },
  wheel: { h: 130, w: 130 },
  stand: { h: 74, w: 130 },
  panel: { h: 74, w: 150 },
  stack: { h: 118, w: 128 },
  arm: { h: 86, w: 120 },
  antenna: { h: 92, w: 74 },
  mound: { h: 46, w: 130 },
  cone: { h: 90, w: 120 },
  cap: { h: 30, w: 96 },
  lever: { h: 70, w: 120 },
  spring: { h: 84, w: 60 },
  blade: { h: 96, w: 54 },
  frame: { h: 96, w: 132 },
  gauge: { h: 72, w: 78 },
};

function formBox(form: string) {
  return FORM_BOX[form] ?? FORM_BOX.box;
}

/** How wide the DRAWN ink is, as a fraction of the part's box.
 *
 * A leader has to end on the shape, not on the empty corner of the box that
 * holds it: a rotor's blades sweep a circle inside a wide box, and a callout
 * pointing at the box edge appears to point at nothing. Anything not listed
 * fills its box.
 */
const INK: Record<string, number> = {
  gauge: 1,
  rotor: 0.72,
  disc: 1,
  valve: 1,
  coil: 1,
  wheel: 1,
  oval: 1,
  cone: 0.9,
};

function inkEdges(form: string, b: Box): { left: number; right: number } {
  const f = INK[form] ?? 1;
  const half = (b.w * f) / 2;
  const cx = b.x + b.w / 2;
  return { left: cx - half, right: cx + half };
}

// ---------------------------------------------------------------------------
// Layout: scene — an object placed in TWO dimensions.
//
// The layout `apparatus` gets wrong. Measured against the official Cambridge
// sample (IELTS Academic Reading Task Type 10, "Dung Beetle Types"): the real
// figure places each feature at its own spot in 2D — blank 6 upper left, 8
// upper right, 7 lower middle — and the numbered blanks sit AT the feature
// rather than in a column down the margin.
//
// `apparatus` stacks everything in one centred column, so a soda can, a Ferris
// wheel and a zip fastener all come out as the same tower of boxes. That is
// the defect, and this is the fix: the model says which CELL of a coarse grid
// a part occupies, and the pixel geometry is derived from that. The grid is
// what keeps the old bargain intact — two parts cannot overlap, because two
// parts cannot hold the same cell.

const SCENE_MAX_COLS = 6;
const SCENE_MAX_ROWS = 5;

function sceneCell(part: VisualDiagramPart) {
  const col = Math.max(0, Math.min(SCENE_MAX_COLS - 1, Math.round(part.col ?? 0)));
  const row = Math.max(0, Math.min(SCENE_MAX_ROWS - 1, Math.round(part.row ?? 0)));
  const w = Math.max(1, Math.min(SCENE_MAX_COLS - col, Math.round(part.w ?? 1)));
  const h = Math.max(1, Math.min(SCENE_MAX_ROWS - row, Math.round(part.h ?? 1)));
  return { col, row, w, h };
}

// Forms that genuinely occupy their whole cell. Everything else is drawn at
// its natural proportions and centred, because a `pipe` stretched to fill a
// cell is a big empty rectangle and a `disc` stretched to fill one is a
// circle the size of the tank beside it.
// Shells whose usable interior is the inscribed rectangle, not the box.
const ROUND_FORMS = new Set(["oval", "disc", "dome", "wheel", "cone"]);

const FILLS_CELL = new Set([
  "pipe",
  "hose",
  "ground",
  "liquid",
  "panel",
  "frame",
  "stack",
  "box",
  "platform",
  "chamber",
  "column",
]);

function fitBox(
  form: string,
  cell: Box,
  under: boolean,
  over: boolean,
  holds = false
): Box {
  // 🔬 A shell that holds things takes the whole cell it was given, whatever
  // its natural proportions. A termite mound came back as an `outer` dome
  // holding five parts: the dome drew at its natural 130x52 inside a 240x270
  // cell, and the five contents were then laid out on a 3x3 sub-grid of THAT
  // — a sub-cell 30 wide and 7 high. All five names printed at their centres,
  // on top of one another, and the figure was an illegible blob. The room a
  // container needs is set by what is in it, not by what shape it is.
  if (FILLS_CELL.has(form) || holds) return cell;
  const nat = formBox(form);
  // Never enlarged past its natural size: scaled up to fill, a pump disc came
  // out as wide as the tank beside it.
  const scale = Math.min(cell.w / nat.w, cell.h / nat.h, 1);
  const w = nat.w * scale;
  const h = nat.h * scale;
  // Pulled towards whatever it touches, so an assembly holds together: sat on
  // the part below, hung under the part above, stretched when there is one of
  // each. Centred in its own cell, a handle floated clear of the body it is
  // bolted to and a tall canister left a gap under the handle above it.
  let y = cell.y + (cell.h - h) / 2;
  let height = h;
  if (under && over) {
    y = cell.y;
    height = cell.h;
  } else if (under) {
    y = cell.y + cell.h - h;
  } else if (over) {
    y = cell.y;
  }
  return { x: cell.x + (cell.w - w) / 2, y, w, h: height };
}

function scene(visual: VisualDiagram): Drawn {
  const all = visual.parts ?? [];
  // A part drawn INSIDE another is positioned within its container, not on the
  // main grid, so it takes no cell of its own and never widens the figure.
  // This is what makes a cross-section a cross-section: a yolk in a shell,
  // frames in a hive, gas in a cylinder. Without it every "cross-section" was
  // a row of separate objects standing next to each other.
  const byIdAll = new Map(all.map((p) => [p.id, p]));
  const nested = all.filter((p) => p.in && byIdAll.has(p.in) && p.in !== p.id);
  const parts = all.filter((p) => !nested.includes(p));
  const cells = parts.map(sceneCell);
  const cols = Math.max(1, ...cells.map((c) => c.col + c.w));
  const rows = Math.max(1, ...cells.map((c) => c.row + c.h));
  // A scene uses the gutters the other layouts reserve for callouts, because
  // its labels are placed AT the feature instead — see below. It may do that
  // only while every label really is short enough to sit in a cell. One
  // clause-length callout needs a margin to sit in, and a scene that had taken
  // the margins printed it over the drawing: the first live redraw came back
  // with three of them lying across the turbine.
  //
  // Measured on the WIDE geometry first, so the choice cannot oscillate:
  // narrowing only shrinks the cells, which can push more labels out but never
  // pull one back in.
  const printedWidth = (text: string) =>
    text.replace(GAP_RE, (_m, n: string) => `${n} ..........`).length * 6.6;
  const CELL_SLACK = 1.3;
  const wideLeft = PAD + 44;
  const wideW = W - PAD - 44 - wideLeft;
  const anyClause = (visual.labels ?? []).some(
    (label) => printedWidth(label.text) >= (wideW / cols) * CELL_SLACK
  );
  const left = anyClause ? DRAW_L : wideLeft;
  const width = anyClause ? DRAW_W : wideW;
  const cellW = width / cols;
  const cellH = Math.max(56, Math.min(92, 360 / rows));
  const originY = TITLE_H;

  const cellBox = (col: number, row: number, w = 1, h = 1): Box => ({
    x: left + col * cellW,
    y: originY + row * cellH,
    w: w * cellW,
    h: h * cellH,
  });

  const taken = new Set<string>();
  cells.forEach((c) => {
    for (let dc = 0; dc < c.w; dc++)
      for (let dr = 0; dr < c.h; dr++) taken.add(`${c.col + dc},${c.row + dr}`);
  });

  const body: ReactNode[] = [];
  const captions: ReactNode[] = [];
  const anchors: Anchor[] = [];
  const drawnBox = new Map<string, Box>();

  const holdsSomething = new Set(nested.map((p) => p.in));
  parts.forEach((part, i) => {
    const c = cells[i];
    const below = taken.has(`${c.col},${c.row + c.h}`);
    const above = c.row > 0 && taken.has(`${c.col},${c.row - 1}`);
    const cell = cellBox(c.col, c.row, c.w, c.h);
    const box = fitBox(part.form, cell, below, above, holdsSomething.has(part.id));
    // The cell, not the fitted shape, is what a name printed underneath has
    // to fit inside — otherwise it runs into the name under the next part.
    const drawn = drawForm(part, box, cell.w);
    body.push(<Fragment key={`sc-${part.id}-${i}`}>{drawn.ink}</Fragment>);
    // A container's name rides at its top edge instead of its centre, where
    // its own contents are: an egg's "Shell" was printed across its yolk.
    const label =
      holdsSomething.has(part.id) && part.name
        ? text(gapText(part.name), box.x + box.w / 2, box.y + 14, { size: 12 })
        : drawn.text;
    captions.push(<Fragment key={`sct-${part.id}-${i}`}>{label}</Fragment>);
    drawnBox.set(part.id, box);
    const ink = inkEdges(part.form, box);
    anchors.push({
      id: part.id,
      x: box.x + box.w / 2,
      y: box.y + box.h / 2,
      left: ink.left,
      right: ink.right,
    });
  });

  // ---- Contents, drawn after their containers so the container's paper fill
  // does not swallow them. Position comes from a 3x3 sub-grid of the
  // container, which keeps two things inside one shell from overlapping.
  nested.forEach((part, i) => {
    const host = drawnBox.get(part.in as string);
    if (!host) return;
    const sub = 3;
    const col = Math.max(0, Math.min(sub - 1, Math.round(part.col ?? 1)));
    const row = Math.max(0, Math.min(sub - 1, Math.round(part.row ?? 1)));
    // A round shell holds its contents in the rectangle INSCRIBED in it. Given
    // the bounding box, an egg put its yolk in a corner and its air cell half
    // outside the shell — 1/sqrt(2) is where the corners of that rectangle
    // touch the curve.
    const hostForm = byIdAll.get(part.in as string)?.form ?? "";
    const round = ROUND_FORMS.has(hostForm);
    const kx = round ? host.w * (1 - 0.707) / 2 : 10;
    // A named container prints its name along its top edge, so its contents
    // start below it — the beehive's frames ran through "Brood box".
    const named = !!byIdAll.get(part.in as string)?.name;
    const ky = (round ? host.h * (1 - 0.707) / 2 : 10) + (named ? 14 : 0);
    const iw = (host.w - kx * 2) / sub;
    const ih = (host.h - ky - (round ? ky : 10)) / sub;
    const span = Math.max(1, Math.min(sub - col, Math.round(part.w ?? 1)));
    const high = Math.max(1, Math.min(sub - row, Math.round(part.h ?? 1)));
    const cell: Box = {
      x: host.x + kx + col * iw,
      y: host.y + ky + row * ih,
      w: span * iw,
      h: high * ih,
    };
    const box = FILLS_CELL.has(part.form) ? cell : fitBox(part.form, cell, false, false);
    const drawn = drawForm(part, box, cell.w, false);
    body.push(<Fragment key={`nest-${part.id}-${i}`}>{drawn.ink}</Fragment>);
    captions.push(<Fragment key={`nestt-${part.id}-${i}`}>{drawn.text}</Fragment>);
    drawnBox.set(part.id, box);
    const ink = inkEdges(part.form, box);
    anchors.push({
      id: part.id,
      x: box.x + box.w / 2,
      y: box.y + box.h / 2,
      left: ink.left,
      right: ink.right,
    });
  });

  // ---- Links. An assembly whose parts are not joined reads as a row of
  // separate objects; the exam draws the pipe, the shaft, the arrow.
  (visual.links ?? []).forEach((link: VisualDiagramLink, i) => {
    const a = drawnBox.get(link.from);
    const b = drawnBox.get(link.to);
    if (!a || !b) return;
    const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
    const bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    // Meet each box on the face that points at the other, so a link never
    // starts in the middle of the shape it leaves.
    const edge = (box: Box, towards: { x: number; y: number }) => {
      const c = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
      const dx = towards.x - c.x;
      const dy = towards.y - c.y;
      if (Math.abs(dx) * box.h > Math.abs(dy) * box.w) {
        return { x: dx > 0 ? box.x + box.w : box.x, y: c.y };
      }
      return { x: c.x, y: dy > 0 ? box.y + box.h : box.y };
    };
    const p1 = edge(a, bc);
    const p2 = edge(b, ac);
    const style = link.style ?? "line";
    body.push(
      <Fragment key={`lk-${i}-${link.from}-${link.to}`}>
        {style === "pipe" ? (
          <>
            <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
                  stroke="currentColor" strokeWidth={11} opacity={0.12} />
            <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
                  stroke="currentColor" strokeWidth={1.6} />
          </>
        ) : (
          <line
            x1={p1.x}
            y1={p1.y}
            x2={p2.x}
            y2={p2.y}
            stroke="currentColor"
            strokeWidth={1.6}
            markerEnd={style === "arrow" ? "url(#dg-arrow)" : undefined}
          />
        )}
      </Fragment>
    );
    if (link.label) {
      captions.push(
        <Fragment key={`lkt-${i}`}>
          {text(gapText(link.label), (p1.x + p2.x) / 2, (p1.y + p2.y) / 2 - 9, {
            size: 12,
          })}
        </Fragment>
      );
    }
  });

  // ---- Labels at the feature, not in a margin.
  //
  // This is the thing that makes a scene read as an exam figure. The official
  // Cambridge sample ("Dung Beetle Types") puts blank 6 upper-left, 8
  // upper-right and 7 lower-middle — each beside the tunnel it names, on a
  // short leader. Sent to a gutter instead, two leaders on the fire
  // extinguisher ran the width of the drawing and crossed the nozzle on the
  // way, which reads as part of the machine.
  let lowest = originY + rows * cellH;
  const byId = new Map(parts.map((p, i) => [p.id, cells[i]]));
  // A nested part is labelled through its container's cell: it has none of its
  // own, and a label for it still has to find somewhere free to sit.
  nested.forEach((p) => {
    const host = byId.get(p.in as string);
    if (host) byId.set(p.id, host);
  });
  const claimed = new Set<string>();
  let overflow = 0;

  const insideOf = new Map(nested.map((p) => [p.id, p.in as string]));

  // Which labels this layout places itself, and which go out to the gutters.
  //
  // Placing them AT the feature is what makes a scene read as an exam figure,
  // and it is what the official Cambridge sample does — but only because the
  // labels on that sample are two or three words. A callout is now a CLAUSE
  // ("Whole tower can be raised for 24 .......... and the extraction of
  // seaweed from the blades"), and a clause dropped into a grid cell printed
  // straight across the drawing: the first live redraw came back with three of
  // them lying over the turbine.
  //
  // So the split is by length, not by layout. A label that fits its cell stays
  // where the exam puts it; a clause goes to the margin, where the exam puts
  // THAT. Both are Cambridge's own behaviour on the same page.
  const fitsACell = (text: string) => printedWidth(text) < cellW * CELL_SLACK;
  // A part with any long label sends ALL of its labels out, so a short one on
  // the same part cannot be drawn twice — once here and once in the gutter.
  const toGutter = new Set(
    (visual.labels ?? [])
      .filter((label) => !fitsACell(label.text))
      .map((label) => label.at)
  );

  (visual.labels ?? []).forEach((label, i) => {
    const c = byId.get(label.at);
    const box = drawnBox.get(label.at);
    if (!c || !box || toGutter.has(label.at)) return;

    // A part drawn inside another gets its label just outside the CONTAINER,
    // level with itself — short, and pointing at the right thing. Sent to a
    // free grid cell it trailed a leader the width of the figure, because
    // every cell near a big container belongs to the container.
    const hostBox = drawnBox.get(insideOf.get(label.at) ?? "");
    if (hostBox) {
      const partMid = box.x + box.w / 2;
      const leftSide =
        partMid < hostBox.x + hostBox.w / 2 ? true : false;
      const tx = leftSide ? hostBox.x - 34 : hostBox.x + hostBox.w + 34;
      const ty = box.y + box.h / 2;
      const ex = leftSide ? box.x : box.x + box.w;
      lowest = Math.max(lowest, ty + 14);
      body.push(
        <Fragment key={`nl-${i}-${label.at}`}>
          <line
            x1={tx}
            y1={ty}
            x2={ex}
            y2={ty}
            stroke="currentColor"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.75"
          />
          <circle cx={ex} cy={ty} r="2.4" fill="currentColor" />
        </Fragment>
      );
      captions.push(
        <Fragment key={`nlt-${i}-${label.at}`}>
          {text(gapText(label.text), tx, ty, {
            size: 13,
            anchor: leftSide ? "end" : "start",
          })}
        </Fragment>
      );
      return;
    }
    // Prefer a free cell beside the part; a label may also sit one cell
    // outside the grid, which is open canvas.
    const options: Array<[number, number]> = [
      [c.col + c.w, c.row],
      [c.col - 1, c.row],
      [c.col, c.row - 1],
      [c.col + c.w, c.row - 1],
      [c.col - 1, c.row - 1],
      [c.col, c.row + c.h],
      [c.col + c.w, c.row + c.h],
      [c.col - 1, c.row + c.h],
    ];
    const spot = options.find(([col, row]) => {
      if (row < 0 || row > rows) return false;
      const probe = cellBox(col, row);
      // Off-canvas is not a free cell. A scene wide enough to use the margins
      // has no column -1 to put a label in, and the first one written there
      // ran off the left edge of the card.
      if (probe.x < PAD || probe.x + probe.w > W - PAD) return false;
      const key = `${col},${row}`;
      return !taken.has(key) && !claimed.has(key);
    });
    // Nowhere free beside it: drop below the whole figure rather than land on
    // a part. Printed into the first occupied cell instead, "16" sat inside
    // the solar panel it was naming.
    const target = spot
      ? cellBox(spot[0], spot[1])
      : { ...cellBox(c.col, rows), y: originY + rows * cellH + overflow * 26 };
    if (spot) claimed.add(`${spot[0]},${spot[1]}`);
    else overflow += 1;

    const tx = target.x + target.w / 2;
    const ty = target.y + target.h / 2;
    // Meet the part on the side the label approaches from.
    const ex = tx < box.x ? box.x : tx > box.x + box.w ? box.x + box.w : tx;
    const ey = ty < box.y ? box.y : ty > box.y + box.h ? box.y + box.h : ty;
    lowest = Math.max(lowest, ty + 14);

    body.push(
      <Fragment key={`sl-${i}-${label.at}`}>
        <line
          x1={tx}
          y1={ty}
          x2={ex}
          y2={ey}
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="3 3"
          opacity="0.75"
        />
        <circle cx={ex} cy={ey} r="2.4" fill="currentColor" />
      </Fragment>
    );
    captions.push(
      <Fragment key={`slt-${i}-${label.at}`}>
        {text(gapText(label.text), tx, ty, { size: 13 })}
      </Fragment>
    );
  });

  return {
    body: (
      <>
        {body}
        {captions}
      </>
    ),
    // Anchors ONLY for the parts whose callouts were too long to sit in a
    // cell. The shared gutter placement draws exactly those and finds nothing
    // for the rest, which this layout has already placed at the feature.
    anchors: [...toGutter]
      .map((id) => {
        const box = drawnBox.get(id);
        if (!box) return null;
        return {
          id,
          x: box.x + box.w / 2,
          y: box.y + box.h / 2,
          left: box.x,
          right: box.x + box.w,
        } satisfies Anchor;
      })
      .filter((a): a is Anchor => a !== null),
    height: lowest + PAD,
    x0: left - 8,
    x1: left + width + 8,
  };
}

function apparatus(visual: VisualDiagram): Drawn {
  const parts = visual.parts ?? [];
  const spine = parts.filter((p) => !(p.attach && p.to));
  const hung = parts.filter((p) => p.attach && p.to);

  const body: ReactNode[] = [];
  // Names are held back and drawn over every shape, so a part cannot bury the
  // one above it. See drawForm.
  const captions: ReactNode[] = [];
  const anchors: Anchor[] = [];
  const placed = new Map<string, { x: number; y: number; w: number; h: number }>();

  // A `ground` part is the floor whatever order it was written in — the model
  // reliably names the seabed but not reliably last.
  const stack = [
    ...spine.filter((p) => p.form !== "ground"),
    ...spine.filter((p) => p.form === "ground"),
  ];

  let y = TITLE_H;
  for (const part of stack) {
    const { h, w } = formBox(part.form);
    const box = { x: CX - w / 2, y, w, h };
    const drawn = drawForm(part, box);
    body.push(<Fragment key={`spine-${part.id}`}>{drawn.ink}</Fragment>);
    captions.push(<Fragment key={`spine-t-${part.id}`}>{drawn.text}</Fragment>);
    placed.set(part.id, { x: CX, y: y + h / 2, w, h });
    const ink = inkEdges(part.form, box);
    anchors.push({
      id: part.id,
      x: CX,
      y: y + h / 2,
      left: ink.left,
      right: ink.right,
    });
    y += h;
  }

  // Attachments, joined to their host by a short connector.
  for (const part of hung) {
    const host = placed.get(part.to as string);
    if (!host) continue;
    const { h, w } = formBox(part.form);
    const side = part.attach === "left" ? -1 : 1;
    const armed = host.w / 2 + 34;
    const cx = host.x + side * (armed + w / 2);
    const box = { x: cx - w / 2, y: host.y - h / 2, w, h };
    const drawn = drawForm(part, box);
    body.push(
      <Fragment key={`hung-${part.id}`}>
        <line
          x1={host.x + side * (host.w / 2)}
          y1={host.y}
          x2={cx - side * (w / 2)}
          y2={host.y}
          stroke="currentColor"
          strokeWidth={1.6}
        />
        {drawn.ink}
      </Fragment>
    );
    captions.push(<Fragment key={`hung-t-${part.id}`}>{drawn.text}</Fragment>);
    const ink = inkEdges(part.form, box);
    anchors.push({
      id: part.id,
      x: cx,
      y: host.y,
      left: ink.left,
      right: ink.right,
    });
    // The host now has something hanging off that side, so its own callout
    // goes to the other one. Widening the host's edge past the attachment was
    // the first attempt and it put both leaders in the same place.
    const hostAnchor = anchors.find((a) => a.id === part.to);
    if (hostAnchor) hostAnchor.avoid = side < 0 ? "left" : "right";
  }

  return {
    body: (
      <>
        {body}
        {captions}
      </>
    ),
    anchors,
    height: y + PAD,
  };
}

type Box = { x: number; y: number; w: number; h: number };

/** A Box in the layouts' own vocabulary, as SVG spells it. Spreading a Box
 * straight into <rect> silently draws nothing, because `w`/`h` are not
 * `width`/`height` — which is exactly how the first render came out empty. */
function rectOf(b: Box) {
  return { x: b.x, y: b.y, width: b.w, height: b.h };
}

/** Draw one part in the exam's line art. Each form is a real outline, not a
 * labelled rectangle — that difference is the whole point of the layout. */
/** One part, drawn in the exam's line art.
 *
 * Returns the ink and the printed name SEPARATELY, because an assembly is
 * stacked: a name printed under a disc lands on top of the part below it, and
 * that part is drawn afterwards, so its paper fill swallows the text. The
 * caller draws every shape first and every name second. Each form is a real
 * outline rather than a labelled rectangle, which is the whole point of the
 * layout.
 */
function drawForm(
  part: VisualDiagramPart,
  b: Box,
  /** The CELL the shape was fitted into, when it is wider than the shape.
   *
   * A name printed under a small shape used to be one unwrapped line measured
   * against the shape, so "Circulation pump" under a disc ran the width of two
   * cells and collided with the name under the next one. It has the cell's
   * width to use, not the disc's. */
  cellW = b.w,
  /** Is the paper under the shape the shape's own?
   *
   * On the main grid it is: the cell belongs to this part and nothing else is
   * drawn in it. Inside a CONTAINER it is not — the space below a part is the
   * next part of the cross-section. 🔬 "Horizontal tunnels", too wide for its
   * pipe, fell back to being printed underneath and landed across "Brood
   * cavity". Inside a container a name that does not fit is dropped, which is
   * the trade `blank_self_answering_labels` already makes for one. */
  roomBelow = true
): { ink: ReactNode; text: ReactNode } {
  const cx = b.x + b.w / 2;
  const cy = b.y + b.h / 2;
  const name = part.name?.trim();
  const inside = name ? inShape(name, cx, cy, b.w, 13, b.h) : null;
  const below = (dy: number) => {
    if (!name) return null;
    const lines = wrapCallout(name, Math.max(cellW, b.w) - 8, 12);
    return lines.map((line, i) => (
      <Fragment key={`bn-${i}`}>
        {text(gapText(line), cx, b.y + b.h + dy + i * 14, { size: 12 })}
      </Fragment>
    ));
  };
  // A name too big for the shape goes UNDER it rather than across it. The
  // shape's own cell is reserved for the shape, so there is room below that
  // belongs to nobody else — which is not true of the middle of a drawing.
  const nameText = inside ?? (roomBelow ? below(14) : null);

  switch (part.form) {
    case "ground": {
      // A surface, not a slab. Given a whole grid cell this filled a third of
      // the figure with hatching; the exam draws a line with a shallow band of
      // hatch beneath it.
      const deep = Math.min(b.h, 26);
      return {
        ink: (
          <>
            <rect
              x={b.x}
              y={b.y}
              width={b.w}
              height={deep}
              fill="url(#dg-hatch)"
              stroke="none"
            />
            <line
              x1={b.x}
              y1={b.y}
              x2={b.x + b.w}
              y2={b.y}
              stroke="currentColor"
              strokeWidth={1.8}
            />
          </>
        ),
        // Below the hatching, ranged left. Nothing is ever drawn under the
        // ground, so this is the one strip of the figure that cannot collide.
        // Centred ABOVE the line it printed through whatever stood in the
        // middle ("Base" through a water tank's name); ranged left above the
        // line it printed through whatever stood at the left edge ("Sea floor"
        // through a diver's canvas suit). Both seen live on 2026-08-28.
        text: name
          ? text(gapText(name), b.x + 6, b.y + deep + 11, {
              size: 12,
              anchor: "start",
            })
          : null,
      };
    }
    case "liquid":
      return {
        ink: (
          <path
            d={waveTop(b)}
            {...SHAPE}
            fill="currentColor"
            fillOpacity={0.08}
            stroke="currentColor"
          />
        ),
        text: nameText,
      };
    case "tank":
      return {
        ink: (
          <>
            <path
              d={`M${b.x},${b.y + 12} L${b.x},${b.y + b.h - 12}
                  A${b.w / 2},12 0 0 0 ${b.x + b.w},${b.y + b.h - 12}
                  L${b.x + b.w},${b.y + 12}
                  A${b.w / 2},12 0 0 0 ${b.x},${b.y + 12} Z`}
              {...SHAPE}
            />
            <path
              d={`M${b.x},${b.y + 12} A${b.w / 2},12 0 0 0 ${b.x + b.w},${b.y + 12}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={1.2}
              opacity={0.55}
            />
          </>
        ),
        text: nameText,
      };
    case "dome":
      return {
        ink: (
          <path
            d={`M${b.x},${b.y + b.h} A${b.w / 2},${b.h} 0 0 1 ${b.x + b.w},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: name ? text(gapText(name), cx, b.y + b.h * 0.62, { size: 12 }) : null,
      };
    case "funnel":
      return {
        ink: (
          <path
            d={`M${b.x},${b.y} L${b.x + b.w},${b.y}
                L${cx + b.w * 0.13},${b.y + b.h} L${cx - b.w * 0.13},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: name ? text(gapText(name), cx, b.y + b.h * 0.38, { size: 12 }) : null,
      };
    case "disc":
      return {
        ink: (
          <>
            <circle cx={cx} cy={cy} r={b.w / 2} {...SHAPE} />
            <circle cx={cx} cy={cy} r={b.w / 8} {...SHAPE} />
          </>
        ),
        // Inside the ring rather than under it: a disc in an assembly has the
        // next part immediately below, and "Bobbin" printed there is buried.
        text: name ? inShape(name, cx, cy + b.w / 4, b.w, 11, b.h / 2) : null,
      };
    case "rotor":
      return {
        ink: (
          <>
            {[0, 120, 240].map((deg) => (
              <path
                key={deg}
                d={`M${cx},${cy} L${cx - 9},${cy - b.h / 2 + 6} L${cx + 9},${cy - b.h / 2 + 6} Z`}
                transform={`rotate(${deg} ${cx} ${cy})`}
                {...SHAPE}
              />
            ))}
            <line
              x1={cx}
              y1={cy}
              x2={cx}
              y2={b.y + b.h}
              stroke="currentColor"
              strokeWidth={1.6}
            />
            <circle cx={cx} cy={cy} r={11} {...SHAPE} />
          </>
        ),
        text: below(10),
      };
    case "coil":
      return {
        ink: <path d={coil(b)} fill="none" stroke="currentColor" strokeWidth={1.6} />,
        text: below(10),
      };
    case "valve":
      return {
        ink: (
          <path
            d={`M${b.x},${b.y} L${b.x + b.w},${b.y + b.h} L${b.x + b.w},${b.y}
                L${b.x},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: below(10),
      };
    case "oval":
      return {
        ink: <ellipse cx={cx} cy={cy} rx={b.w / 2} ry={b.h / 2} {...SHAPE} />,
        text: nameText,
      };
    case "canister":
      // A soda can, a fire extinguisher: a cylinder with a rounded shoulder
      // and a rim, which is what makes it read as a can rather than a tank.
      return {
        ink: (
          <>
            <path
              d={`M${b.x},${b.y + b.h} L${b.x},${b.y + 16} Q${b.x},${b.y} ${b.x + 14},${b.y} L${b.x + b.w - 14},${b.y} Q${b.x + b.w},${b.y} ${b.x + b.w},${b.y + 16} L${b.x + b.w},${b.y + b.h} Z`}
              {...SHAPE}
            />
            <line
              x1={b.x}
              y1={b.y + 22}
              x2={b.x + b.w}
              y2={b.y + 22}
              stroke="currentColor"
              strokeWidth={1.2}
              opacity={0.6}
            />
          </>
        ),
        text: nameText,
      };
    case "wheel":
      // A Ferris wheel, a pulley: rim, hub and spokes. Four crossing spokes
      // read as a wheel; two read as a cross.
      return {
        ink: (
          <>
            <circle cx={cx} cy={cy} r={b.w / 2} {...SHAPE} />
            {[0, 45, 90, 135].map((deg) => (
              <line
                key={deg}
                x1={cx - b.w / 2}
                y1={cy}
                x2={cx + b.w / 2}
                y2={cy}
                transform={`rotate(${deg} ${cx} ${cy})`}
                stroke="currentColor"
                strokeWidth={1.1}
              />
            ))}
            <circle cx={cx} cy={cy} r={b.w / 9} {...SHAPE} />
          </>
        ),
        text: below(10),
      };
    case "stand":
      return {
        ink: (
          <>
            <line x1={cx - 6} y1={b.y} x2={b.x} y2={b.y + b.h} stroke="currentColor" strokeWidth={1.6} />
            <line x1={cx + 6} y1={b.y} x2={b.x + b.w} y2={b.y + b.h} stroke="currentColor" strokeWidth={1.6} />
            <line x1={b.x + b.w * 0.2} y1={b.y + b.h * 0.62} x2={b.x + b.w * 0.8} y2={b.y + b.h * 0.62} stroke="currentColor" strokeWidth={1.2} />
          </>
        ),
        text: below(10),
      };
    case "panel":
      // A solar array, a screen: a rectangle ruled into cells.
      return {
        ink: (
          <>
            <rect {...rectOf(b)} {...SHAPE} />
            {[1, 2, 3].map((k) => (
              <line
                key={`v${k}`}
                x1={b.x + (b.w * k) / 4}
                y1={b.y}
                x2={b.x + (b.w * k) / 4}
                y2={b.y + b.h}
                stroke="currentColor"
                strokeWidth={1}
                opacity={0.65}
              />
            ))}
            <line x1={b.x} y1={cy} x2={b.x + b.w} y2={cy} stroke="currentColor" strokeWidth={1} opacity={0.65} />
          </>
        ),
        // Inside, not below: a panel is wide and flat, and its caption set
        // underneath landed on the ground hatching in a scene.
        text: nameText,
      };
    case "stack":
      // Beehive supers, stacked crates.
      return {
        ink: (
          <>
            {[0, 1, 2].map((k) => (
              <rect
                key={k}
                x={b.x}
                y={b.y + (b.h * k) / 3}
                width={b.w}
                height={b.h / 3}
                {...SHAPE}
              />
            ))}
          </>
        ),
        text: nameText,
      };
    case "mound":
      // A cow pat, a heap of soil: a low hump sitting on its baseline.
      return {
        ink: (
          <path
            d={`M${b.x},${b.y + b.h} Q${cx},${b.y - b.h * 0.35} ${b.x + b.w},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: nameText,
      };
    case "cone":
      return {
        ink: (
          <path
            d={`M${cx},${b.y} L${b.x + b.w},${b.y + b.h} L${b.x},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: name ? text(gapText(name), cx, b.y + b.h * 0.7, { size: 12 }) : null,
      };
    case "nozzle":
      return {
        ink: (
          <path
            d={`M${b.x},${b.y} L${b.x + b.w},${cy - 5} L${b.x + b.w},${cy + 5} L${b.x},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: below(10),
      };
    case "hose":
      return {
        ink: (
          <path
            d={`M${b.x},${b.y} C${b.x + b.w},${b.y + b.h * 0.2} ${b.x},${b.y + b.h * 0.8} ${b.x + b.w},${b.y + b.h}`}
            fill="none"
            stroke="currentColor"
            strokeWidth={3}
            strokeLinecap="round"
          />
        ),
        text: below(8),
      };
    case "handle":
      return {
        ink: (
          <>
            <line x1={b.x + 8} y1={b.y + b.h} x2={b.x + 8} y2={b.y + 8} stroke="currentColor" strokeWidth={1.6} />
            <line x1={b.x + b.w - 8} y1={b.y + b.h} x2={b.x + b.w - 8} y2={b.y + 8} stroke="currentColor" strokeWidth={1.6} />
            <rect x={b.x} y={b.y} width={b.w} height={9} rx={4} {...SHAPE} />
          </>
        ),
        text: below(8),
      };
    case "lever":
      return {
        ink: (
          <>
            <line x1={b.x} y1={b.y + 6} x2={b.x + b.w} y2={b.y + b.h * 0.55} stroke="currentColor" strokeWidth={2.4} />
            <path
              d={`M${cx - 12},${b.y + b.h} L${cx},${b.y + b.h - 22} L${cx + 12},${b.y + b.h} Z`}
              {...SHAPE}
            />
          </>
        ),
        text: below(8),
      };
    case "arm":
      // A jointed arm — the Mars probe's instrument arm, a crane jib.
      return {
        ink: (
          <>
            <line x1={b.x} y1={b.y + b.h} x2={b.x + b.w * 0.45} y2={b.y + 8} stroke="currentColor" strokeWidth={2.4} />
            <line x1={b.x + b.w * 0.45} y1={b.y + 8} x2={b.x + b.w} y2={b.y + b.h * 0.5} stroke="currentColor" strokeWidth={2.4} />
            <circle cx={b.x + b.w * 0.45} cy={b.y + 8} r={5} {...SHAPE} />
          </>
        ),
        text: below(8),
      };
    case "antenna":
      return {
        ink: (
          <>
            <line x1={cx} y1={b.y + b.h} x2={cx} y2={b.y + 18} stroke="currentColor" strokeWidth={1.8} />
            <path
              d={`M${cx - 22},${b.y + 20} A22,20 0 0 1 ${cx + 22},${b.y + 20} Z`}
              {...SHAPE}
            />
          </>
        ),
        text: below(8),
      };
    case "spring":
      return {
        ink: (
          <path
            d={[...Array(6)]
              .map(
                (_, k) =>
                  `${k === 0 ? "M" : "L"}${k % 2 ? b.x + b.w : b.x},${b.y + (b.h * k) / 5}`
              )
              .join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
          />
        ),
        text: below(8),
      };
    case "blade":
      return {
        ink: (
          <path
            d={`M${cx},${b.y} Q${b.x + b.w},${cy} ${cx},${b.y + b.h} Q${b.x},${cy} ${cx},${b.y} Z`}
            {...SHAPE}
          />
        ),
        text: below(8),
      };
    case "frame":
      return {
        ink: (
          <>
            <rect {...rectOf(b)} {...SHAPE} />
            <rect
              x={b.x + 8}
              y={b.y + 8}
              width={Math.max(0, b.w - 16)}
              height={Math.max(0, b.h - 16)}
              fill="none"
              stroke="currentColor"
              strokeWidth={1}
              opacity={0.6}
            />
          </>
        ),
        text: nameText,
      };
    case "gauge":
      // A dial with a needle. Without a case here it fell through to the plain
      // rectangle, and a pressure gauge on a cross-section was an empty box.
      return {
        ink: (
          <>
            <circle cx={cx} cy={cy} r={Math.min(b.w, b.h) / 2} {...SHAPE} />
            <line
              x1={cx}
              y1={cy}
              x2={cx + Math.min(b.w, b.h) * 0.3}
              y2={cy - Math.min(b.w, b.h) * 0.3}
              stroke="currentColor"
              strokeWidth={2}
            />
            <circle cx={cx} cy={cy} r={3} fill="currentColor" />
          </>
        ),
        text: below(10),
      };
    case "cap":
      return {
        ink: (
          <path
            d={`M${b.x + 10},${b.y + b.h} L${b.x + 10},${b.y + 6} Q${b.x + 10},${b.y} ${b.x + 20},${b.y} L${b.x + b.w - 20},${b.y} Q${b.x + b.w - 10},${b.y} ${b.x + b.w - 10},${b.y + 6} L${b.x + b.w - 10},${b.y + b.h} Z`}
            {...SHAPE}
          />
        ),
        text: below(8),
      };
    case "pipe": {
      // A narrow tube spanning its cell, laid along whichever way the cell is
      // longer, so it reaches the parts either side. Drawn at its natural size
      // it was a small empty rectangle floating in the gap it was meant to
      // bridge.
      const flat = b.w >= b.h;
      const bore = 16;
      const run = flat
        ? { x: b.x, y: cy - bore / 2, w: b.w, h: bore }
        : { x: cx - bore / 2, y: b.y, w: bore, h: b.h };
      return {
        ink: <rect {...rectOf(run)} {...SHAPE} />,
        text: nameText,
      };
    }
    case "platform":
      return { ink: <rect {...rectOf(b)} {...SHAPE} />, text: nameText };
    case "column":
    case "chamber":
      return {
        ink: (
          <rect
            {...rectOf(b)}
            rx={part.form === "chamber" ? 8 : 2}
            {...SHAPE}
          />
        ),
        text: nameText,
      };
    default:
      return { ink: <rect {...rectOf(b)} rx={3} {...SHAPE} />, text: nameText };
  }
}


function waveTop(b: Box): string {
  const step = b.w / 4;
  let d = `M${b.x},${b.y + 6}`;
  for (let i = 0; i < 4; i++) {
    const x0 = b.x + i * step;
    d += ` Q${x0 + step / 4},${b.y} ${x0 + step / 2},${b.y + 6}`;
    d += ` Q${x0 + (step * 3) / 4},${b.y + 12} ${x0 + step},${b.y + 6}`;
  }
  d += ` L${b.x + b.w},${b.y + b.h} L${b.x},${b.y + b.h} Z`;
  return d;
}

function coil(b: Box): string {
  const turns = 5;
  const step = b.h / turns;
  let d = `M${b.x},${b.y}`;
  for (let i = 0; i < turns; i++) {
    const y0 = b.y + i * step;
    d += ` C${b.x + b.w * 1.25},${y0 + step * 0.2} ${b.x - b.w * 0.25},${y0 + step * 0.8} ${b.x + b.w},${y0 + step}`;
  }
  return d;
}

// ---------------------------------------------------------------------------
// Layout: layers — a strata cross-section.
//
// "Cross-section of the same area at the time the article was written:
// granite / mud / water / stiff clay / sand". Bands run the full width, top of
// the section down, in the order the parts were listed.
// ---------------------------------------------------------------------------

/** A strata section with no callouts is drawn wider than the gutters allow,
 * because its text sits INSIDE the bands rather than out at the end of
 * leaders.
 *
 * Only when it has none. `placeLabels` measures its columns from the global
 * GUTTER, so a section that took the extra width AND carried a callout had the
 * callout printed on top of its own bands — visible the moment the gutters
 * were widened to hold a Cambridge-length sentence, and wrong by 42px even
 * before that. */
const WIDE_L = PAD + 100;
const WIDE_R = W - PAD - 100;

function layers(visual: VisualDiagram): Drawn {
  const parts = visual.parts ?? [];
  const bare = (visual.labels ?? []).length === 0;
  const LAYER_L = bare ? WIDE_L : DRAW_L;
  const LAYER_R = bare ? WIDE_R : DRAW_R;
  const LAYER_W = LAYER_R - LAYER_L;
  const LAYER_CX = (LAYER_L + LAYER_R) / 2;
  const bandH = parts.length > 6 ? 46 : 58;
  const body: ReactNode[] = [];
  const anchors: Anchor[] = [];
  let y = TITLE_H;

  parts.forEach((part, i) => {
    const b = { x: LAYER_L, y, w: LAYER_W, h: bandH };
    const solid = part.form === "rock" || part.form === "clay";
    body.push(
      <Fragment key={part.id}>
        <rect
          {...rectOf(b)}
          fill={solid ? "url(#dg-hatch)" : "var(--card, #fff)"}
          stroke="currentColor"
          strokeWidth={1.6}
        />
        {part.form === "water" && (
          <path
            d={waveTop({ ...b, h: 6 })}
            fill="currentColor"
            fillOpacity={0.1}
            stroke="currentColor"
            strokeWidth={1.2}
          />
        )}
        {part.form === "sand" &&
          [...Array(14)].map((_, k) => (
            <circle
              key={k}
              cx={b.x + 14 + ((k * 37) % (b.w - 28))}
              cy={b.y + 12 + ((k * 23) % (b.h - 24))}
              r="1.6"
              fill="currentColor"
              opacity="0.5"
            />
          ))}
        {part.name && inShape(part.name, LAYER_CX, y + bandH / 2, LAYER_W - 40, 13, bandH)}
      </Fragment>
    );
    anchors.push({
      id: part.id,
      x: LAYER_CX,
      y: y + bandH / 2,
      left: LAYER_L,
      right: LAYER_R,
    });
    y += bandH;
    void i;
  });

  return { body: <>{body}</>, anchors, height: y + PAD };
}

// ---------------------------------------------------------------------------
// Layout: cycle — a process that returns to its start.
//
// "THE OPERATIONAL CYCLE": float dropped into ocean, records salinity, surfaces,
// transmits by satellite, information analysed, and round again. Stages sit on
// a circle clockwise from the top, with an arc arrow between each pair.
// ---------------------------------------------------------------------------

function cycle(visual: VisualDiagram): Drawn {
  const parts = (visual.parts ?? []).slice(0, 8);
  const n = Math.max(parts.length, 1);
  const boxH = 52;
  // 🔬 The ring used to be sized only by the chord between neighbouring
  // stages, so it grew to R=210 — and the drawing area between the callout
  // gutters is only DRAW_W wide. Every box past the top and bottom of the ring
  // was drawn out under the callouts: a monarch life cycle printed "The 1
  // .......... is where females deposit their eggs" straight across the box
  // labelled "Egg". The ring has to fit the paper it is drawn on FIRST.
  //
  // Both constraints at once. With the ring inset by half a box,
  //   R = DRAW_W/2 - b/2 - 6
  // and n boxes plus their arrows have to fit the circumference,
  //   n(b + 20) <= 2.pi.R
  // which solves for the widest box that can work:
  //   b <= (pi.DRAW_W - 12.pi - 20n) / (n + pi)
  const widest = Math.floor(
    (Math.PI * (DRAW_W - 12) - 20 * n) / (n + Math.PI)
  );
  const boxW = Math.max(76, Math.min(124, widest));
  const R = n > 1 ? Math.round(Math.max(96, DRAW_W / 2 - boxW / 2 - 6)) : 126;
  const cy = TITLE_H + R + 46;
  const body: ReactNode[] = [];
  const anchors: Anchor[] = [];

  const angleOf = (i: number) => (i / n) * Math.PI * 2 - Math.PI / 2;
  const on = (angle: number) => ({
    x: r2(CX + R * Math.cos(angle)),
    y: r2(cy + R * Math.sin(angle)),
  });
  const at = (i: number) => on(angleOf(i));

  // Back the arc off each box by the angle its half-width subtends, so the
  // head is drawn in open paper. Run to the box CENTRE and the arrowhead lands
  // under the next box's fill: the ring loses its direction entirely.
  const clear = r2(Math.min((boxW / 2 + 12) / R, Math.PI / n - 0.06));
  for (let i = 0; i < n && n > 1; i++) {
    const a = on(angleOf(i) + clear);
    const b = on(angleOf(i + 1) - clear);
    body.push(
      <path
        key={`arc-${i}`}
        d={`M${a.x},${a.y} A${R},${R} 0 0 1 ${b.x},${b.y}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.4}
        markerEnd="url(#dg-arrow)"
        opacity={0.85}
      />
    );
  }

  parts.forEach((part, i) => {
    const p = at(i);
    body.push(
      <Fragment key={part.id}>
        <rect
          x={p.x - boxW / 2}
          y={p.y - boxH / 2}
          width={boxW}
          height={boxH}
          rx={6}
          {...SHAPE}
        />
        {part.name && inShape(part.name, p.x, p.y, boxW, 12, boxH)}
      </Fragment>
    );
    anchors.push({
      id: part.id,
      x: p.x,
      y: p.y,
      left: p.x - boxW / 2,
      right: p.x + boxW / 2,
    });
  });

  return { body: <>{body}</>, anchors, height: cy + R + boxH / 2 + PAD };
}

// ---------------------------------------------------------------------------
// Layout: tree — a classification.
//
// "Dung Beetle Types": a root splitting into named groups. Depth comes from
// `parent`, so the model states only what descends from what.
// ---------------------------------------------------------------------------

function tree(visual: VisualDiagram): Drawn {
  const parts = visual.parts ?? [];
  const byId = new Map(parts.map((p) => [p.id, p]));
  const depth = (p: VisualDiagramPart, guard = 0): number => {
    const parent = p.parent ? byId.get(p.parent) : undefined;
    if (!parent || guard > 6) return 0;
    return 1 + depth(parent, guard + 1);
  };

  const levels: VisualDiagramPart[][] = [];
  for (const part of parts) {
    const d = depth(part);
    (levels[d] ??= []).push(part);
  }

  // Order each level so a node sits under its own parent. Listed in whatever
  // order the model wrote them, siblings from different parents interleave and
  // the connectors cross — the figure then shows the wrong thing descending
  // from the wrong group, which on a classification diagram is the whole
  // content of the question.
  for (let d = 1; d < levels.length; d++) {
    const above = levels[d - 1] ?? [];
    const rank = new Map(above.map((p, i) => [p.id, i]));
    levels[d] = levels[d].map((p, i) => ({ p, i })).sort(
      (a, b) =>
        (rank.get(a.p.parent ?? "") ?? 99) - (rank.get(b.p.parent ?? "") ?? 99) ||
        a.i - b.i
    ).map((x) => x.p);
  }

  const rowH = 78;
  const widest = Math.max(1, ...levels.map((r) => r.length));
  const boxH = 46;
  const body: ReactNode[] = [];
  const anchors: Anchor[] = [];
  const pos = new Map<string, { x: number; y: number }>();

  // A tree prints its text inside the nodes, so it may use the gutters — but
  // only when it carries no callouts, for the reason `layers` documents: the
  // callout columns are measured from the global GUTTER, so a tree that took
  // the extra width AND had a callout printed the two on top of each other.
  // The box also has to shrink to whatever the widest level leaves it: at a
  // fixed width, four siblings on one row simply overlapped each other.
  const span =
    (visual.labels ?? []).length === 0 ? DRAW_W + GUTTER : DRAW_W;
  const boxW = Math.max(72, Math.min(128, span / (widest + 1) - 8));

  levels.forEach((row, d) => {
    const y = TITLE_H + 14 + d * rowH;
    const left = (W - span) / 2;
    row.forEach((part, i) => {
      const x = left + (span / (row.length + 1)) * (i + 1);
      pos.set(part.id, { x, y });
      anchors.push({
        id: part.id,
        x,
        y,
        left: x - boxW / 2,
        right: x + boxW / 2,
      });
    });
  });

  // Connectors before boxes, for the same paper-fill reason as the cycle.
  for (const part of parts) {
    const me = pos.get(part.id);
    const up = part.parent ? pos.get(part.parent) : undefined;
    if (!me || !up) continue;
    const mid = (up.y + boxH / 2 + (me.y - boxH / 2)) / 2;
    body.push(
      <polyline
        key={`edge-${part.id}`}
        points={`${up.x},${up.y + boxH / 2} ${up.x},${mid} ${me.x},${mid} ${me.x},${me.y - boxH / 2}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.4}
      />
    );
  }

  for (const part of parts) {
    const p = pos.get(part.id);
    if (!p) continue;
    body.push(
      <Fragment key={part.id}>
        <rect
          x={p.x - boxW / 2}
          y={p.y - boxH / 2}
          width={boxW}
          height={boxH}
          rx={4}
          {...SHAPE}
        />
        {part.name && inShape(part.name, p.x, p.y, boxW, 12)}
      </Fragment>
    );
  }

  return {
    body: <>{body}</>,
    anchors,
    height: TITLE_H + 14 + Math.max(levels.length, 1) * rowH + PAD,
  };
}

// ---------------------------------------------------------------------------
// Layout: panel — the front of a device.
//
// "Water Heater": electricity indicator, on/off switch, reset button, time
// control, warning indicator. Controls sit on a drawn face in reading order;
// which control is which is exactly what the recording tells the student, so
// the callouts carry the numbers and the face carries the shapes.
// ---------------------------------------------------------------------------

function panel(visual: VisualDiagram): Drawn {
  const parts = (visual.parts ?? []).slice(0, 10);
  // A panel prints its numbers ON the face, directly under each control, and
  // returns NO anchors so the shared gutter placement finds nothing to draw.
  // Leaders are wrong here: the controls sit in a grid, so every leader from a
  // side gutter has to cross the controls between it and its own, and the
  // student cannot tell which one it means. Cambridge numbers them in place.
  const caption = new Map<string, string>();
  for (const label of visual.labels ?? []) {
    if (label.text) caption.set(label.at, label.text);
  }
  const cols = Math.min(parts.length > 6 ? 4 : 3, Math.max(parts.length, 1));
  const rows = Math.ceil(parts.length / cols) || 1;
  const cellW = DRAW_W / cols;
  const cellH = 88;
  const faceY = TITLE_H + 10;
  const faceH = rows * cellH + 24;

  const body: ReactNode[] = [
    <rect
      key="face"
      x={DRAW_L}
      y={faceY}
      width={DRAW_W}
      height={faceH}
      rx={12}
      {...SHAPE}
    />,
  ];
  const anchors: Anchor[] = [];

  parts.forEach((part, i) => {
    const r = Math.floor(i / cols);
    const c = i % cols;
    const x = DRAW_L + cellW * c + cellW / 2;
    const y = faceY + 12 + cellH * r + cellH / 2 - 8;
    body.push(<Fragment key={part.id}>{drawControl(part, x, y)}</Fragment>);
    const printed = caption.get(part.id) || part.name || "";
    if (printed) {
      body.push(
        <Fragment key={`${part.id}-name`}>
          {inShape(printed, x, y + 30, cellW - 10, 11)}
        </Fragment>
      );
    }
  });

  return { body: <>{body}</>, anchors, height: faceY + faceH + PAD };
}

function drawControl(part: VisualDiagramPart, x: number, y: number): ReactNode {
  switch (part.form) {
    case "dial":
      return (
        <>
          <circle cx={x} cy={y} r={18} {...SHAPE} />
          <line
            x1={x}
            y1={y}
            x2={x + 11}
            y2={y - 11}
            stroke="currentColor"
            strokeWidth={2}
          />
        </>
      );
    case "gauge":
      return (
        <>
          <path
            d={`M${x - 20},${y + 6} A20,20 0 0 1 ${x + 20},${y + 6}`}
            {...SHAPE}
          />
          <line
            x1={x}
            y1={y + 6}
            x2={x + 9}
            y2={y - 9}
            stroke="currentColor"
            strokeWidth={2}
          />
        </>
      );
    case "switch":
      return (
        <>
          <rect x={x - 20} y={y - 11} width={40} height={22} rx={11} {...SHAPE} />
          <circle cx={x + 9} cy={y} r={7.5} fill="currentColor" />
        </>
      );
    case "light":
      return (
        <>
          <circle cx={x} cy={y} r={10} {...SHAPE} />
          <circle cx={x} cy={y} r={4.5} fill="currentColor" opacity={0.6} />
        </>
      );
    case "display":
      return <rect x={x - 30} y={y - 14} width={60} height={28} rx={3} {...SHAPE} />;
    case "slot":
      return <rect x={x - 26} y={y - 5} width={52} height={10} rx={5} {...SHAPE} />;
    default:
      return (
        <>
          <circle cx={x} cy={y} r={15} {...SHAPE} />
          <circle
            cx={x}
            cy={y}
            r={9}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.1}
            opacity={0.6}
          />
        </>
      );
  }
}

export { hasGap };
