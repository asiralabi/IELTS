"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "relative inline-flex items-center justify-center gap-2 overflow-hidden whitespace-nowrap font-medium transition-all duration-200 select-none disabled:pointer-events-none disabled:opacity-50 active:scale-[0.97] cursor-pointer",
  {
    variants: {
      variant: {
        primary:
          "bg-gradient-to-r from-primary via-secondary to-primary bg-[length:200%_auto] text-primary-foreground shadow-lift hover:bg-[position:100%_50%] hover:shadow-glow",
        secondary:
          "glass text-foreground hover:border-primary/40 hover:shadow-soft",
        ghost: "text-muted-foreground hover:text-foreground hover:bg-muted",
        danger: "bg-danger text-white hover:bg-danger/90 shadow-soft",
        success: "bg-success text-white hover:bg-success/90 shadow-soft",
        outline:
          "border border-input bg-transparent hover:bg-muted text-foreground",
      },
      size: {
        sm: "h-9 rounded-xl px-4 text-sm",
        md: "h-11 rounded-2xl px-6 text-sm",
        lg: "h-13 rounded-[20px] px-8 text-base",
        icon: "size-11 rounded-2xl",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  }
);

type Ripple = { x: number; y: number; id: number };

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, onClick, disabled, ...props }, ref) => {
    const [ripples, setRipples] = React.useState<Ripple[]>([]);

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const id = Date.now();
      setRipples((r) => [...r, { x: e.clientX - rect.left, y: e.clientY - rect.top, id }]);
      setTimeout(() => setRipples((r) => r.filter((rp) => rp.id !== id)), 600);
      onClick?.(e);
    };

    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        onClick={handleClick}
        disabled={disabled || loading}
        {...props}
      >
        {ripples.map((r) => (
          <span
            key={r.id}
            className="pointer-events-none absolute size-4 -translate-x-1/2 -translate-y-1/2 animate-ping rounded-full bg-white/40"
            style={{ left: r.x, top: r.y }}
          />
        ))}
        {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";
