import Link from "next/link";
import { Sparkles } from "lucide-react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-mesh px-4 py-12">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-24 left-1/3 size-[420px] animate-aurora rounded-full bg-primary/20 blur-[120px]" />
        <div className="absolute bottom-0 right-1/4 size-[380px] animate-aurora rounded-full bg-accent/15 blur-[110px] [animation-delay:-5s]" />
      </div>

      <Link href="/" className="mb-8 flex items-center gap-2">
        <span className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-secondary shadow-glow">
          <Sparkles className="size-5 text-white" aria-hidden />
        </span>
        <span className="font-display text-xl font-bold tracking-tight">AI IELTS</span>
      </Link>

      {children}
    </main>
  );
}
