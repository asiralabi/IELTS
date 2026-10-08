import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * The Oratio mark: an open "O" drawn as a flight path, with the red sun
 * sitting where the path leaves the circle. Plain SVG in currentColor so it
 * follows the theme without a second asset.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden
      className={cn("size-8 shrink-0", className)}
    >
      <path
        d="M24.8 9.2A11 11 0 1 0 27 16"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="25.6" cy="8.6" r="3.6" className="fill-sun" />
    </svg>
  );
}

export function Logo({
  href = "/",
  className,
  label = true,
}: {
  href?: string;
  className?: string;
  label?: boolean;
}) {
  return (
    <Link
      href={href}
      aria-label="Oratio home"
      className={cn("group inline-flex items-center gap-2.5 text-foreground", className)}
    >
      <LogoMark className="transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-rotate-12" />
      {label && (
        <span className="font-display text-[1.35rem] font-medium italic leading-none tracking-tight">
          Oratio
        </span>
      )}
    </Link>
  );
}
