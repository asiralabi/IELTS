"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Download, LogOut, Target, Mail, Trash2, UserRound } from "lucide-react";
import { useAuth } from "@/lib/store";
import { api } from "@/lib/api";
import { Input, Label } from "@/components/ui/input";
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
  const [exporting, setExporting] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);

  const downloadData = async () => {
    setExporting(true);
    try {
      const data = await api.exportMyData();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = "oratio-my-data.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not export your data.");
    } finally {
      setExporting(false);
    }
  };

  const deleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setDeleting(true);
    try {
      await api.deleteAccount(password);
      logout();
      toast.success("Your account and all of its data have been deleted.");
      router.push("/");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete your account.");
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <Topbar title="Settings" />

      <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-5">
        <motion.div variants={fadeUp}>
          <GlowCard className="p-7">
            <h2 className="mb-5 font-display font-medium">Profile</h2>
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
              <h2 className="font-display font-medium">Appearance</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Switch between light and dark mode.
              </p>
            </div>
            <ThemeToggle />
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlowCard className="p-7">
            <h2 className="font-display font-medium">Your data</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Download a copy of everything Oratio holds about you, or erase it. Read
              how it is handled in the{" "}
              <Link href="/privacy" className="text-foreground underline decoration-sun underline-offset-4">
                privacy policy
              </Link>
              .
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Button variant="secondary" loading={exporting} onClick={downloadData}>
                <Download className="size-4" aria-hidden />
                Download my data
              </Button>
              {!confirming && (
                <Button variant="outline" onClick={() => setConfirming(true)} className="text-danger">
                  <Trash2 className="size-4" aria-hidden />
                  Delete my account
                </Button>
              )}
            </div>
            {confirming && (
              <form onSubmit={deleteAccount} className="mt-5 rounded-xl border border-danger/30 bg-danger/5 p-5">
                <p className="text-sm">
                  This permanently deletes your account, essays, recordings, scores and
                  chats. It cannot be undone.
                </p>
                <Label htmlFor="delete-password" className="mt-4">
                  Enter your password to confirm
                </Label>
                <Input
                  id="delete-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <div className="mt-4 flex gap-2">
                  <Button type="submit" variant="danger" loading={deleting} disabled={!password}>
                    Delete everything
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setConfirming(false);
                      setPassword("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            )}
          </GlowCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlowCard className="flex items-center justify-between p-7">
            <div>
              <h2 className="font-display font-medium">Session</h2>
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
