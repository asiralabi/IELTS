"""Live browser click-through of the FULL 4-part Listening test audio.

Generates a complete 4-part test, then for each part clicks Play and asserts
the frontend fetched that part's neural MP3 (``/listening/audio/{id}?part=N``)
and playback started. Slow: 4-part LLM generation + four sequential syntheses
(each a multi-turn edge-tts clip). Prod build only.

Run with:  PYTHONIOENCODING=utf-8 python tools/browser_fulltest_audio_check.py
"""

from __future__ import annotations

import json
import re
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
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  [shot] {name}.png")


def get_auth_state() -> dict:
    r = httpx.post(
        f"{API}/auth/login", data={"username": EMAIL, "password": PASSWORD}, timeout=15
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
    audio_hits: list[tuple[str, int, str, int]] = []  # (url, status, ctype, bytes)
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
                    n = len(resp.body())
                except Exception:
                    n = -1
                audio_hits.append(
                    (resp.url, resp.status, resp.headers.get("content-type", "?"), n)
                )

        page.on("response", on_response)

        print("[1] auth seed ...")
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(get_auth_state())],
        )

        print("[2] /listening/test ...")
        page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
        page.get_by_role("button", name="Generate full test").wait_for(timeout=20000)
        shot(page, "ft_10_landing")

        print("[3] generate full 4-part test (real LLM, can take several minutes) ...")
        page.get_by_role("button", name="Generate full test").click()
        # First part player appears once the whole test payload arrives.
        page.get_by_role("button", name="Play audio").first.wait_for(timeout=600000)
        n_players = page.get_by_role("button", name="Play audio").count()
        print(f"    parts rendered with a Play button: {n_players}")
        ok = ok and (n_players == 4)
        shot(page, "ft_20_generated")

        print("[4] play each part in turn (synthesis ~30-90s each) ...")
        for i in range(n_players):
            # Playing parts flip their label to 'Stop audio', so the first
            # remaining 'Play audio' button is always the next unplayed part.
            btn = page.get_by_role("button", name="Play audio").first
            with page.expect_response(
                lambda r: "/listening/audio" in r.url, timeout=180000
            ) as info:
                btn.click()
            resp = info.value
            m = re.search(r"part=(\d+)", resp.url)
            part = m.group(1) if m else "?"
            print(
                f"    part {part}: {resp.status} {resp.headers.get('content-type')}"
            )
            # let this part's element start advancing
            for _ in range(30):
                page.wait_for_timeout(500)
                playing = page.evaluate(
                    """() => Array.from(document.querySelectorAll('audio'))
                        .filter(a => !a.paused && a.currentTime > 0.15).length"""
                )
                if playing >= i + 1:
                    break

        advanced = page.evaluate(
            """() => Array.from(document.querySelectorAll('audio')).map(a => ({
                srcBlob: a.src.startsWith('blob:'), paused: a.paused,
                t: a.currentTime, ready: a.readyState,
            }))"""
        )
        shot(page, "ft_30_playing")

        # -------------------- assertions --------------------
        print("\n[5] results:")
        print(f"    audio elements: {advanced}")
        parts_fetched = sorted(
            {re.search(r"part=(\d+)", u).group(1) for u, *_ in audio_hits if "part=" in u}
        )
        all_ok_type = all(s == 200 and "audio/mpeg" in ct for _, s, ct, _ in audio_hits)
        playing_now = sum(1 for a in advanced if a["srcBlob"] and a["t"] > 0.15)
        checks = {
            "4 part players rendered": n_players == 4,
            "all 4 parts fetched (1,2,3,4)": parts_fetched == ["1", "2", "3", "4"],
            "every audio response 200 audio/mpeg": all_ok_type and len(audio_hits) >= 4,
            "all 4 audio elements advancing": playing_now == 4,
            "no page errors": not any("pageerror" in l for l in logs),
        }
        for name, passed in checks.items():
            print(f"    [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        print(f"    parts fetched: {parts_fetched}  bytes: "
              f"{[n for *_, n in audio_hits]}")

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
