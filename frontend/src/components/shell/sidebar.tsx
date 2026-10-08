"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  ClipboardList,
  PenLine,
  Mic,
  BookOpen,
  BookOpenCheck,
  Headphones,
  Layers,
  CalendarCheck,
  Library,
  Settings,
  Home,
  MessageSquareHeart,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { LogoMark } from "@/components/brand/logo";

const items = [
  { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard" },
  { icon: ClipboardList, label: "Mock Tests", href: "/mock-test" },
  { icon: BookOpenCheck, label: "Cambridge", href: "/cambridge" },
  { icon: PenLine, label: "Writing", href: "/writing" },
  { icon: Mic, label: "Speaking", href: "/speaking" },
  { icon: BookOpen, label: "Reading", href: "/reading" },
  { icon: Headphones, label: "Listening", href: "/listening" },
  { icon: Layers, label: "Vocabulary", href: "/vocabulary" },
  { icon: CalendarCheck, label: "Study Plan", href: "/study-plan" },
  { icon: Library, label: "Resources", href: "/resources" },
  { icon: Settings, label: "Settings", href: "/settings" },
];

// The landing page and its feedback box live OUTSIDE the app shell, and until
// now nothing in here pointed at them: the logo goes to /dashboard, so a
// signed-in tester had no route back to `/` and could not reach the feedback
// form a second time. These two are plain hrefs, not app routes -- they never
// take an active state, which is also why they are not in `items` (a "/" entry
// there would light up on every page, since the match is startsWith).
const outboundItems = [
  { icon: Home, label: "Home", href: "/" },
  { icon: MessageSquareHeart, label: "Feedback", href: "/#feedback" },
];

/**
 * Props that hold a link's prefetch back until the user shows intent.
 *
 * Every one of the eleven nav items is in the viewport the whole time, so the
 * default (prefetch on becoming visible) had each app page quietly downloading
 * the WHOLE app after load -- measured at 1013KB across 52 requests on
 * /dashboard, including all 278KB of the charting library on a page that draws
 * no charts. On a phone that is a megabyte of background traffic competing
 * with the API call the user is actually waiting for.
 *
 * `prefetch={false}` in the App Router disables hover prefetching too, so the
 * arming is explicit: null restores the default the moment intent shows.
 * Hover and focus cover a mouse and a keyboard; touchstart fires before the
 * tap completes, which buys a phone a head start it otherwise never gets.
 * This is the `HoverPrefetchLink` pattern from the Next.js docs, widened past
 * the mouse.
 */
function useIntentPrefetch() {
  const [armed, setArmed] = React.useState(false);
  const arm = React.useCallback(() => setArmed(true), []);
  return {
    prefetch: armed ? null : false,
    onMouseEnter: arm,
    onFocus: arm,
    onTouchStart: arm,
  } as const;
}

export function Sidebar() {
  const pathname = usePathname();
  const intent = useIntentPrefetch();
  const [expanded, setExpanded] = React.useState(false);

  return (
    <motion.aside
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      animate={{ width: expanded ? 224 : 68 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="fixed inset-y-0 left-0 z-40 hidden flex-col overflow-hidden border-r border-border bg-card p-3 md:flex"
    >
      <Link href="/dashboard" className="mb-5 flex items-center gap-3 px-1 py-2">
        <span className="flex size-9 shrink-0 items-center justify-center">
          <LogoMark className="size-7" />
        </span>
        <motion.span
          animate={{ opacity: expanded ? 1 : 0 }}
          transition={{ duration: 0.15 }}
          className="whitespace-nowrap font-display text-xl font-medium italic tracking-tight"
        >
          Oratio
        </motion.span>
      </Link>

      <nav className="flex flex-1 flex-col gap-1" aria-label="Main navigation">
        {items.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              {...intent}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "text-foreground"
                  : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
              )}
            >
              {active && (
                <motion.span
                  layoutId="sidebar-active"
                  transition={{ type: "spring", stiffness: 350, damping: 30 }}
                  className="absolute inset-0 rounded-lg bg-muted before:absolute before:inset-y-2 before:-left-3 before:w-[3px] before:rounded-r before:bg-sun"
                />
              )}
              <item.icon
                className="relative size-5 shrink-0" strokeWidth={1.6}
                aria-hidden
              />
              <motion.span
                animate={{ opacity: expanded ? 1 : 0 }}
                transition={{ duration: 0.15 }}
                className="relative whitespace-nowrap"
              >
                {item.label}
              </motion.span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-2 border-t border-border/60 pt-2">
        {outboundItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            {...intent}
            aria-label={item.label}
            className="group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
          >
            <item.icon
              className="relative size-5 shrink-0" strokeWidth={1.6}
              aria-hidden
            />
            <motion.span
              animate={{ opacity: expanded ? 1 : 0 }}
              transition={{ duration: 0.15 }}
              className="relative whitespace-nowrap"
            >
              {item.label}
            </motion.span>
          </Link>
        ))}
      </div>
    </motion.aside>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  const intent = useIntentPrefetch();
  const mobileItems = items.slice(0, 5);

  return (
    <nav
      aria-label="Main navigation"
      className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-card/95 px-2 pt-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] backdrop-blur md:hidden"
    >
      {mobileItems.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            {...intent}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex flex-col items-center gap-1 rounded-lg px-3 py-1.5 text-[10px] font-medium tracking-wide transition-colors",
              active ? "text-foreground after:absolute after:-top-1.5 after:h-[2px] after:w-6 after:rounded-full after:bg-sun" : "text-muted-foreground"
            )}
          >
            <item.icon className="size-5" strokeWidth={1.6} aria-hidden />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * Mobile-only hamburger + slide-in drawer that exposes ALL sidebar items
 * (bottom nav on mobile only shows the first 5). Closes automatically when
 * the user taps a link and preserves aria-expanded state.
 */
export function MobileDrawer() {
  const pathname = usePathname();
  const intent = useIntentPrefetch();
  const [open, setOpen] = React.useState(false);

  // Close whenever the route changes.
  React.useEffect(() => {
    Promise.resolve().then(() => setOpen(false));
  }, [pathname]);

  return (
    <>
      <button
        type="button"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls="mobile-drawer"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex size-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground transition-colors hover:text-foreground md:hidden"
      >
        {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="drawer-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-40 bg-[#1b231f]/40 md:hidden"
              aria-hidden
            />
            <motion.aside
              key="drawer-panel"
              id="mobile-drawer"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation menu"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 320, damping: 32 }}
              className="fixed inset-y-0 left-0 z-50 flex w-[272px] flex-col border-r border-border bg-card p-4 shadow-lift md:hidden"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <LogoMark className="size-7" />
                  <span className="font-display text-xl font-medium italic tracking-tight">Oratio</span>
                </div>
                <button
                  type="button"
                  aria-label="Close menu"
                  onClick={() => setOpen(false)}
                  className="inline-flex size-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="size-4" aria-hidden />
                </button>
              </div>
              <nav
                className="flex flex-1 flex-col gap-1 overflow-y-auto"
                aria-label="All navigation"
              >
                {items.map((item) => {
                  const active = pathname.startsWith(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      {...intent}
                      onClick={() => setOpen(false)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                        active
                          ? "bg-muted text-foreground shadow-[inset_3px_0_0_var(--sun)]"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      <item.icon className="size-5 shrink-0" strokeWidth={1.6} aria-hidden />
                      {item.label}
                    </Link>
                  );
                })}
              </nav>

              <div className="mt-2 border-t border-border/60 pt-2">
                {outboundItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    {...intent}
                    onClick={() => setOpen(false)}
                    className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <item.icon className="size-5 shrink-0" strokeWidth={1.6} aria-hidden />
                    {item.label}
                  </Link>
                ))}
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
