"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { LogOut, Target, Mail, UserRound } from "lucide-react";
import { useAuth } from "@/lib/store";
import { API_URL } from "@/lib/api";
import { Topbar } from "@/components/shell/topbar";
import { Button } from "@/components/ui/button";
import { GlowCard } from "@/components/ui/card";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { formatBand } from "@/lib/utils";

export default function SettingsPage() {
  const router = useRouter();
  const { user, logout } = useAuth();

  return (
    <div className="mx-auto max-w-2xl">
      <Topbar title="Settings" />

      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-5">
        <motion.div variants={fadeUp}>
          <GlowCard className="p-7">
            <h2 className="mb-5 font-display font-semibold">Profile</h2>
            <dl className="space-y-4 text-sm">
              <div className="flex items-center gap-3">
                <UserRound className="size-4 text-muted-foreground" aria-hidden />
                <dt className="w-28 text-muted-foreground">Name</dt>
                <dd className="font-medium">{user?.full_name ?? "—"}</dd>
              </div>
              <div className="flex items-center gap-3">
                <Mail className="size-4 text-muted-foreground" aria-hidden />
                <dt className="w-28 text-muted-foreground">Email</dt>
                <dd className="font-medium">{user?.email ?? "—"}</dd>
              </div>
              <div className="flex items-center gap-3">
                <Target className="size-4 text-muted-foreground" aria-hidden />
                <dt className="w-28 text-muted-foreground">Target band</dt>
                <dd>
                  <Badge variant="accent">{formatBand(user?.target_band)}</Badge>
                </dd>
              </div>
            </dl>
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlowCard className="flex items-center justify-between p-7">
            <div>
              <h2 className="font-display font-semibold">Appearance</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Switch between light and dark mode.
              </p>
            </div>
            <ThemeToggle />
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlowCard className="flex items-center justify-between p-7">
            <div>
              <h2 className="font-display font-semibold">Backend</h2>
              <p className="mt-1 font-mono text-xs text-muted-foreground">{API_URL}</p>
            </div>
            <Badge variant="outline">FastAPI + local AI</Badge>
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlowCard className="flex items-center justify-between p-7">
            <div>
              <h2 className="font-display font-semibold">Session</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Sign out of your account on this device.
              </p>
            </div>
            <Button
              variant="danger"
              onClick={() => {
                logout();
                router.push("/");
              }}
            >
              <LogOut className="size-4" aria-hidden />
              Log out
            </Button>
          </GlowCard>
        </motion.div>
      </motion.div>
    </div>
  );
}
