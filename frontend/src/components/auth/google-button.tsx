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

// GIS keeps one callback per page load and warns when initialize() runs again,
// which every client-side hop between /login and /register used to do. So it
// is initialized once, and the callback goes to whichever button is mounted.
let currentHandler: ((credential: string) => void) | null = null;
let initialized = false;

function initializeOnce(gsi: Gsi["accounts"]["id"]) {
  if (initialized) return;
  initialized = true;
  gsi.initialize({
    client_id: CLIENT_ID,
    callback: (response) => currentHandler?.(response.credential),
  });
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
  // Always hand GIS the latest handler (and so the latest form state).
  React.useEffect(() => {
    currentHandler = onCredential;
  }, [onCredential]);
  React.useEffect(
    () => () => {
      currentHandler = null;
    },
    [],
  );

  React.useEffect(() => {
    if (!CLIENT_ID) return;
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    loadScript()
      .then(() => {
        const el = ref.current;
        const gsi = window.google?.accounts.id;
        if (cancelled || !el || !gsi) return;
        initializeOnce(gsi);
        // Google draws the button at a fixed pixel width, so it is redrawn
        // when the column changes size (a phone turned upright would
        // otherwise keep the wide button and scroll sideways).
        let drawnWidth = 0;
        const draw = () => {
          const width = Math.min(400, Math.floor(el.clientWidth) || 320);
          if (width === drawnWidth) return;
          drawnWidth = width;
          gsi.renderButton(el, {
            type: "standard",
            theme: "outline",
            size: "large",
            shape: "pill",
            text,
            // The site is English; left to itself Google guesses a language
            // from the visitor's machine and can label the button in another.
            locale: "en",
            width,
          });
        };
        draw();
        observer = new ResizeObserver(draw);
        observer.observe(el);
      })
      .catch(() => {
        /* No button is better than a broken one; email sign-in still works. */
      });
    return () => {
      cancelled = true;
      observer?.disconnect();
    };
  }, [text]);

  if (!CLIENT_ID) return null;
  // contain: inline-size stops the drawn iframe from setting the column's
  // minimum width, so the column can shrink and the observer can redraw.
  return (
    <div
      ref={ref}
      className="flex min-h-[44px] w-full justify-center overflow-hidden [contain:inline-size]"
    />
  );
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
