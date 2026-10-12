"use client";

import * as React from "react";

/**
 * Google's own "Sign in with Google" button (Google Identity Services).
 *
 * Google renders the button in an iframe and hands back a signed ID token
 * (`credential`), which the backend verifies at POST /auth/google. Nothing
 * redirects, so the OAuth client needs JavaScript origins but no redirect URIs.
 * Renders nothing when NEXT_PUBLIC_GOOGLE_CLIENT_ID is unset.
 */

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const SCRIPT_SRC = "https://accounts.google.com/gsi/client";

type GsiButtonText = "signin_with" | "signup_with" | "continue_with";

interface Gsi {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (response: { credential: string }) => void;
      }) => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}

declare global {
  interface Window {
    google?: Gsi;
  }
}

let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  scriptPromise ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Could not load Google sign-in"));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

export const googleSignInEnabled = CLIENT_ID !== "";

export function GoogleButton({
  text,
  onCredential,
}: {
  text: GsiButtonText;
  onCredential: (credential: string) => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  // GIS keeps the first callback it is given; route through a ref so it
  // always reaches the latest handler (and the latest form state).
  const handler = React.useRef(onCredential);
  React.useEffect(() => {
    handler.current = onCredential;
  }, [onCredential]);

  React.useEffect(() => {
    if (!CLIENT_ID) return;
    let cancelled = false;
    loadScript()
      .then(() => {
        const el = ref.current;
        const gsi = window.google?.accounts.id;
        if (cancelled || !el || !gsi) return;
        gsi.initialize({
          client_id: CLIENT_ID,
          callback: (response) => handler.current(response.credential),
        });
        gsi.renderButton(el, {
          type: "standard",
          theme: "outline",
          size: "large",
          shape: "pill",
          text,
          width: Math.min(400, el.offsetWidth || 320),
        });
      })
      .catch(() => {
        /* No button is better than a broken one; email sign-in still works. */
      });
    return () => {
      cancelled = true;
    };
  }, [text]);

  if (!CLIENT_ID) return null;
  return <div ref={ref} className="flex min-h-[44px] w-full justify-center" />;
}

export function OrDivider() {
  return (
    <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-wider text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      or
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
