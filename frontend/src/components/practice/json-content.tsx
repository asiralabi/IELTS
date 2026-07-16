"use client";

import ReactMarkdown from "react-markdown";

/** Renders loosely-shaped LLM JSON (strings, arrays, nested objects) as readable content. */
export function JsonContent({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value == null) return null;

  if (typeof value === "string") {
    return (
      <div className="prose-chat text-sm leading-relaxed text-muted-foreground">
        <ReactMarkdown>{value}</ReactMarkdown>
      </div>
    );
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="text-sm text-muted-foreground">{String(value)}</span>;
  }

  if (Array.isArray(value)) {
    return (
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
        {value.map((item, i) => (
          <li key={i}>
            <JsonContent value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    );
  }

  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, v]) => v != null
  );
  return (
    <div className={depth > 0 ? "space-y-2" : "space-y-4"}>
      {entries.map(([key, v]) => (
        <div key={key}>
          <h4 className="mb-1 text-sm font-semibold capitalize text-foreground">
            {key.replace(/_/g, " ")}
          </h4>
          <JsonContent value={v} depth={depth + 1} />
        </div>
      ))}
    </div>
  );
}
