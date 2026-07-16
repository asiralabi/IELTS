"""Live browser verification of Listening + Speaking flows.

- Cambridge listening loader (no audio, expect note)
- Default AI listening page (start screen)
- Default AI speaking page (start screen)
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

BASE = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"


def shot(page: Page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [shot] {path.name}")


def wait_for_hydrate(page: Page, min_chars: int = 40, tries: int = 30) -> str:
    for _ in range(tries):
        text = page.locator("body").inner_text().strip()
        if len(text) >= min_chars:
            return text
        page.wait_for_timeout(500)
    return page.locator("body").inner_text().strip()


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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

        print("[1] auth seed ...")
        auth_blob = get_auth_state()
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_blob)],
        )

        # ------------------------------------------------------------------
        # 1. Cambridge listening loader
        print("\n[2] /listening?book=cambridge-18&test=1&part=1 ...")
        page.goto(
            f"{BASE}/listening?book=cambridge-18&test=1&part=1",
            wait_until="domcontentloaded",
        )
        text = wait_for_hydrate(page, min_chars=200, tries=40)
        page.wait_for_timeout(2500)
        shot(page, "cam_60_listening_cambridge")
        text_now = page.locator("body").inner_text()
        has_note = "Paper-based only" in text_now
        # Player button should be hidden (no audio_script)
        play_btns = page.locator("button[aria-label*='Play audio' i]").count()
        print(
            f"    body chars={len(text_now)}  note-shown={has_note}  play-buttons={play_btns}"
        )

        # ------------------------------------------------------------------
        # 2. Default /listening (AI mode start screen)
        print("\n[3] /listening (default AI landing) ...")
        page.goto(f"{BASE}/listening", wait_until="domcontentloaded")
        wait_for_hydrate(page, min_chars=100)
        shot(page, "cam_61_listening_default")
        listen_text = page.locator("body").inner_text()
        has_generate = "Generate a recording" in listen_text
        print(f"    'Generate a recording' visible: {has_generate}")

        # ------------------------------------------------------------------
        # 3. Default /speaking (AI mode start screen)
        print("\n[4] /speaking (default AI landing) ...")
        page.goto(f"{BASE}/speaking", wait_until="domcontentloaded")
        wait_for_hydrate(page, min_chars=100)
        shot(page, "cam_70_speaking_default")
        speak_text = page.locator("body").inner_text()
        # Speaking page uses different button text; enumerate visible buttons
        buttons = [
            b.inner_text().strip()
            for b in page.locator("button").all()
            if b.inner_text().strip()
        ]
        print(f"    body chars={len(speak_text)}  buttons={buttons[:8]}")

        # ------------------------------------------------------------------
        print("\n[5] console log tail:")
        for line in logs[-20:]:
            print(f"    {line}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
