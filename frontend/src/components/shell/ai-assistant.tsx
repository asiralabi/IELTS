"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageCircle } from "lucide-react";

/**
 * A quiet way into the tutor chat from any page. It used to be a bouncing
 * robot with a speech bubble that popped up uninvited; a student working
 * through a timed reading passage does not need either.
 */
export function AiAssistant() {
  const pathname = usePathname();
  if (pathname.startsWith("/chat") || pathname.includes("/test")) return null;

  return (
    <Link
      href="/chat"
      className="group fixed right-4 bottom-20 z-40 inline-flex h-11 items-center gap-2 rounded-full border border-border bg-card pr-4 pl-3 text-sm font-medium text-foreground shadow-lift transition-[border-color,transform] duration-300 hover:-translate-y-0.5 hover:border-foreground/30 md:right-6 md:bottom-6"
    >
      <span className="relative flex size-6 items-center justify-center">
        <MessageCircle className="size-[18px]" strokeWidth={1.6} aria-hidden />
        <span className="absolute top-0.5 right-0 size-1.5 rounded-full bg-sun" aria-hidden />
      </span>
      Ask Oratio
    </Link>
  );
}
