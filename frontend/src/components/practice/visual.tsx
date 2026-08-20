"use client";

import type { ReactNode } from "react";
import { API_URL } from "@/lib/api";
import type {
  Visual,
  VisualChart,
  VisualChartSeries,
  VisualMap,
  VisualPlan,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function Visuals({
  visual,
  visuals,
  className,
}: {
  visual?: Visual;
  visuals?: Visual[];
  className?: string;
}) {
  const list = visuals && visuals.length > 0 ? visuals : visual ? [visual] : [];
  if (list.length === 0) return null;
  return (
    <div className={cn("space-y-3", className)}>
      {list.map((v, i) => (
        <VisualBlock key={i} visual={v} />
      ))}
    </div>
  );
}

function resolveSrc(url: string): string {
  if (/^(https?:)?\/\//i.test(url) || url.startsWith("data:")) return url;
  if (url.startsWith("/")) return `${API_URL}${url}`;
  return `${API_URL}/${url}`;
}

export function VisualBlock({
  visual,
  className,
}: {
  visual: Visual;
  className?: string;
}) {
  if (visual.kind === "image") {
    return (
      <figure
        className={cn(
          "glass overflow-hidden rounded-[20px] p-3 shadow-soft",
          className
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={resolveSrc(visual.url)}
          alt={visual.alt}
          className="mx-auto max-h-[480px] w-full rounded-xl object-contain"
        />
        {visual.caption && (
          <figcaption className="mt-2 text-center text-xs text-muted-foreground">
            {visual.caption}
          </figcaption>
        )}
      </figure>
    );
  }
  if (visual.kind === "plan") {
    return <PlanBlock visual={visual} className={className} />;
  }
  if (visual.kind === "map") {
    return <MapBlock visual={visual} className={className} />;
  }
  return <ChartBlock visual={visual} className={className} />;
}

// ---------------------------------------------------------------------------
// Floor plan renderer — the grid carries only *which room is where*, so the
// geometry is derived here: cells holding the same value merge into one room,
// which makes shared walls and non-overlapping rooms structural rather than
// something the generator has to get right.

type PlanCell = { r: number; c: number };
type PlanRegion = { value: string; cells: PlanCell[] };

const PLAN_CELL = 46;
const PLAN_CHAR_W = 5.9;

function PlanBlock({ visual, className }: { visual: VisualPlan; className?: string }) {
  const raw = Array.isArray(visual.grid) ? visual.grid : [];
  const rows = raw.length;
  const cols = raw.reduce(
    (m, row) => Math.max(m, Array.isArray(row) ? row.length : 0),
    0
  );
  if (rows === 0 || cols === 0) return null;

  const grid: string[][] = Array.from({ length: rows }, (_, r) =>
    Array.from({ length: cols }, (_, c) => {
      const v = raw[r]?.[c];
      return typeof v === "string" ? v.trim() : "";
    })
  );

  const entrance = planEntrance(visual.entrance, grid, rows, cols);

  // The entrance label hangs outside the building, so its side needs room for
  // the whole caption rather than the default margin.
  const base = 28;
  const reach = entrance ? entrance.label.length * PLAN_CHAR_W + 46 : 0;
  const side = entrance?.side;
  const padL = base + (side === "left" ? reach : 0);
  const padR = base + (side === "right" ? reach : 0);
  const padT = base + (side === "top" ? 48 : 0);
  const padB = base + (side === "bottom" ? 48 : 0);

  const width = cols * PLAN_CELL + padL + padR;
  const height = rows * PLAN_CELL + padT + padB;
  const gx = (c: number) => padL + c * PLAN_CELL;
  const gy = (r: number) => padT + r * PLAN_CELL;

  const regions = planRegions(grid, rows, cols);
  const ids = Array.from({ length: rows }, () => new Array<number>(cols).fill(-1));
  regions.forEach((region, i) => {
    for (const cellPos of region.cells) ids[cellPos.r][cellPos.c] = i;
  });
  const walls = planWalls(regions, ids, rows, cols, padL, padT, entrance?.key);

  return (
    <figure
      className={cn("glass rounded-[20px] p-4 shadow-soft", className)}
      aria-label={`Plan: ${visual.title}`}
    >
      <figcaption className="mb-3 text-sm font-medium">{visual.title}</figcaption>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="mx-auto w-full max-w-[600px]"
          role="img"
          preserveAspectRatio="xMidYMid meet"
        >
          {regions.map((region, ri) => {
            const corridor = isCorridorValue(region.value);
            return (
              <g key={`f${ri}`}>
                {region.cells.map((cellPos, ci) => (
                  <rect
                    key={ci}
                    x={gx(cellPos.c)}
                    y={gy(cellPos.r)}
                    width={PLAN_CELL}
                    height={PLAN_CELL}
                    fill={corridor ? "currentColor" : "#5b5ceb"}
                    fillOpacity={corridor ? 0.05 : 0.08}
                  />
                ))}
              </g>
            );
          })}

          {walls.map((wall, wi) => (
            <line
              key={`w${wi}`}
              x1={wall.x1}
              y1={wall.y1}
              x2={wall.x2}
              y2={wall.y2}
              stroke="currentColor"
              strokeOpacity={wall.outer ? 0.75 : 0.45}
              strokeWidth={wall.outer ? 3.5 : 2}
              strokeLinecap="square"
            />
          ))}

          {regions.map((region, ri) => (
            <PlanRegionLabel key={`l${ri}`} region={region} gx={gx} gy={gy} />
          ))}

          {entrance && (
            <PlanEntranceMark
              {...planEntrancePoint(entrance, rows, cols, gx, gy)}
              label={entrance.label}
            />
          )}
        </svg>
      </div>
    </figure>
  );
}

function isCorridorValue(value: string): boolean {
  return value.toLowerCase() === "corridor";
}

function planRegions(grid: string[][], rows: number, cols: number): PlanRegion[] {
  const seen = Array.from({ length: rows }, () => new Array<boolean>(cols).fill(false));
  const out: PlanRegion[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const value = grid[r][c];
      if (seen[r][c] || !value) continue;
      const cells: PlanCell[] = [];
      const stack: PlanCell[] = [{ r, c }];
      seen[r][c] = true;
      while (stack.length > 0) {
        const cur = stack.pop() as PlanCell;
        cells.push(cur);
        const around: PlanCell[] = [
          { r: cur.r - 1, c: cur.c },
          { r: cur.r + 1, c: cur.c },
          { r: cur.r, c: cur.c - 1 },
          { r: cur.r, c: cur.c + 1 },
        ];
        for (const next of around) {
          if (next.r < 0 || next.r >= rows || next.c < 0 || next.c >= cols) continue;
          if (seen[next.r][next.c] || grid[next.r][next.c] !== value) continue;
          seen[next.r][next.c] = true;
          stack.push(next);
        }
      }
      out.push({ value, cells });
    }
  }
  return out;
}

type PlanWall = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  outer: boolean;
};

type PlanRun = {
  orient: "v" | "h";
  fixed: number;
  from: number;
  to: number;
  aId: number;
  bId: number;
};

const PLAN_DOOR = 24;

// Every boundary is visited exactly once — vertical edges by their left/right
// pair, horizontal edges by their top/bottom pair — so a wall between two rooms
// is drawn once and belongs to both of them. Collinear edges dividing the same
// two rooms then merge into a single run, and each room gets exactly one
// doorway, cut into its longest wall facing a corridor.
function planWalls(
  regions: PlanRegion[],
  ids: number[][],
  rows: number,
  cols: number,
  padX: number,
  padY: number,
  skipKey?: string
): PlanWall[] {
  const idAt = (r: number, c: number) =>
    r < 0 || r >= rows || c < 0 || c >= cols ? -1 : ids[r][c];

  const grouped = new Map<string, PlanRun[]>();
  const add = (
    orient: "v" | "h",
    fixed: number,
    start: number,
    aId: number,
    bId: number
  ) => {
    const key = `${orient}:${fixed}:${aId}:${bId}`;
    const list = grouped.get(key) ?? [];
    list.push({ orient, fixed, from: start, to: start + 1, aId, bId });
    grouped.set(key, list);
  };

  for (let c = 0; c <= cols; c++) {
    for (let r = 0; r < rows; r++) {
      const a = idAt(r, c - 1);
      const b = idAt(r, c);
      if (a !== b && `v:${c}:${r}` !== skipKey) add("v", c, r, a, b);
    }
  }
  for (let r = 0; r <= rows; r++) {
    for (let c = 0; c < cols; c++) {
      const a = idAt(r - 1, c);
      const b = idAt(r, c);
      if (a !== b && `h:${r}:${c}` !== skipKey) add("h", r, c, a, b);
    }
  }

  const runs: PlanRun[] = [];
  for (const list of grouped.values()) {
    list.sort((p, q) => p.from - q.from);
    let cur = { ...list[0] };
    for (let i = 1; i < list.length; i++) {
      if (list[i].from === cur.to) cur.to = list[i].to;
      else {
        runs.push(cur);
        cur = { ...list[i] };
      }
    }
    runs.push(cur);
  }

  // One door per room, cut into its longest wall onto the corridor; a room the
  // plan never joined to the corridor falls back to its longest wall onto any
  // neighbour, so none is drawn sealed shut. A plan with no corridor at all is
  // a labelled diagram rather than a building — a cross-section through soil
  // has no doorways between its layers — so it keeps unbroken outlines.
  const isCorridorId = (id: number) => id >= 0 && isCorridorValue(regions[id].value);
  const onCorridor = new Map<number, PlanRun>();
  const onAnything = new Map<number, PlanRun>();
  const consider = (into: Map<number, PlanRun>, room: number, run: PlanRun) => {
    const best = into.get(room);
    if (!best || run.to - run.from > best.to - best.from) into.set(room, run);
  };
  for (const run of runs) {
    if (run.aId < 0 || run.bId < 0) continue;
    for (const [room, other] of [
      [run.aId, run.bId],
      [run.bId, run.aId],
    ]) {
      if (isCorridorId(room)) continue;
      consider(isCorridorId(other) ? onCorridor : onAnything, room, run);
    }
  }
  const doors = new Set<PlanRun>();
  if (onCorridor.size > 0)
    for (let id = 0; id < regions.length; id++) {
      if (isCorridorId(id)) continue;
      const run = onCorridor.get(id) ?? onAnything.get(id);
      if (run) doors.add(run);
    }

  const walls: PlanWall[] = [];
  for (const run of runs) emitWall(walls, run, doors.has(run), padX, padY);
  return walls;
}

function emitWall(
  walls: PlanWall[],
  run: PlanRun,
  door: boolean,
  padX: number,
  padY: number
): void {
  const vertical = run.orient === "v";
  const fixedPx = (vertical ? padX : padY) + run.fixed * PLAN_CELL;
  const lo = (vertical ? padY : padX) + run.from * PLAN_CELL;
  const hi = (vertical ? padY : padX) + run.to * PLAN_CELL;
  const outer = run.aId < 0 || run.bId < 0;
  const seg = (a: number, b: number) =>
    walls.push(
      vertical
        ? { x1: fixedPx, y1: a, x2: fixedPx, y2: b, outer }
        : { x1: a, y1: fixedPx, x2: b, y2: fixedPx, outer }
    );

  if (!door) {
    seg(lo, hi);
    return;
  }
  const gap = Math.min(PLAN_DOOR, (hi - lo) * 0.42);
  const mid = (lo + hi) / 2;
  seg(lo, mid - gap / 2);
  seg(mid + gap / 2, hi);
}

function PlanRegionLabel({
  region,
  gx,
  gy,
}: {
  region: PlanRegion;
  gx: (c: number) => number;
  gy: (r: number) => number;
}) {
  if (isCorridorValue(region.value)) return null;

  // Anchor on the region's widest row, so an L-shaped room labels inside
  // itself rather than in the notch of its bounding box. Ties go to the row
  // nearest the vertical middle.
  const byRow = new Map<number, number[]>();
  for (const cellPos of region.cells) {
    const list = byRow.get(cellPos.r) ?? [];
    list.push(cellPos.c);
    byRow.set(cellPos.r, list);
  }
  const rowsUsed = [...byRow.keys()].sort((a, b) => a - b);
  const midRow = (rowsUsed[0] + rowsUsed[rowsUsed.length - 1]) / 2;
  let anchorRow = rowsUsed[0];
  for (const r of rowsUsed) {
    const best = byRow.get(anchorRow) as number[];
    const list = byRow.get(r) as number[];
    if (
      list.length > best.length ||
      (list.length === best.length &&
        Math.abs(r - midRow) < Math.abs(anchorRow - midRow))
    )
      anchorRow = r;
  }
  const anchorCols = byRow.get(anchorRow) as number[];
  const minC = Math.min(...anchorCols);
  const maxC = Math.max(...anchorCols);

  const cx = (gx(minC) + gx(maxC + 1)) / 2;
  const cy = gy(anchorRow) + PLAN_CELL / 2;
  const boxW = (maxC - minC + 1) * PLAN_CELL;

  const blank = /^_+\s*(\d+)\s*_+$/.exec(region.value);
  if (blank) {
    return (
      <text
        x={cx}
        y={cy}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={13}
        fontWeight={600}
        fill="currentColor"
      >
        {`${blank[1]} ${"·".repeat(8)}`}
      </text>
    );
  }

  if (/^[A-Za-z]$/.test(region.value)) {
    return (
      <text
        x={cx}
        y={cy}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={20}
        fontWeight={700}
        fill="currentColor"
      >
        {region.value.toUpperCase()}
      </text>
    );
  }

  const lines = wrapPlanText(region.value, boxW - 8);
  const start = cy - ((lines.length - 1) * 13) / 2;
  return (
    <g>
      {lines.map((line, i) => (
        <text
          key={i}
          x={cx}
          y={start + i * 13}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={10.5}
          fill="currentColor"
          fillOpacity={0.85}
        >
          {line}
        </text>
      ))}
    </g>
  );
}

function wrapPlanText(text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const lines: string[] = [];
  let cur = words[0];
  for (let i = 1; i < words.length; i++) {
    const merged = `${cur} ${words[i]}`;
    if (merged.length * PLAN_CHAR_W <= maxWidth) cur = merged;
    else {
      lines.push(cur);
      cur = words[i];
    }
  }
  lines.push(cur);
  return lines;
}

type PlanEntrance = {
  key: string;
  side: "top" | "bottom" | "left" | "right";
  index: number;
  label: string;
};

function planEntrance(
  entrance: VisualPlan["entrance"],
  grid: string[][],
  rows: number,
  cols: number
): PlanEntrance | null {
  if (!entrance) return null;
  const side = entrance.side;
  if (side !== "top" && side !== "bottom" && side !== "left" && side !== "right")
    return null;

  const along = side === "top" || side === "bottom" ? cols : rows;
  const filled = (i: number) => {
    if (side === "top") return grid[0]?.[i];
    if (side === "bottom") return grid[rows - 1]?.[i];
    if (side === "left") return grid[i]?.[0];
    return grid[i]?.[cols - 1];
  };

  // Nearest position on that side that actually touches the building, so an
  // entrance nominated over empty margin still lands on a wall.
  const want = clamp(Math.round(entrance.index ?? Math.floor(along / 2)), 0, along - 1);
  let index = -1;
  for (let d = 0; d < along; d++) {
    for (const i of [want - d, want + d]) {
      if (i < 0 || i >= along || index >= 0) continue;
      if (filled(i)) index = i;
    }
    if (index >= 0) break;
  }
  if (index < 0) return null;

  const key =
    side === "top"
      ? `h:0:${index}`
      : side === "bottom"
        ? `h:${rows}:${index}`
        : side === "left"
          ? `v:0:${index}`
          : `v:${cols}:${index}`;

  return { key, side, index, label: entrance.label?.trim() || "Entrance" };
}

// Anchor on the outer wall, with (dx, dy) pointing into the building.
function planEntrancePoint(
  entrance: PlanEntrance,
  rows: number,
  cols: number,
  gx: (c: number) => number,
  gy: (r: number) => number
): { x: number; y: number; dx: number; dy: number } {
  const { side, index } = entrance;
  if (side === "top")
    return { x: gx(index) + PLAN_CELL / 2, y: gy(0), dx: 0, dy: 1 };
  if (side === "bottom")
    return { x: gx(index) + PLAN_CELL / 2, y: gy(rows), dx: 0, dy: -1 };
  if (side === "left")
    return { x: gx(0), y: gy(index) + PLAN_CELL / 2, dx: 1, dy: 0 };
  return { x: gx(cols), y: gy(index) + PLAN_CELL / 2, dx: -1, dy: 0 };
}

function PlanEntranceMark({
  x,
  y,
  dx,
  dy,
  label,
}: {
  x: number;
  y: number;
  dx: number;
  dy: number;
  label: string;
}) {
  return (
    <g>
      <line
        x1={x - dx * 26}
        y1={y - dy * 26}
        x2={x + dx * 8}
        y2={y + dy * 8}
        stroke="#5b5ceb"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
      <circle cx={x - dx * 26} cy={y - dy * 26} r={3.5} fill="#5b5ceb" />
      <text
        x={x - dx * 34}
        y={y - dy * 34}
        textAnchor={dx === 0 ? "middle" : dx > 0 ? "end" : "start"}
        dominantBaseline={dy === 0 ? "central" : dy > 0 ? "auto" : "hanging"}
        fontSize={11}
        fontWeight={600}
        fill="currentColor"
        fillOpacity={0.85}
      >
        {label}
      </text>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Map / plan renderer — draws IELTS map-labelling plans (lettered locations
// on a grid) as SVG. Coordinates are grid units with a bottom-left origin.

type LabelBox = { x: number; y: number; w: number; h: number };

function MapBlock({ visual, className }: { visual: VisualMap; className?: string }) {
  const gw = Math.max(4, Math.round(visual.width ?? 10));
  const gh = Math.max(4, Math.round(visual.height ?? 8));
  const cell = 52;
  const pad = 34;
  const width = gw * cell + pad * 2;
  const height = gh * cell + pad * 2;

  const px = (x: number) => pad + clamp(x, 0, gw) * cell;
  const py = (y: number) => pad + (gh - clamp(y, 0, gh)) * cell;

  const features = visual.features ?? [];
  const roomW = 44;
  const roomH = 36;

  // ---- collision-avoided text placement ---------------------------------
  // Reserve every room box and marker up front, then position each word label
  // in the first candidate slot that clears the reserved regions and other
  // labels. This keeps landmark and corridor labels from stacking on top of
  // each other (or of a room) the way plain fixed offsets did.
  const reserved: LabelBox[] = [];
  const CHAR_W = 6.3;
  const LINE_H = 15;

  for (const f of features) {
    const isLetter = !f.fixed && f.shape !== "point";
    if (isLetter) {
      reserved.push({ x: px(f.x) - roomW / 2, y: py(f.y) - roomH / 2, w: roomW, h: roomH });
    } else {
      reserved.push({ x: px(f.x) - 6, y: py(f.y) - 6, w: 12, h: 12 });
    }
  }

  const overlaps = (a: LabelBox, b: LabelBox) =>
    !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);

  const placeLabel = (cx: number, cy: number, text: string): LabelBox => {
    const w = text.length * CHAR_W + 12;
    const h = LINE_H;
    const candidates: Array<[number, number]> = [
      [cx - w / 2, cy - 20 - h],
      [cx - w / 2, cy + 12],
      [cx + 12, cy - h / 2],
      [cx - w - 12, cy - h / 2],
      [cx - w / 2, cy - 34 - h],
      [cx - w / 2, cy + 26],
    ];
    for (const [bx, by] of candidates) {
      const box = { x: bx, y: by, w, h };
      if (box.x < 3 || box.y < 3 || box.x + box.w > width - 3 || box.y + box.h > height - 3)
        continue;
      if (reserved.some((r) => overlaps(box, r))) continue;
      reserved.push(box);
      return box;
    }
    const box = {
      x: clamp(cx - w / 2, 3, width - w - 3),
      y: clamp(cy - 20 - h, 3, height - h - 3),
      w,
      h,
    };
    reserved.push(box);
    return box;
  };

  return (
    <figure
      className={cn("glass rounded-[20px] p-4 shadow-soft", className)}
      aria-label={`Map: ${visual.title}`}
    >
      <figcaption className="mb-3 text-sm font-medium">{visual.title}</figcaption>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="mx-auto w-full max-w-[560px]"
          role="img"
          preserveAspectRatio="xMidYMid meet"
        >
          {/* building outline */}
          <rect
            x={pad}
            y={pad}
            width={gw * cell}
            height={gh * cell}
            rx={10}
            fill="currentColor"
            fillOpacity={0.025}
            stroke="currentColor"
            strokeOpacity={0.28}
            strokeWidth={1.5}
          />
          {Array.from({ length: gw + 1 }).map((_, i) => (
            <line
              key={`v${i}`}
              x1={pad + i * cell}
              y1={pad}
              x2={pad + i * cell}
              y2={pad + gh * cell}
              stroke="currentColor"
              strokeOpacity={0.05}
            />
          ))}
          {Array.from({ length: gh + 1 }).map((_, i) => (
            <line
              key={`h${i}`}
              x1={pad}
              y1={pad + i * cell}
              x2={pad + gw * cell}
              y2={pad + i * cell}
              stroke="currentColor"
              strokeOpacity={0.05}
            />
          ))}

          {/* compass */}
          <g transform={`translate(${width - pad - 6}, ${pad + 14})`} aria-hidden>
            <line x1={0} y1={6} x2={0} y2={-8} stroke="currentColor" strokeOpacity={0.4} />
            <path d="M 0 -12 L 3 -6 L -3 -6 Z" fill="currentColor" fillOpacity={0.5} />
            <text x={0} y={18} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.5}>
              N
            </text>
          </g>

          {/* corridors / roads / rivers */}
          {(visual.paths ?? []).map((path, pi) => {
            const pts = (path.points ?? []).filter(
              (p) => Array.isArray(p) && p.length >= 2
            );
            if (pts.length < 2) return null;
            const d = pts
              .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p[0])} ${py(p[1])}`)
              .join(" ");
            return (
              <path
                key={`path${pi}`}
                d={d}
                fill="none"
                stroke="currentColor"
                strokeOpacity={0.18}
                strokeWidth={12}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}

          {/* rooms (lettered) + markers */}
          {features.map((f, fi) => {
            const cx = px(f.x);
            const cy = py(f.y);
            const isLetter = !f.fixed && f.shape !== "point";
            if (isLetter) {
              return (
                <g key={`r${fi}`}>
                  <rect
                    x={cx - roomW / 2}
                    y={cy - roomH / 2}
                    width={roomW}
                    height={roomH}
                    rx={7}
                    fill="#5b5ceb"
                    fillOpacity={0.13}
                    stroke="#5b5ceb"
                    strokeOpacity={0.55}
                    strokeWidth={1.5}
                  />
                  <text
                    x={cx}
                    y={cy}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={17}
                    fontWeight={700}
                    fill="currentColor"
                  >
                    {f.label}
                  </text>
                </g>
              );
            }
            return (
              <circle
                key={`m${fi}`}
                cx={cx}
                cy={cy}
                r={f.fixed ? 4 : 5}
                fill={f.fixed ? "#5b5ceb" : "#38bdf8"}
              />
            );
          })}

          {/* word labels for landmarks / points + path labels, placed last so
              they paint on top, each in a collision-free slot with a pill */}
          {features
            .filter((f) => f.fixed || f.shape === "point")
            .map((f, fi) => {
              const box = placeLabel(px(f.x), py(f.y), f.label);
              return <LabelPill key={`l${fi}`} box={box} text={f.label} strong />;
            })}
          {(visual.paths ?? []).map((path, pi) => {
            const pts = (path.points ?? []).filter(
              (p) => Array.isArray(p) && p.length >= 2
            );
            if (pts.length < 2 || !path.label) return null;
            const mid = pts[Math.floor(pts.length / 2)];
            const box = placeLabel(px(mid[0]), py(mid[1]), path.label);
            return <LabelPill key={`pl${pi}`} box={box} text={path.label} />;
          })}
        </svg>
      </div>
    </figure>
  );
}

function LabelPill({
  box,
  text,
  strong,
}: {
  box: LabelBox;
  text: string;
  strong?: boolean;
}) {
  return (
    <g>
      <rect
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={5}
        className="fill-background"
        fillOpacity={0.85}
      />
      <text
        x={box.x + box.w / 2}
        y={box.y + box.h / 2}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={11}
        fontWeight={strong ? 600 : 400}
        fill="currentColor"
        fillOpacity={strong ? 0.85 : 0.6}
      >
        {text}
      </text>
    </g>
  );
}

function clamp(v: number, lo: number, hi: number): number {
  const n = typeof v === "number" && Number.isFinite(v) ? v : lo;
  return Math.min(hi, Math.max(lo, n));
}

// ---------------------------------------------------------------------------
// Chart renderers

const SERIES_COLORS = [
  "#5b5ceb", // primary
  "#38bdf8", // accent
  "#f59e0b", // warning
  "#22c55e", // success
  "#ef4444", // danger
  "#7c4dff", // secondary
];

function ChartBlock({
  visual,
  className,
}: {
  visual: VisualChart;
  className?: string;
}) {
  return (
    <figure
      className={cn("glass rounded-[20px] p-4 shadow-soft", className)}
      aria-label={`${visual.chart_type} chart: ${visual.title}`}
    >
      <figcaption className="mb-3 text-sm font-medium">{visual.title}</figcaption>
      {visual.chart_type === "bar" && <BarChart visual={visual} />}
      {visual.chart_type === "line" && <LineChart visual={visual} />}
      {visual.chart_type === "pie" && <PieChart visual={visual} />}
      {visual.chart_type === "table" && <ChartTable visual={visual} />}
    </figure>
  );
}

type NumericPoint = { category: string; value: number };

function toNumericPoints(series: VisualChartSeries): NumericPoint[] {
  return series.data.map((point, i) => {
    if (Array.isArray(point)) {
      const v = typeof point[1] === "number" ? point[1] : Number(point[1]) || 0;
      return { category: String(point[0]), value: v };
    }
    return { category: String(i + 1), value: typeof point === "number" ? point : 0 };
  });
}

function unionCategories(series: VisualChartSeries[]): string[] {
  const seen: string[] = [];
  const set = new Set<string>();
  for (const s of series) {
    for (const p of toNumericPoints(s)) {
      if (!set.has(p.category)) {
        set.add(p.category);
        seen.push(p.category);
      }
    }
  }
  return seen;
}

function niceMax(raw: number): number {
  if (raw <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const scaled = raw / pow;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * pow;
}

function BarChart({ visual }: { visual: VisualChart }) {
  const width = 640;
  const height = 320;
  const padding = { top: 16, right: 16, bottom: 44, left: 44 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const categories = unionCategories(visual.series);
  const seriesByCategory = visual.series.map(toNumericPoints);
  const rawMax = Math.max(
    ...seriesByCategory.flatMap((s) => s.map((p) => p.value)),
    0
  );
  const yMax = niceMax(rawMax);
  const ticks = 4;

  const groupW = chartW / Math.max(categories.length, 1);
  const gap = Math.min(12, groupW * 0.15);
  const barW = Math.max(2, (groupW - gap) / Math.max(visual.series.length, 1));

  return (
    <ChartFrame
      width={width}
      height={height}
      padding={padding}
      yMax={yMax}
      yTicks={ticks}
      xLabel={visual.x_label}
      yLabel={visual.y_label}
      categories={categories}
    >
      {visual.series.map((s, si) => {
        const points = toNumericPoints(s);
        const lookup = new Map(points.map((p) => [p.category, p.value]));
        return (
          <g key={si} fill={SERIES_COLORS[si % SERIES_COLORS.length]}>
            {categories.map((cat, ci) => {
              const value = lookup.get(cat) ?? 0;
              const h = (value / yMax) * chartH;
              const x = padding.left + ci * groupW + gap / 2 + si * barW;
              const y = padding.top + chartH - h;
              return (
                <rect
                  key={ci}
                  x={x}
                  y={y}
                  width={barW - 1}
                  height={Math.max(0, h)}
                  rx={2}
                >
                  <title>
                    {s.name}: {cat} = {value}
                  </title>
                </rect>
              );
            })}
          </g>
        );
      })}
      <Legend series={visual.series} />
    </ChartFrame>
  );
}

function LineChart({ visual }: { visual: VisualChart }) {
  const width = 640;
  const height = 320;
  const padding = { top: 16, right: 16, bottom: 44, left: 44 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const categories = unionCategories(visual.series);
  const rawMax = Math.max(
    ...visual.series.flatMap((s) => toNumericPoints(s).map((p) => p.value)),
    0
  );
  const yMax = niceMax(rawMax);
  const step = categories.length > 1 ? chartW / (categories.length - 1) : 0;

  return (
    <ChartFrame
      width={width}
      height={height}
      padding={padding}
      yMax={yMax}
      yTicks={4}
      xLabel={visual.x_label}
      yLabel={visual.y_label}
      categories={categories}
    >
      {visual.series.map((s, si) => {
        const color = SERIES_COLORS[si % SERIES_COLORS.length];
        const points = toNumericPoints(s);
        const lookup = new Map(points.map((p) => [p.category, p.value]));
        const coords = categories.map((cat, ci) => {
          const value = lookup.get(cat) ?? 0;
          const x = padding.left + ci * step + (categories.length === 1 ? chartW / 2 : 0);
          const y = padding.top + chartH - (value / yMax) * chartH;
          return { x, y, cat, value };
        });
        const d = coords.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
        return (
          <g key={si}>
            <path d={d} fill="none" stroke={color} strokeWidth={2} />
            {coords.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={3} fill={color}>
                <title>
                  {s.name}: {p.cat} = {p.value}
                </title>
              </circle>
            ))}
          </g>
        );
      })}
      <Legend series={visual.series} />
    </ChartFrame>
  );
}

function ChartFrame({
  width,
  height,
  padding,
  yMax,
  yTicks,
  xLabel,
  yLabel,
  categories,
  children,
}: {
  width: number;
  height: number;
  padding: { top: number; right: number; bottom: number; left: number };
  yMax: number;
  yTicks: number;
  xLabel?: string;
  yLabel?: string;
  categories: string[];
  children: ReactNode;
}) {
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => (yMax / yTicks) * i);
  const step = categories.length > 1 ? chartW / (categories.length - 1) : 0;
  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        preserveAspectRatio="xMidYMid meet"
      >
        {ticks.map((t, i) => {
          const y = padding.top + chartH - (t / yMax) * chartH;
          return (
            <g key={i}>
              <line
                x1={padding.left}
                x2={padding.left + chartW}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.12}
              />
              <text
                x={padding.left - 6}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={10}
                fill="currentColor"
                fillOpacity={0.6}
              >
                {formatTick(t)}
              </text>
            </g>
          );
        })}
        <line
          x1={padding.left}
          x2={padding.left + chartW}
          y1={padding.top + chartH}
          y2={padding.top + chartH}
          stroke="currentColor"
          strokeOpacity={0.35}
        />
        {categories.map((cat, ci) => {
          const cx =
            categories.length === 1
              ? padding.left + chartW / 2
              : padding.left + ci * step;
          return (
            <text
              key={ci}
              x={cx}
              y={padding.top + chartH + 14}
              textAnchor="middle"
              fontSize={10}
              fill="currentColor"
              fillOpacity={0.7}
            >
              {cat}
            </text>
          );
        })}
        {xLabel && (
          <text
            x={padding.left + chartW / 2}
            y={height - 4}
            textAnchor="middle"
            fontSize={10}
            fill="currentColor"
            fillOpacity={0.6}
          >
            {xLabel}
          </text>
        )}
        {yLabel && (
          <text
            x={12}
            y={padding.top + chartH / 2}
            textAnchor="middle"
            fontSize={10}
            fill="currentColor"
            fillOpacity={0.6}
            transform={`rotate(-90 12 ${padding.top + chartH / 2})`}
          >
            {yLabel}
          </text>
        )}
        {children}
      </svg>
    </div>
  );
}

function formatTick(n: number): string {
  if (n === 0) return "0";
  const abs = Math.abs(n);
  if (abs >= 1000) return `${(n / 1000).toFixed(abs >= 10000 ? 0 : 1)}k`;
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

function Legend({ series }: { series: VisualChartSeries[] }) {
  if (series.length <= 1) return null;
  return (
    <g>
      {series.map((s, i) => (
        <g key={i} transform={`translate(${60 + i * 140}, 8)`}>
          <rect
            x={0}
            y={-6}
            width={10}
            height={10}
            rx={2}
            fill={SERIES_COLORS[i % SERIES_COLORS.length]}
          />
          <text
            x={16}
            y={2}
            fontSize={10}
            fill="currentColor"
            fillOpacity={0.75}
          >
            {s.name}
          </text>
        </g>
      ))}
    </g>
  );
}

function PieChart({ visual }: { visual: VisualChart }) {
  const width = 480;
  const height = 300;
  const cx = 150;
  const cy = height / 2;
  const r = 110;

  const slices = toNumericPoints(visual.series[0] ?? { name: "", data: [] });
  const total = slices.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  if (total <= 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Pie chart has no positive values to render.
      </p>
    );
  }

  const fractions = slices.map((s) => Math.max(0, s.value) / total);
  const cumulative = fractions.reduce<number[]>((acc, f, i) => {
    acc.push((acc[i - 1] ?? 0) + f);
    return acc;
  }, []);
  const arcs = slices.map((slice, i) => {
    const frac = fractions[i];
    const startFrac = (cumulative[i - 1] ?? 0);
    const start = -Math.PI / 2 + startFrac * Math.PI * 2;
    const end = -Math.PI / 2 + cumulative[i] * Math.PI * 2;
    const large = frac > 0.5 ? 1 : 0;
    const x1 = cx + r * Math.cos(start);
    const y1 = cy + r * Math.sin(start);
    const x2 = cx + r * Math.cos(end);
    const y2 = cy + r * Math.sin(end);
    const d =
      slices.length === 1
        ? `M ${cx - r} ${cy} A ${r} ${r} 0 1 1 ${cx + r} ${cy} A ${r} ${r} 0 1 1 ${cx - r} ${cy} Z`
        : `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
    return {
      d,
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      label: slice.category,
      value: slice.value,
      pct: frac * 100,
    };
  });

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full max-w-[520px]"
        role="img"
        preserveAspectRatio="xMidYMid meet"
      >
        {arcs.map((a, i) => (
          <path key={i} d={a.d} fill={a.color}>
            <title>
              {a.label}: {a.value} ({a.pct.toFixed(1)}%)
            </title>
          </path>
        ))}
        {arcs.map((a, i) => (
          <g key={`legend-${i}`} transform={`translate(300, ${40 + i * 22})`}>
            <rect x={0} y={-8} width={12} height={12} rx={2} fill={a.color} />
            <text
              x={18}
              y={2}
              fontSize={11}
              fill="currentColor"
              fillOpacity={0.8}
            >
              {a.label} ({a.pct.toFixed(0)}%)
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table renderer — handles both plain data tables and Listening completion
// tables where cells are `"__<n>__"` placeholders for question N.

const BLANK_RE = /^__(\d+)__$/;

function ChartTable({ visual }: { visual: VisualChart }) {
  let headers = deriveHeaders(visual);
  let cornerLabel = "";
  // The model often emits the row category as BOTH the row name and the first
  // data column, so the table shows it twice ("Individual | Individual | …").
  // If a leading column merely repeats every row's name, fold it into the
  // corner header instead of rendering a redundant duplicate column.
  if (headers.length >= 2) {
    const h0 = headers[0];
    const redundant = visual.series.every((row) => {
      const name = String(row.name).trim();
      return name !== "" && String(findCell(row, h0)).trim() === name;
    });
    if (redundant) {
      cornerLabel = h0;
      headers = headers.slice(1);
    }
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 font-medium">{cornerLabel}</th>
            {headers.map((h) => (
              <th key={h} className="px-2 py-1.5">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visual.series.map((row, ri) => (
            <tr key={ri} className="border-t border-border/60">
              <td className="px-2 py-1.5 font-medium">{row.name}</td>
              {headers.map((h) => {
                const cell = findCell(row, h);
                return (
                  <td key={h} className="px-2 py-1.5 tabular-nums">
                    {renderCell(cell)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function deriveHeaders(visual: VisualChart): string[] {
  const first = visual.series[0];
  if (first) {
    const heads: string[] = [];
    const set = new Set<string>();
    for (const point of first.data) {
      if (Array.isArray(point)) {
        const h = String(point[0]);
        if (!set.has(h)) {
          set.add(h);
          heads.push(h);
        }
      }
    }
    if (heads.length > 0) return heads;
  }
  if (visual.x_label) return visual.x_label.split(",").map((s) => s.trim());
  return [visual.y_label ?? "Value"];
}

function findCell(row: VisualChartSeries, header: string): unknown {
  for (const point of row.data) {
    if (Array.isArray(point) && String(point[0]) === header) return point[1];
  }
  return "";
}

function renderCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  const str = String(value);
  const blank = BLANK_RE.exec(str);
  if (blank) {
    return (
      <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        Q{blank[1]}
      </span>
    );
  }
  return str;
}
