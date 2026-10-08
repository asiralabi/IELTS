import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { LEGAL_CONTACT_EMAIL, LEGAL_UPDATED } from "@/lib/legal";

export type LegalSection = { id: string; title: string; body: React.ReactNode };

export function LegalPage({
  eyebrow,
  title,
  intro,
  sections,
}: {
  eyebrow: string;
  title: string;
  intro: React.ReactNode;
  sections: LegalSection[];
}) {
  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Logo />
          <nav className="flex gap-5 text-sm text-muted-foreground">
            <Link href="/privacy" className="hover:text-foreground">Privacy</Link>
            <Link href="/terms" className="hover:text-foreground">Terms</Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[14rem_minmax(0,1fr)] lg:py-24">
        <aside className="hidden lg:block">
          <nav aria-label="On this page" className="sticky top-10">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">On this page</p>
            <ol className="mt-4 space-y-2 text-sm">
              {sections.map((s, i) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="text-muted-foreground transition-colors hover:text-foreground">
                    <span className="mr-2 font-mono text-xs">{String(i + 1).padStart(2, "0")}</span>
                    {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
        </aside>

        <article className="max-w-[68ch]">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sun">{eyebrow}</p>
          <h1 className="mt-4 font-display text-5xl font-normal tracking-tight sm:text-6xl">{title}</h1>
          <p className="mt-4 font-mono text-xs text-muted-foreground">Last updated {LEGAL_UPDATED}</p>
          <div className="mt-8 space-y-4 text-[1.05rem] leading-relaxed text-foreground/85">{intro}</div>

          <div className="mt-14 space-y-14">
            {sections.map((s, i) => (
              <section key={s.id} id={s.id} className="scroll-mt-10 border-t border-border pt-8">
                <h2 className="flex items-baseline gap-3 font-display text-2xl font-normal">
                  <span className="font-mono text-xs text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  {s.title}
                </h2>
                <div className="legal-body mt-4 space-y-4 leading-relaxed text-foreground/85">{s.body}</div>
              </section>
            ))}
          </div>

          <p className="mt-16 border-t border-border pt-8 text-sm text-muted-foreground">
            Questions about this page?{" "}
            {LEGAL_CONTACT_EMAIL ? (
              <a className="text-foreground underline underline-offset-4" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>
                {LEGAL_CONTACT_EMAIL}
              </a>
            ) : (
              <Link className="text-foreground underline underline-offset-4" href="/#feedback">
                Write to us through the feedback form
              </Link>
            )}
            .
          </p>
        </article>
      </main>
    </div>
  );
}

/** How a reader reaches the team, used inside the policy text. */
export function ContactLine() {
  return LEGAL_CONTACT_EMAIL ? (
    <a className="underline underline-offset-4" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>
  ) : (
    <Link className="underline underline-offset-4" href="/#feedback">the feedback form on our homepage</Link>
  );
}
