"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuth } from "@/lib/store";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { MobileDrawer } from "@/components/shell/sidebar";
import { formatBand } from "@/lib/utils";

export function Topbar({ title }: { title: string }) {
  const router = useRouter();
  const { user, logout } = useAuth();

  return (
    <header className="mb-8 flex items-start justify-between gap-4 border-b border-border pb-5">
      <div className="flex items-center gap-3">
        <MobileDrawer />
        <div>
          {user && (
            <p className="flex flex-wrap items-center gap-x-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              <span>{user.full_name ?? user.email}</span>
              {user.target_band != null && (
                <>
                  <span aria-hidden className="text-border">/</span>
                  <span>
                    Target <span className="text-sun">{formatBand(user.target_band)}</span>
                  </span>
                </>
              )}
            </p>
          )}
          <h1 className="mt-1 font-display text-3xl font-medium tracking-tight sm:text-[2.5rem] sm:leading-[1.1]">
            {title}
          </h1>
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
          className="inline-flex size-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground transition-colors hover:border-danger/40 hover:text-danger"
        >
          <LogOut className="size-[18px]" strokeWidth={1.6} aria-hidden />
        </button>
      </div>
    </header>
  );
}
