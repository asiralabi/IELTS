"""Live browser verification of the Cambridge picker + visuals feature.

Runs against http://127.0.0.1:8000 (backend) and http://127.0.0.1:3000
(frontend, prod build). Screenshots land under tools/browser_shots/.
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

        print("[1] auth seed via /auth/login ...")
        auth_blob = get_auth_state()
        print(f"    token starts {auth_blob['state']['accessToken'][:12]}")

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_blob)],
        )

        # ------------------------------------------------------------------
        # 1. Cambridge picker landing page
        print("\n[2] /cambridge — picker index ...")
        page.goto(f"{BASE}/cambridge", wait_until="domcontentloaded")
        text = wait_for_hydrate(page, min_chars=100)
        shot(page, "cam_10_index")
        book_ids = sorted(set(re.findall(r"Cambridge IELTS \d+", text)))
        print(f"    body chars={len(text)}  books listed={book_ids}")

        # Expand the first book so we can see per-test launchers
        try:
            btn = page.get_by_role("button", name=re.compile(r"Cambridge IELTS", re.I)).first
            btn.click(timeout=5000)
            page.wait_for_timeout(500)
            shot(page, "cam_11_expanded")
            expanded_text = page.locator("body").inner_text()
            has_launcher = "Reading 1" in expanded_text and "Writing 1" in expanded_text
            print(f"    expanded — launchers visible: {has_launcher}")
        except Exception as e:
            print(f"    ! expand failed: {e}")

        # ------------------------------------------------------------------
        # 2. Cambridge reading loader
        print("\n[3] /reading?book=cambridge-18&test=1&passage=1 ...")
        page.goto(
            f"{BASE}/reading?book=cambridge-18&test=1&passage=1",
            wait_until="domcontentloaded",
        )
        text = wait_for_hydrate(page, min_chars=300, tries=40)
        # Give the async loader another beat to complete
        page.wait_for_timeout(2500)
        shot(page, "cam_20_reading")
        text_now = page.locator("body").inner_text()
        has_passage = "Passage" in text_now or "READING PASSAGE" in text_now.upper()
        print(f"    body chars={len(text_now)}  passage rendered: {has_passage}")

        # ------------------------------------------------------------------
        # 3. Cambridge writing task 1 (chart visual)
        print("\n[4] /writing?book=cambridge-18&test=1&task=1 ...")
        page.goto(
            f"{BASE}/writing?book=cambridge-18&test=1&task=1",
            wait_until="domcontentloaded",
        )
        wait_for_hydrate(page, min_chars=200)
        page.wait_for_timeout(2500)
        shot(page, "cam_30_writing_task1")
        # Look for the "You should spend about 20 minutes on this task" text
        # (canonical Task 1 preamble).
        writing_text = page.locator("body").inner_text()
        preamble = "20 minutes" in writing_text and (
            "chart" in writing_text.lower() or "graph" in writing_text.lower() or "table" in writing_text.lower()
        )
        # Check for an <img> on the page (the Cambridge extracted chart)
        img_count = page.locator("img[src*='/assets/']").count()
        print(f"    preamble: {preamble}  cambridge-asset-imgs: {img_count}")

        # ------------------------------------------------------------------
        # 4. Default /writing page — no URL params, should show the AI flow
        print("\n[5] /writing (default AI mode) ...")
        page.goto(f"{BASE}/writing", wait_until="domcontentloaded")
        wait_for_hydrate(page, min_chars=100)
        shot(page, "cam_40_writing_default")
        default_text = page.locator("body").inner_text()
        has_generate_btn = "Generate AI prompt" in default_text
        print(f"    generate button visible: {has_generate_btn}")

        # ------------------------------------------------------------------
        # 5. Mock exam start page
        print("\n[6] /mock-test — landing ...")
        page.goto(f"{BASE}/mock-test", wait_until="domcontentloaded")
        wait_for_hydrate(page, min_chars=100)
        shot(page, "cam_50_mock_start")
        mock_text = page.locator("body").inner_text()
        has_generate = "Generate my exam" in mock_text
        print(f"    'Generate my exam' visible: {has_generate}")

        # ------------------------------------------------------------------
        print("\n[7] console log tail:")
        for line in logs[-20:]:
            print(f"    {line}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
