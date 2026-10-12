"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

/** What a new account agrees to. One wording for every way of signing up. */
export function ConsentText() {
  return (
    <span>
      I have read and agree to the{" "}
      <Link href="/terms" target="_blank" className="text-foreground underline underline-offset-4">
        Terms
      </Link>{" "}
      and{" "}
      <Link href="/privacy" target="_blank" className="text-foreground underline underline-offset-4">
        Privacy Policy
      </Link>
      , including my essays and recordings being processed by the service
      providers named there, some outside Bangladesh. I am 18 or older, or
      my parent or guardian agrees.
    </span>
  );
}

/**
 * Shown on the login page when Google hands back an address with no account:
 * the student agrees here and the account is made from the same Google
 * credential, instead of being sent off to start again on another page.
 */
export function FinishGoogleSignUp({
  onCreate,
  onCancel,
}: {
  onCreate: () => Promise<void>;
  onCancel: () => void;
}) {
  const [accepted, setAccepted] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const create = async () => {
    setBusy(true);
    try {
      await onCreate();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-sm font-medium text-foreground">
        There&apos;s no Oratio account for this Google address yet.
      </p>
      <p className="mt-1 text-sm text-muted-foreground">Create one now. It&apos;s free.</p>
      <label className="mt-4 flex items-start gap-3 text-sm leading-relaxed text-muted-foreground">
        <input
          type="checkbox"
          className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        <ConsentText />
      </label>
      <Button
        type="button"
        className="mt-4 w-full"
        size="lg"
        disabled={!accepted}
        loading={busy}
        onClick={create}
      >
        Create my account
      </Button>
      <button
        type="button"
        onClick={onCancel}
        className="mt-3 w-full text-center text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
      >
        Use a different Google account
      </button>
    </div>
  );
}
