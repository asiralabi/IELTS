import { cn } from "@/lib/utils";

/**
 * A chapter mark: the number in Bangla numerals, the name in English, set like
 * the running head of a printed book.
 */
export function Chapter({
  n,
  label,
  tone = "default",
  className,
}: {
  n: string;
  label: string;
  tone?: "default" | "inverse";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-4 font-mono text-[11px] uppercase tracking-[0.2em]",
        tone === "inverse" ? "text-[#efe9dc]/60" : "text-muted-foreground",
        className
      )}
    >
      <span className={cn("font-bangla text-xl tracking-normal", tone === "inverse" ? "text-sun" : "text-sun")}>
        {n}
      </span>
      <span aria-hidden className={cn("h-px w-10", tone === "inverse" ? "bg-[#efe9dc]/25" : "bg-border")} />
      <span>{label}</span>
    </div>
  );
}
