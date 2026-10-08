"use client";

import * as React from "react";
import Link from "next/link";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "framer-motion";
import { Menu, X } from "lucide-react";
import { useAuth } from "@/lib/store";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Logo } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

const links = [
  { label: "The night", href: "#night" },
  { label: "The route", href: "#route" },
  { label: "The marking", href: "#stamp" },
  { label: "What you carry", href: "#pack" },
  { label: "Feedback", href: "#feedback" },
];

// Read through useSyncExternalStore, not the zustand hook: the store rehydrates
// from localStorage in the BROWSER only, so a subscribed read renders one thing
// during prerender and another after hydration. The third argument is the
// server snapshot -- nobody is signed in during a prerender.
const subscribeToAuth = (onChange: () => void) => useAuth.subscribe(onChange);
const readSignedIn = () => useAuth.getState().accessToken !== null;
const signedOutOnServer = () => false;

export function Navbar() {
  const { scrollY, scrollYProgress } = useScroll();
  // A signed-in tester who came back here for the feedback box was offered
  // "Login" and "Start Free" -- both wrong, and neither a way back into the
  // app. Send them to the dashboard instead.
  const signedIn = React.useSyncExternalStore(subscribeToAuth, readSignedIn, signedOutOnServer);
  const [scrolled, setScrolled] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  useMotionValueEvent(scrollY, "change", (y) => setScrolled(y > 24));

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div
        className={cn(
          "border-b transition-[background-color,border-color] duration-300",
          scrolled || open
            ? "border-border bg-background"
            : "border-transparent bg-transparent"
        )}
      >
        <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <Logo href="#home" />

          <div className="hidden items-center gap-7 lg:flex">
            {links.map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {l.label}
              </a>
            ))}
          </div>

          <div className="hidden items-center gap-2 md:flex">
            <ThemeToggle />
            {signedIn ? (
              <Link
                href="/dashboard"
                className="inline-flex h-10 items-center rounded-xl bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-secondary dark:hover:bg-primary/85"
              >
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="inline-flex h-10 items-center rounded-xl px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  Sign in
                </Link>
                <Link
                  href="/register"
                  className="inline-flex h-10 items-center rounded-xl bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-secondary dark:hover:bg-primary/85"
                >
                  Begin
                </Link>
              </>
            )}
          </div>

          <button
            className="inline-flex size-10 items-center justify-center rounded-xl border border-border bg-card md:hidden"
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
          >
            {open ? <X className="size-5" strokeWidth={1.6} /> : <Menu className="size-5" strokeWidth={1.6} />}
          </button>
        </nav>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className="overflow-hidden md:hidden"
            >
              <div className="flex flex-col px-5 pb-5">
                {links.map((l) => (
                  <a
                    key={l.href}
                    href={l.href}
                    onClick={() => setOpen(false)}
                    className="border-b border-border py-3.5 font-display text-xl"
                  >
                    {l.label}
                  </a>
                ))}
                <div className="mt-5 flex items-center gap-2">
                  <ThemeToggle />
                  {signedIn ? (
                    <Link
                      href="/dashboard"
                      className="inline-flex h-11 flex-1 items-center justify-center rounded-xl bg-primary text-sm font-medium text-primary-foreground"
                    >
                      Go to dashboard
                    </Link>
                  ) : (
                    <>
                      <Link
                        href="/login"
                        className="inline-flex h-11 flex-1 items-center justify-center rounded-xl border border-input bg-card text-sm font-medium"
                      >
                        Sign in
                      </Link>
                      <Link
                        href="/register"
                        className="inline-flex h-11 flex-1 items-center justify-center rounded-xl bg-primary text-sm font-medium text-primary-foreground"
                      >
                        Begin
                      </Link>
                    </>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {/* how far from Bangladesh you have scrolled */}
      <motion.div
        aria-hidden
        style={{ scaleX: scrollYProgress }}
        className="relative h-[2px] origin-left bg-sun"
      />
    </header>
  );
}
