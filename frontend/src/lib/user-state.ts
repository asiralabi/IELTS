"use client";

import { api } from "./api";
import { useAuth } from "./store";

/**
 * Progress the browser shows from its own localStorage copy (Cambridge ticks,
 * vocabulary cards), mirrored to the student's account so it survives a
 * sign-out and follows them to another device. Signing out clears the local
 * copy (see `logout` in store.ts); signing in pulls it back.
 */

export type StateKey = "cambridge" | "vocab";

export const STATE_STORAGE: Record<StateKey, { storage: string; event: string }> = {
  cambridge: { storage: "ai-ielts-cambridge-progress", event: "ai-ielts-cambridge-progress" },
  vocab: { storage: "ai-ielts-vocab", event: "ai-ielts-vocab" },
};

type Json = Record<string, unknown>;

function readLocal(key: StateKey): Json {
  try {
    const parsed = JSON.parse(localStorage.getItem(STATE_STORAGE[key].storage) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeLocal(key: StateKey, value: Json): void {
  try {
    localStorage.setItem(STATE_STORAGE[key].storage, JSON.stringify(value));
    window.dispatchEvent(new CustomEvent(STATE_STORAGE[key].event));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

/** Save to the account. Fire and forget: the local copy already has it. */
export function pushUserState(key: StateKey, value: Json): void {
  if (!useAuth.getState().accessToken) return;
  api.saveUserState(key, value).catch(() => {
    /* offline: the next sign-in merges the local copy back up */
  });
}

/** Deep merge for nested progress maps; the newer timestamp wins on a clash. */
function merge(a: Json, b: Json): Json {
  const out: Json = { ...a };
  for (const [k, v] of Object.entries(b)) {
    const prev = out[k];
    if (
      prev && v && typeof prev === "object" && typeof v === "object" &&
      !("timestamp" in (v as Json))
    ) {
      out[k] = merge(prev as Json, v as Json);
    } else if (
      prev && v && typeof prev === "object" && typeof v === "object" &&
      Number((prev as Json).timestamp) > Number((v as Json).timestamp)
    ) {
      out[k] = prev;
    } else {
      out[k] = v;
    }
  }
  return out;
}

/** After sign-in: combine the account's copy with anything saved here while
 *  offline, keep both sides equal, and tell open pages to re-read. */
export async function syncUserState(): Promise<void> {
  const server = (await api.userState()) as Partial<Record<StateKey, Json>>;
  for (const key of Object.keys(STATE_STORAGE) as StateKey[]) {
    const local = readLocal(key);
    const remote = server[key] ?? {};
    const merged = merge(local, remote);
    writeLocal(key, merged);
    if (JSON.stringify(merged) !== JSON.stringify(remote)) pushUserState(key, merged);
  }
}
