import Link from "next/link";
import { Logo } from "@/components/brand/logo";

/**
 * Sign-in and sign-up share one frame: the form on paper, and beside it a
 * boarding pass that is still waiting for its destination.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-[100dvh] bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <aside className="relative hidden overflow-hidden bg-secondary text-[#efe9dc] lg:flex lg:flex-col lg:justify-between lg:p-12 xl:p-16">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-28 -bottom-28 size-[19rem] rounded-full bg-sun/90"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-6 left-10 font-bangla text-[11rem] leading-none text-white/[0.05] select-none"
        >
          যাত্রা
        </div>

        <Logo className="relative text-[#efe9dc]" />

        <div className="relative max-w-md">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[#efe9dc]/60">
            Boarding pass · not yet issued
          </p>
          <div className="mt-5 rounded-2xl bg-[#f3eee3] p-6 text-[#1b231f] shadow-[0_30px_60px_-30px_rgb(0_0_0/0.6)]">
            <div className="flex items-end justify-between">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#5d645e]">From</p>
                <p className="font-display text-4xl font-medium leading-none">BD</p>
                <p className="mt-1 text-xs text-[#5d645e]">Bangladesh</p>
              </div>
              <svg viewBox="0 0 120 24" className="mb-5 h-6 w-28 text-[#0f5c45]" aria-hidden>
                <path d="M2 20 Q60 -8 118 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 4" />
                <circle cx="118" cy="20" r="3" fill="#c9372c" />
              </svg>
              <div className="text-right">
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[#5d645e]">To</p>
                <p className="font-display text-[1.7rem] font-medium italic leading-none text-[#0f5c45]">Anywhere</p>
              </div>
            </div>
            <div className="mt-6 grid grid-cols-3 gap-4 border-t border-dashed border-[#1b231f]/25 pt-4 font-mono text-[11px] uppercase tracking-[0.1em]">
              <div>
                <p className="text-[#5d645e]">Passenger</p>
                <p className="mt-1 text-[#1b231f]">You</p>
              </div>
              <div>
                <p className="text-[#5d645e]">Requires</p>
                <p className="mt-1 text-[#1b231f]">IELTS</p>
              </div>
              <div>
                <p className="text-[#5d645e]">Gate</p>
                <p className="mt-1 text-[#c9372c]">Open</p>
              </div>
            </div>
          </div>
          <p className="mt-8 font-display text-2xl leading-snug text-[#efe9dc]/90">
            “The ticket is the easy part. The band score is what gets you on the plane.”
          </p>
        </div>

        <p className="relative font-mono text-[11px] uppercase tracking-[0.16em] text-[#efe9dc]/50">
          Practice at home · Marked against the band descriptors
        </p>
      </aside>

      <section className="flex flex-col px-5 py-8 sm:px-10 lg:px-16">
        <Logo className="lg:hidden" />
        <div className="flex flex-1 items-center justify-center py-10">{children}</div>
        <p className="flex justify-center gap-5 text-xs text-muted-foreground">
          <Link href="/privacy" className="hover:text-foreground">Privacy</Link>
          <Link href="/terms" className="hover:text-foreground">Terms</Link>
        </p>
      </section>
    </main>
  );
}
