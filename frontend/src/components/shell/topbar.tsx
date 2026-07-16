"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuth } from "@/lib/store";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { MobileDrawer } from "@/components/shell/sidebar";
import { formatBand } from "@/lib/utils";

export function Topbar({ title }: { title: string }) {
  const router = useRouter();
  const { user, logout } = useAuth();

  return (
    <header className="mb-8 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <MobileDrawer />
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
            {title}
          </h1>
          {user && (
            <p className="mt-1 text-sm text-muted-foreground">
              {user.full_name ?? user.email}
              {user.target_band != null && (
                <Badge variant="accent" className="ml-2">
                  Target {formatBand(user.target_band)}
                </Badge>
              )}
            </p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <button
          aria-label="Log out"
          onClick={() => {
            logout();
            router.push("/");
          }}
          className="glass inline-flex size-11 items-center justify-center rounded-2xl text-muted-foreground transition-all hover:text-danger hover:shadow-soft"
        >
          <LogOut className="size-5" aria-hidden />
        </button>
      </div>
    </header>
  );
}
