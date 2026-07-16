import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "bg-primary/10 text-primary dark:bg-primary/20 dark:text-indigo-300",
        secondary: "bg-secondary/10 text-secondary dark:bg-secondary/20 dark:text-violet-300",
        accent: "bg-accent/15 text-sky-700 dark:bg-accent/20 dark:text-sky-300",
        success: "bg-success/10 text-emerald-700 dark:bg-success/20 dark:text-emerald-300",
        warning: "bg-warning/10 text-amber-700 dark:bg-warning/20 dark:text-amber-300",
        danger: "bg-danger/10 text-red-700 dark:bg-danger/20 dark:text-red-300",
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
