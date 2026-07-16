"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error("[GlobalError]", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, -apple-system, sans-serif",
          margin: 0,
          padding: "4rem 1rem",
          minHeight: "100vh",
          background: "#0b0b12",
          color: "#f4f4f7",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ maxWidth: 480, textAlign: "center" }}>
          <div
            style={{
              width: 64,
              height: 64,
              margin: "0 auto 1.25rem",
              borderRadius: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "linear-gradient(135deg, rgba(244,63,94,0.2), rgba(220,38,38,0.1))",
              color: "#fb7185",
              fontSize: "1.75rem",
            }}
          >
            !
          </div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: "0 0 0.75rem" }}>
            Something went wrong
          </h1>
          <p style={{ opacity: 0.7, margin: "0 0 1.5rem", lineHeight: 1.5 }}>
            The app hit an unexpected error. Try again, or reload the page.
          </p>
          {error.digest && (
            <p
              style={{
                fontSize: "0.75rem",
                opacity: 0.5,
                marginBottom: "1.5rem",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              Error ID: {error.digest}
            </p>
          )}
          <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", flexWrap: "wrap" }}>
            <button
              onClick={() => unstable_retry()}
              style={{
                padding: "0.75rem 1.5rem",
                borderRadius: 12,
                border: "none",
                background: "linear-gradient(135deg, #6d5cff, #b95cff)",
                color: "white",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "0.9rem",
              }}
            >
              Try again
            </button>
            <button
              onClick={() => (window.location.href = "/")}
              style={{
                padding: "0.75rem 1.5rem",
                borderRadius: 12,
                border: "1px solid rgba(255,255,255,0.2)",
                background: "transparent",
                color: "white",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "0.9rem",
              }}
            >
              Go home
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
