"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Logo } from "@/components/brand/logo";

export function Footer() {
  return (
    <footer id="about" className="relative overflow-hidden bg-secondary text-[#efe9dc]">
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-[15rem] left-1/2 size-[22rem] -translate-x-1/2 rounded-full bg-sun sm:-bottom-[21rem] sm:size-[31rem]"
      />
      <div className="relative mx-auto max-w-7xl px-5 pt-28 pb-10 sm:px-8 sm:pt-36">
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
          lang="bn"
          className="font-bangla text-6xl leading-[1.15] sm:text-8xl lg:text-[9rem]"
        >
          শুভ যাত্রা
        </motion.p>
        <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.2em] text-[#efe9dc]/60">
          Shubho jatra · Have a good journey
        </p>

        <div className="mt-14 grid gap-8 md:grid-cols-12 md:items-end">
          <p className="max-w-[40ch] font-display text-2xl leading-snug md:col-span-6 sm:text-3xl">
            The real test takes just under three hours. Practise it here until the clock stops scaring you.
          </p>
          <div className="md:col-span-5 md:col-start-8 md:justify-self-end">
            <Link
              href="/register"
              className="group inline-flex h-13 items-center gap-3 rounded-xl bg-[#efe9dc] px-7 font-medium text-[#173b30] transition-colors hover:bg-white"
            >
              Begin, it is free
              <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" strokeWidth={1.8} aria-hidden />
            </Link>
          </div>
        </div>

        <div className="relative mt-40 flex flex-col gap-4 border-t border-[#efe9dc]/15 pt-6 text-sm text-[#efe9dc]/70 sm:mt-56 sm:flex-row sm:items-center sm:justify-between">
          <Logo href="#home" className="text-[#efe9dc]" />
          <p className="font-mono text-[11px] uppercase tracking-[0.16em]">
            For every student with a bag half-packed
          </p>
          <p className="flex gap-5 font-mono text-[11px] uppercase tracking-[0.16em]">
            <Link href="/privacy" className="hover:text-[#efe9dc]">Privacy</Link>
            <Link href="/terms" className="hover:text-[#efe9dc]">Terms</Link>
            <span>© {new Date().getFullYear()} Oratio</span>
          </p>
        </div>
        <p className="relative mt-6 max-w-3xl text-xs leading-relaxed text-[#efe9dc]/55">
          IELTS is a registered trademark of the British Council, IDP: IELTS Australia and
          Cambridge University Press &amp; Assessment. Oratio is an independent practice
          service and is not affiliated with, approved or endorsed by them. Scores are
          practice estimates, not official results.
        </p>
      </div>
    </footer>
  );
}
