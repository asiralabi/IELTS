"use client";

import { Fragment } from "react";
import type { ReactNode } from "react";
import type {
  VisualDiagram,
  VisualDiagramLabel,
  VisualDiagramPart,
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
const W = 720;
const PAD = 16;
/** Callout gutters. A label column has to hold "Thread guide" without wrapping. */
const GUTTER = 168;
const DRAW_L = PAD + GUTTER;
const DRAW_R = W - PAD - GUTTER;
const DRAW_W = DRAW_R - DRAW_L;
const CX = (DRAW_L + DRAW_R) / 2;

/** Narrowest the figure is allowed to render before it scrolls instead. */
const MIN_W = 620;

const TITLE_H = 34;
/** Vertical room a callout needs before it collides with the one above it. */
const LABEL_GAP = 30;

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
}: {
  visual: VisualDiagram;
  className?: string;
}) {
  const layout = visual.layout ?? "apparatus";
  const drawn =
    layout === "layers"
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
      <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        style={{ minWidth: MIN_W }}
        className="mx-auto block w-full max-w-[720px] text-foreground"
        role="img"
        aria-label={visual.title || "Labelled diagram"}
      >
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
        {drawn.body}
        {callouts.body}
      </svg>
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
    out.push(
      <Fragment key={`${m.index}-${m[1]}`}>
        <tspan fontWeight={700}>{m[1]}</tspan>
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

function inShape(raw: string, x: number, y: number, width: number, size = 13) {
  const lines = wrap(raw, width - 12, size);
  const top = y - ((lines.length - 1) * (size + 3)) / 2;
  return lines.map((line, i) => (
    <Fragment key={i}>
      {text(gapText(line), x, top + i * (size + 3), { size })}
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
    if (label.side === "left" || label.side === "right") side = label.side;
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
    const items = [...sides[side]].sort((p, q) => p.a.y - q.a.y);
    // Spread: start at each label's own height, then walk down enforcing the
    // minimum spacing. Anything pushed past the drawing extends the canvas.
    const ys: number[] = [];
    let prev = -Infinity;
    for (const item of items) {
      const y = Math.max(item.a.y, prev + LABEL_GAP, TITLE_H);
      ys.push(y);
      prev = y;
    }
    items.forEach((item, i) => {
      const y = ys[i];
      lowest = Math.max(lowest, y + 14);
      const tx = side === "left" ? PAD + GUTTER - 26 : W - PAD - GUTTER + 26;
      const edge = side === "left" ? item.a.left : item.a.right;
      body.push(
        <Fragment key={`${side}-${i}-${item.label.at}`}>
          {/* Leader: out of the label horizontally, then to the part's edge.
              Two segments rather than one diagonal, because a diagonal across
              a drawing reads as part of the machine. */}
          <polyline
            points={`${tx},${y} ${side === "left" ? tx + 14 : tx - 14},${y} ${edge},${item.a.y}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.75"
          />
          <circle cx={edge} cy={item.a.y} r="2.4" fill="currentColor" />
          {text(gapText(item.label.text), tx, y, {
            anchor: side === "left" ? "end" : "start",
            size: 13,
          })}
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
  rotor: 0.72,
  disc: 1,
  valve: 1,
  coil: 1,
};

function inkEdges(form: string, b: Box): { left: number; right: number } {
  const f = INK[form] ?? 1;
  const half = (b.w * f) / 2;
  const cx = b.x + b.w / 2;
  return { left: cx - half, right: cx + half };
}

function apparatus(visual: VisualDiagram): {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
} {
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
  b: Box
): { ink: ReactNode; text: ReactNode } {
  const cx = b.x + b.w / 2;
  const cy = b.y + b.h / 2;
  const name = part.name?.trim();
  const inside = name ? inShape(name, cx, cy, b.w) : null;
  const below = (dy: number) =>
    name ? text(gapText(name), cx, b.y + b.h + dy, { size: 12 }) : null;

  switch (part.form) {
    case "ground":
      return {
        ink: (
          <>
            <rect {...rectOf(b)} fill="url(#dg-hatch)" stroke="none" />
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
        text: name ? text(gapText(name), cx, b.y - 9, { size: 12 }) : null,
      };
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
        text: inside,
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
        text: inside,
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
        text: name ? inShape(name, cx, cy + b.w / 4, b.w, 11) : null,
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
    case "pipe":
      return {
        ink: <rect {...rectOf(b)} {...SHAPE} />,
        text: name
          ? text(gapText(name), cx + b.w, cy, { size: 12, anchor: "start" })
          : null,
      };
    case "platform":
      return { ink: <rect {...rectOf(b)} {...SHAPE} />, text: inside };
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
        text: inside,
      };
    default:
      return { ink: <rect {...rectOf(b)} rx={3} {...SHAPE} />, text: inside };
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

/** A strata section is drawn wider than the gutters allow, because its text
 * sits INSIDE the bands rather than out at the end of leaders. 100px each side
 * still holds the one or two callouts a section carries. */
const LAYER_L = PAD + 100;
const LAYER_R = W - PAD - 100;
const LAYER_W = LAYER_R - LAYER_L;

function layers(visual: VisualDiagram): {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
} {
  const parts = visual.parts ?? [];
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
        {part.name && inShape(part.name, CX, y + bandH / 2, LAYER_W - 40)}
      </Fragment>
    );
    anchors.push({
      id: part.id,
      x: CX,
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

function cycle(visual: VisualDiagram): {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
} {
  const parts = (visual.parts ?? []).slice(0, 8);
  const n = Math.max(parts.length, 1);
  const boxW = 124;
  const boxH = 52;
  // Chord between neighbouring stages has to hold a box plus the arrow drawn
  // between them: 2R.sin(pi/n) >= boxW + gap. Sized off the circumference
  // instead, six boxes sat shoulder to shoulder and every arc was hidden
  // behind paper — only the two arrowheads in the vertical gaps survived.
  const R =
    n > 1
      ? Math.round(
          Math.min(210, Math.max(126, (boxW + 70) / (2 * Math.sin(Math.PI / n))))
        )
      : 126;
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
        {part.name && inShape(part.name, p.x, p.y, boxW, 12)}
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

function tree(visual: VisualDiagram): {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
} {
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

  // A tree prints its text inside the nodes, so it may use the gutters. The
  // box has to shrink to whatever the widest level leaves it: at a fixed
  // width, four siblings on one row simply overlapped each other.
  const span = DRAW_W + GUTTER;
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

function panel(visual: VisualDiagram): {
  body: ReactNode;
  anchors: Anchor[];
  height: number;
} {
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
