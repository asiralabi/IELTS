"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  PenLine,
  Mic,
  BookOpen,
  Headphones,
  Flame,
  ClipboardList,
  ArrowRight,
  Trophy,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Progress } from "@/lib/types";
import { useAuth } from "@/lib/store";
import { Topbar } from "@/components/shell/topbar";
import { GlowCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BandRing, ProgressBar } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { formatBand } from "@/lib/utils";

const skillMeta = [
  { key: "writing", label: "Writing", icon: PenLine, href: "/writing", color: "text-orange-500" },
  { key: "speaking", label: "Speaking", icon: Mic, href: "/speaking", color: "text-emerald-500" },
  { key: "reading", label: "Reading", icon: BookOpen, href: "/reading", color: "text-violet-500" },
  { key: "listening", label: "Listening", icon: Headphones, href: "/listening", color: "text-sky-500" },
] as const;

function currentBand(p: Progress): number | null {
  const bands = skillMeta
    .map((s) => p.skills[s.key].latest_band)
    .filter((b): b is number => b != null);
  if (p.skills.mock_exam.latest_band != null) return p.skills.mock_exam.latest_band;
  if (!bands.length) return null;
  return Math.round((bands.reduce((a, b) => a + b, 0) / bands.length) * 2) / 2;
}

export default function DashboardPage() {
  const user = useAuth((s) => s.user);
  const [progress, setProgress] = React.useState<Progress | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api.progress().then(setProgress).catch((e) => setError(e.message));
  }, []);

  const totalActivities = progress
    ? Object.values(progress.counts).reduce((a, b) => a + b, 0)
    : 0;
  const band = progress ? currentBand(progress) : null;
  const target = progress?.target_band ?? user?.target_band ?? null;
  const overallPct =
    band != null && target != null ? Math.min(100, (band / target) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl">
      <Topbar title={`Welcome back${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`} />

      {error && (
        <div className="glass mb-6 rounded-2xl border-danger/30 p-4 text-sm text-danger">
          {error}
        </div>
      )}

      {!progress && !error ? (
        <div className="grid gap-6 md:grid-cols-3">
          <Skeleton className="h-56 md:col-span-1" />
          <Skeleton className="h-56 md:col-span-2" />
          <Skeleton className="h-40 md:col-span-3" />
        </div>
      ) : progress ? (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="grid gap-6 md:grid-cols-3"
        >
          {/* Band overview */}
          <motion.div variants={fadeUp}>
            <GlowCard className="flex h-full flex-col items-center justify-center p-8 text-center">
              <BandRing band={band} label="Current Band" />
              <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
                <Trophy className="size-4 text-warning" aria-hidden />
                Target band:{" "}
                <span className="font-semibold text-foreground">{formatBand(target)}</span>
              </div>
            </GlowCard>
          </motion.div>

          {/* Overall progress */}
          <motion.div variants={fadeUp} className="md:col-span-2">
            <GlowCard className="h-full">
              <CardHeader>
                <CardTitle>Overall Progress</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className="text-muted-foreground">Toward your target</span>
                    <span className="font-medium">{Math.round(overallPct)}%</span>
                  </div>
                  <ProgressBar value={overallPct} />
                </div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  {skillMeta.map((s) => (
                    <Link key={s.key} href={s.href} className="group">
                      <div className="glass rounded-2xl p-4 transition-all group-hover:shadow-glow">
                        <s.icon className={`size-5 ${s.color}`} aria-hidden />
                        <div className="mt-2 font-display text-xl font-bold">
                          {formatBand(progress.skills[s.key].latest_band)}
                        </div>
                        <div className="text-xs text-muted-foreground">{s.label}</div>
                      </div>
                    </Link>
                  ))}
                </div>
              </CardContent>
            </GlowCard>
          </motion.div>

          {/* Stats row */}
          <motion.div variants={fadeUp} className="md:col-span-3">
            <div className="grid gap-4 sm:grid-cols-3">
              <GlowCard className="flex items-center gap-4 p-5">
                <span className="flex size-12 items-center justify-center rounded-2xl bg-warning/15 text-warning">
                  <Flame className="size-6" aria-hidden />
                </span>
                <div>
                  <div className="font-display text-2xl font-bold">{totalActivities}</div>
                  <div className="text-xs text-muted-foreground">Total activities</div>
                </div>
              </GlowCard>
              <GlowCard className="flex items-center gap-4 p-5">
                <span className="flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary">
                  <ClipboardList className="size-6" aria-hidden />
                </span>
                <div>
                  <div className="font-display text-2xl font-bold">
                    {progress.counts.mock_exams}
                  </div>
                  <div className="text-xs text-muted-foreground">Mock exams taken</div>
                </div>
              </GlowCard>
              <Link href="/mock-test">
                <GlowCard className="group flex h-full items-center justify-between p-5">
                  <div>
                    <div className="font-display font-semibold">Today&apos;s Goal</div>
                    <div className="text-xs text-muted-foreground">
                      Take a full AI mock test
                    </div>
                  </div>
                  <ArrowRight
                    className="size-5 text-primary transition-transform group-hover:translate-x-1"
                    aria-hidden
                  />
                </GlowCard>
              </Link>
            </div>
          </motion.div>

          {/* Recent activity */}
          <motion.div variants={fadeUp} className="md:col-span-3">
            <GlowCard>
              <CardHeader>
                <CardTitle>Recent Activity</CardTitle>
              </CardHeader>
              <CardContent>
                {progress.timeline.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    No activity yet — start with a practice module or take a mock test.
                  </p>
                ) : (
                  <ul className="divide-y divide-border">
                    {progress.timeline.map((item) => (
                      <li
                        key={`${item.type}-${item.id}`}
                        className="flex items-center justify-between py-3 text-sm"
                      >
                        <span className="capitalize text-muted-foreground">
                          {item.type.replace("_", " ")}
                        </span>
                        <div className="flex items-center gap-3">
                          {item.band != null && (
                            <Badge>Band {formatBand(item.band)}</Badge>
                          )}
                          {item.score != null && item.total != null && (
                            <Badge variant="accent">
                              {item.score}/{item.total}
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground">
                            {new Date(item.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </GlowCard>
          </motion.div>
        </motion.div>
      ) : null}
    </div>
  );
}
