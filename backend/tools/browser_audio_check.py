"""Live browser click-through of the neural Listening audio.

Generates a single-part AI recording, clicks Play, and asserts the frontend
fetched the backend MP3 blob and actually started playback (audio element
advancing), plus the 2-play badge incremented. Prod build only (headless
Next.js dev renders blank — see project memory).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, Page

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3200"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"


def shot(page: Page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [shot] {path.name}")


def get_auth_state() -> dict:
    r = httpx.post(
        f"{API}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    tokens = r.json()
    me = httpx.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )
    me.raise_for_status()
    return {
        "state": {
            "accessToken": tokens["access_token"],
            "refreshToken": tokens["refresh_token"],
            "user": me.json(),
        },
        "version": 0,
    }


def main() -> int:
    audio_responses: list[tuple[int, str, int]] = []  # (status, content-type, bytes)
    ok = True

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

        def on_response(resp):
            if "/listening/audio" in resp.url:
                try:
                    body_len = len(resp.body())
                except Exception:
                    body_len = -1
                audio_responses.append(
                    (resp.status, resp.headers.get("content-type", "?"), body_len)
                )

        page.on("response", on_response)

        print("[1] auth seed ...")
        auth_blob = get_auth_state()
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_blob)],
        )

        print("[2] /listening (AI landing) ...")
        page.goto(f"{BASE}/listening", wait_until="domcontentloaded")
        page.get_by_role("button", name="Generate a recording").wait_for(timeout=20000)
        shot(page, "audio_10_landing")

        print("[3] generate recording (real LLM, may take ~30-60s) ...")
        page.get_by_role("button", name="Generate a recording").click()
        play_btn = page.get_by_role("button", name="Play audio")
        play_btn.wait_for(timeout=180000)  # generation
        shot(page, "audio_20_player")
        print("    player rendered")

        plays_before = page.get_by_text("Plays used:").inner_text()
        print(f"    badge before: {plays_before!r}")

        print("[4] click Play -> fetch blob (synthesis can take ~30-90s) ...")
        with page.expect_response(
            lambda r: "/listening/audio" in r.url, timeout=180000
        ) as resp_info:
            play_btn.click()
        resp = resp_info.value
        print(f"    audio response: {resp.status} {resp.headers.get('content-type')}")

        print("[5] confirm playback advances ...")
        # Wait for the audio element to load a src and start advancing.
        state = {}
        for _ in range(40):
            page.wait_for_timeout(500)
            state = page.evaluate(
                """() => {
                    const a = document.querySelector('audio');
                    if (!a) return {found:false};
                    return {
                        found:true, hasSrc: !!a.src, srcBlob: a.src.startsWith('blob:'),
                        paused: a.paused, readyState: a.readyState,
                        currentTime: a.currentTime, duration: a.duration,
                    };
                }"""
            )
            if state.get("found") and state.get("currentTime", 0) > 0.15:
                break
        print(f"    audio state: {state}")
        page.wait_for_timeout(500)
        badge_after = page.get_by_text("Plays used:").inner_text()
        print(f"    badge after: {badge_after!r}")
        shot(page, "audio_30_playing")

        # -------------------- assertions --------------------
        print("\n[6] results:")
        got_audio = any(s == 200 and "audio/mpeg" in ct for s, ct, _ in audio_responses)
        print(f"    /listening/audio responses: {audio_responses}")
        checks = {
            "audio blob fetched 200 audio/mpeg": got_audio,
            "audio element has blob src": bool(state.get("srcBlob")),
            "playback advanced (currentTime>0.15)": state.get("currentTime", 0) > 0.15,
            "play badge -> 1/2": "1/2" in badge_after,
            "no page errors": not any("pageerror" in l for l in logs),
        }
        for name, passed in checks.items():
            print(f"    [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed

        errs = [l for l in logs if "pageerror" in l or "[error]" in l]
        if errs:
            print("\n    console errors:")
            for l in errs[-10:]:
                print(f"      {l}")

        browser.close()

    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
