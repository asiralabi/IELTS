"use client";

import * as React from "react";
import { useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

/*
 * A split-flap departures board. Adapted from the 21st.dev "Split Flap
 * Display" idea, rebuilt so a cell re-renders once per flap rather than once
 * per animation phase: each flip is a CSS animation restarted by a key, and the
 * old and new characters are both rendered so the leaf has something to show
 * on either face.
 */

const FLAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const FLAP_MS = 70;

function Half({
  char,
  side,
  className,
  style,
}: {
  char: string;
  side: "top" | "bottom";
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <span
      style={style}
      className={cn(
        "absolute inset-x-0 h-1/2 overflow-hidden [backface-visibility:hidden]",
        side === "top" ? "top-0 rounded-t-[3px] bg-[#1d2722]" : "bottom-0 rounded-b-[3px] bg-[#19221e]",
        className
      )}
    >
      <span
        className={cn(
          "absolute inset-x-0 flex h-[200%] items-center justify-center",
          side === "top" ? "top-0" : "-top-full"
        )}
      >
        {char}
      </span>
    </span>
  );
}

function FlapCell({
  target,
  delay,
  tone,
}: {
  target: string;
  delay: number;
  tone: "plain" | "sun" | "green";
}) {
  const reduce = useReducedMotion();
  const [state, setState] = React.useState({ cur: target, prev: target, flip: 0 });

  React.useEffect(() => {
    if (reduce) {
      // Nothing to animate: land on the target in one step.
      const t = window.setTimeout(() => setState((s) => ({ cur: target, prev: s.cur, flip: s.flip })), 0);
      return () => window.clearTimeout(t);
    }
    let cancelled = false;
    const timers: number[] = [];
    // A few random flaps before landing, the way a real board shuffles past
    // letters on its way to the right one. Blanks stay blank.
    const steps = target === " " ? 1 : 2 + Math.floor(Math.random() * 4);
    for (let i = 1; i <= steps; i++) {
      timers.push(
        window.setTimeout(() => {
          if (cancelled) return;
          const next =
            i === steps ? target : FLAP_CHARS[Math.floor(Math.random() * FLAP_CHARS.length)];
          setState((s) => (s.cur === next ? s : { cur: next, prev: s.cur, flip: s.flip + 1 }));
        }, delay + i * FLAP_MS)
      );
    }
    return () => {
      cancelled = true;
      timers.forEach(window.clearTimeout);
    };
  }, [target, delay, reduce]);

  const color =
    tone === "sun" ? "text-[#f0806f]" : tone === "green" ? "text-[#8fd3ae]" : "text-[#efe9dc]";

  return (
    <span
      className={cn(
        "relative inline-block h-[28px] w-[18px] font-mono text-[15px] font-medium sm:h-[34px] sm:w-[22px] sm:text-[19px] lg:h-[40px] lg:w-[26px] lg:text-[23px]",
        color
      )}
      style={{ perspective: "220px" }}
    >
      <Half char={state.cur} side="top" />
      <Half char={state.prev} side="bottom" />
      {state.flip > 0 && !reduce && (
        <React.Fragment key={state.flip}>
          <Half
            char={state.prev}
            side="top"
            className="z-10 origin-bottom"
            style={{ animation: `flap-top ${FLAP_MS * 0.9}ms ease-in both` }}
          />
          <Half
            char={state.cur}
            side="bottom"
            className="z-10 origin-top"
            style={{ animation: `flap-bottom ${FLAP_MS * 0.9}ms ${FLAP_MS * 0.9}ms ease-out both` }}
          />
        </React.Fragment>
      )}
      {/* the hinge */}
      <span aria-hidden className="absolute inset-x-0 top-1/2 z-20 h-px -translate-y-1/2 bg-black/70" />
    </span>
  );
}

function FlapWord({
  text,
  width,
  delay,
  tone = "plain",
  className,
}: {
  text: string;
  width: number;
  delay: number;
  tone?: "plain" | "sun" | "green";
  className?: string;
}) {
  const chars = text.toUpperCase().padEnd(width, " ").slice(0, width).split("");
  return (
    <span className={cn("flex gap-[2px]", className)} aria-hidden>
      {chars.map((c, i) => (
        <FlapCell key={i} target={c} delay={delay + i * 28} tone={tone} />
      ))}
    </span>
  );
}

type Departure = { flight: string; city: string; band: string; remark: string; gate: string };

const DEPARTURES: Departure[] = [
  { flight: "OR 214", city: "Toronto", band: "6.5", remark: "Boarding", gate: "LST" },
  { flight: "OR 108", city: "London", band: "7.0", remark: "On time", gate: "RDG" },
  { flight: "OR 336", city: "Melbourne", band: "6.5", remark: "Final call", gate: "WRT" },
  { flight: "OR 052", city: "Helsinki", band: "6.5", remark: "On time", gate: "SPK" },
  { flight: "OR 471", city: "Glasgow", band: "6.5", remark: "Boarding", gate: "LST" },
  { flight: "OR 619", city: "Vancouver", band: "7.0", remark: "On time", gate: "RDG" },
  { flight: "OR 287", city: "Berlin", band: "6.0", remark: "Go to gate", gate: "WRT" },
  { flight: "OR 903", city: "Auckland", band: "6.5", remark: "On time", gate: "SPK" },
  { flight: "OR 145", city: "Manchester", band: "6.5", remark: "Boarding", gate: "LST" },
  { flight: "OR 760", city: "Dublin", band: "6.5", remark: "Final call", gate: "RDG" },
];

const VISIBLE = 4;

function remarkTone(remark: string): "plain" | "sun" | "green" {
  if (remark === "Final call") return "sun";
  if (remark === "Boarding" || remark === "Go to gate") return "green";
  return "plain";
}

/** Bangladesh's wall clock, read only in the browser so prerender and hydration agree. */
function useBangladeshTime() {
  const subscribe = React.useCallback((cb: () => void) => {
    const id = window.setInterval(cb, 15_000);
    return () => window.clearInterval(id);
  }, []);
  const read = () =>
    new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Dhaka",
    }).format(new Date());
  return React.useSyncExternalStore(subscribe, read, () => "--:--");
}

export function DepartureBoard() {
  const reduce = useReducedMotion();
  const [offset, setOffset] = React.useState(0);
  const time = useBangladeshTime();

  React.useEffect(() => {
    if (reduce) return;
    const id = window.setInterval(() => setOffset((o) => (o + 1) % DEPARTURES.length), 5200);
    return () => window.clearInterval(id);
  }, [reduce]);

  const rows = Array.from({ length: VISIBLE }, (_, i) => DEPARTURES[(offset + i) % DEPARTURES.length]);

  return (
    <div
      className="relative w-full overflow-hidden rounded-2xl bg-[#121916] p-4 shadow-[0_40px_80px_-40px_rgb(0_0_0/0.7),inset_0_1px_0_rgb(255_255_255/0.05)] sm:p-6"
      role="img"
      aria-label={`Departures board from Bangladesh: ${rows
        .map((r) => `${r.city}, target band ${r.band}, ${r.remark}`)
        .join("; ")}`}
    >
      <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-white/10 pb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-[#efe9dc]/55 sm:text-[11px]">
        <span className="flex items-baseline gap-3">
          <span className="text-[#efe9dc]">Departures</span>
          <span className="font-bangla text-sm tracking-normal normal-case text-[#efe9dc]/70">প্রস্থান</span>
        </span>
        <span>
          Bangladesh <span className="tabular-nums text-[#efe9dc]">{time}</span>
        </span>
      </div>

      <div className="grid gap-y-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-[#efe9dc]/45">
        <div className="flex gap-3 sm:gap-5">
          <span className="hidden w-[calc(6*24px)] sm:block lg:w-[calc(6*28px)]">Flight</span>
          <span className="w-[calc(10*20px)] sm:w-[calc(10*24px)] lg:w-[calc(10*28px)]">Destination</span>
          <span className="w-[calc(3*20px)] sm:w-[calc(3*24px)] lg:w-[calc(3*28px)]">Target</span>
          <span className="hidden w-[calc(10*24px)] md:block lg:w-[calc(10*28px)]">Remarks</span>
          <span className="hidden xl:block">Gate</span>
        </div>
        {rows.map((r, i) => (
          <div key={i} className="flex gap-3 sm:gap-5">
            <FlapWord text={r.flight} width={6} delay={i * 120} className="hidden sm:flex" />
            <FlapWord text={r.city} width={10} delay={i * 120 + 60} />
            <FlapWord text={r.band} width={3} delay={i * 120 + 90} tone="sun" />
            <FlapWord
              text={r.remark}
              width={10}
              delay={i * 120 + 140}
              tone={remarkTone(r.remark)}
              className="hidden md:flex"
            />
            <FlapWord text={r.gate} width={3} delay={i * 120 + 220} className="hidden xl:flex" />
          </div>
        ))}
      </div>
    </div>
  );
}
