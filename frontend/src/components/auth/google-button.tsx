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

// Google refuses to sign anyone in from inside another app's built-in browser
// ("403 disallowed_useragent"), and links shared on Messenger or Facebook open
// in exactly that. Those visitors are told to open the page in a real browser.
const IN_APP_BROWSER =
  /FBAN|FBAV|FB_IAB|FBIOS|Messenger|Instagram|Line\/|MicroMessenger|Snapchat|TikTok|musical_ly|BytedanceWebview|; wv\)/i;

type ButtonState = "loading" | "ready" | "failed";

const noSubscribe = () => () => {};

export function GoogleButton({
  text,
  onCredential,
}: {
  text: GsiButtonText;
  onCredential: (credential: string) => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [state, setState] = React.useState<ButtonState>("loading");
  // Read after hydration only: the server has no user agent to test.
  const inApp = React.useSyncExternalStore(
    noSubscribe,
    () => IN_APP_BROWSER.test(navigator.userAgent),
    () => false,
  );

  // Always hand GIS the latest handler (and so the latest form state). The
  // cleanup only clears the slot if it is still ours, so a page that unmounts
  // after the next one mounted cannot switch the next one's button off.
  React.useEffect(() => {
    currentHandler = onCredential;
    return () => {
      if (currentHandler === onCredential) currentHandler = null;
    };
  }, [onCredential]);

  React.useEffect(() => {
    if (!CLIENT_ID || inApp) return;
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    loadScript()
      .then(() => {
        const el = ref.current;
        const gsi = window.google?.accounts.id;
        if (cancelled || !el) return;
        if (!gsi) throw new Error("Google sign-in did not start");
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
        setState("ready");
      })
      .catch(() => {
        // Usually an ad or tracker blocker, or a network that blocks Google.
        if (!cancelled) setState("failed");
      });
    return () => {
      cancelled = true;
      observer?.disconnect();
    };
  }, [text, inApp]);

  if (!CLIENT_ID) return null;
  if (inApp) return <InAppBrowserNotice />;
  if (state === "failed") {
    return (
      <p className="rounded-xl border border-border bg-card p-4 text-center text-sm text-muted-foreground">
        Google sign-in couldn&apos;t load here. An ad blocker or your network may be
        stopping it. Use your email and password, or try another browser.
      </p>
    );
  }
  // contain: inline-size stops the drawn iframe from setting the column's
  // minimum width, so the column can shrink and the observer can redraw.
  return (
    <div
      ref={ref}
      className="flex min-h-[44px] w-full justify-center overflow-hidden [contain:inline-size]"
    />
  );
}

function InAppBrowserNotice() {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      /* Some in-app browsers block the clipboard; the steps above still work. */
    }
  };
  return (
    <div className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
      <p className="font-medium text-foreground">Google sign-in doesn&apos;t work inside this app.</p>
      <p className="mt-1">
        Open this page in Chrome or Safari: tap the <span aria-hidden>⋮</span> or share menu
        and choose &ldquo;Open in browser&rdquo;. Email and password work here too.
      </p>
      <button
        type="button"
        onClick={copy}
        className="mt-3 text-xs font-medium text-foreground underline underline-offset-4"
      >
        {copied ? "Link copied. Paste it into your browser." : "Copy link to this page"}
      </button>
    </div>
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
