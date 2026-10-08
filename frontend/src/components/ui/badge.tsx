import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.06em]",
  {
    variants: {
      variant: {
        default: "bg-primary/10 text-primary dark:bg-primary/15",
        secondary: "bg-foreground/[0.06] text-foreground/80",
        accent: "bg-primary/10 text-primary dark:bg-primary/15",
        success: "bg-success/12 text-success",
        warning: "bg-warning/12 text-warning",
        danger: "bg-danger/10 text-danger",
        outline: "border border-border text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
