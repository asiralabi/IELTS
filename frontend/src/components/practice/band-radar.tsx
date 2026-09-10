"use client";

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
} from "recharts";

export interface BandRadarDatum {
  skill: string;
  band: number;
}

/**
 * The four-skill radar on the mock-test results screen.
 *
 * Split into its own file so recharts can be code-split away from the page.
 * It is ~278KB and draws exactly one chart, on a screen a student only reaches
 * after finishing a full mock exam -- but a static import put it in the route's
 * chunk, so every visit AND every prefetch of /mock-test paid for it. The
 * import now happens when the results actually render.
 */
export default function BandRadar({ data }: { data: BandRadarDatum[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RadarChart data={data} outerRadius="75%">
        <PolarGrid stroke="currentColor" strokeOpacity={0.15} />
        <PolarAngleAxis
          dataKey="skill"
          tick={{ fill: "currentColor", fontSize: 12, opacity: 0.7 }}
        />
        <Radar
          dataKey="band"
          stroke="#7C4DFF"
          fill="#5B5CEB"
          fillOpacity={0.35}
          isAnimationActive
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
