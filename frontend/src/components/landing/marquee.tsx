const ROUTES = ["LHR", "YYZ", "MEL", "HEL", "GLA", "YVR", "BER", "AKL", "MAN", "DUB", "SYD", "BOS"];

/** An endless strip of routes out of Bangladesh. Decorative, so hidden from readers. */
export function Marquee() {
  const strip = ROUTES.map((code) => (
    <span key={code} className="flex items-center gap-6 pr-6">
      <span>BD</span>
      <span className="text-sun">→</span>
      <span className="text-primary">{code}</span>
      <span className="text-border">/</span>
    </span>
  ));
  return (
    <div aria-hidden className="overflow-hidden border-y border-border bg-background py-5 select-none">
      <div className="flex w-max animate-marquee font-mono text-sm tracking-[0.2em] text-foreground/70 motion-reduce:animate-none">
        <div className="flex">{strip}</div>
        <div className="flex">{strip}</div>
      </div>
    </div>
  );
}
