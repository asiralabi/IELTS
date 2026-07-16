import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-shimmer rounded-2xl bg-[linear-gradient(110deg,transparent_25%,rgb(100_116_139/0.15)_50%,transparent_75%)] bg-[length:200%_100%] bg-muted/60",
        className
      )}
      {...props}
    />
  );
}
