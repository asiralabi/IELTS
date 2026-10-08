"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "relative inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium tracking-[-0.005em] transition-[background-color,color,border-color,box-shadow,transform] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] select-none disabled:pointer-events-none disabled:opacity-50 active:translate-y-px cursor-pointer",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.12),0_1px_0_rgb(27_35_31/0.2)] hover:bg-secondary dark:hover:bg-primary/85",
        secondary:
          "border border-input bg-card text-foreground hover:border-foreground/35 hover:bg-muted/60",
        ghost: "text-muted-foreground hover:text-foreground hover:bg-muted",
        danger: "bg-danger text-white hover:bg-danger/90",
        success: "bg-success text-white hover:bg-success/90",
        outline:
          "border border-input bg-transparent hover:bg-muted text-foreground",
      },
      size: {
        sm: "h-9 rounded-lg px-4 text-sm",
        md: "h-11 rounded-xl px-5 text-sm",
        lg: "h-13 rounded-xl px-7 text-base",
        icon: "size-11 rounded-xl",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
);
Button.displayName = "Button";
