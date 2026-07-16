"""Live browser verification of the full 4-part / 40-question Listening test.

Flow:
- seed demo auth via localStorage
- open /listening/test, generate a full test (4 parts, 40 questions)
- verify 4 Part badges, table + map figures, per-part audio players, 40 inputs
- fill answers, submit, verify band-score summary + per-part cards render
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, Page

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"

GEN_TIMEOUT_MS = 540_000  # generating 4 parts against a remote 70B model is slow
CHECK_TIMEOUT_MS = 300_000


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

        print("\n[2] /listening/test start screen ...")
        page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
        wait_for_hydrate(page, min_chars=120)
        shot(page, "ft_00_start")
        has_cta = page.get_by_role("button", name="Generate full test").count() > 0
        print(f"    'Generate full test' button visible: {has_cta}")

        print("\n[3] generating full test (up to 6 min) ...")
        page.get_by_role("button", name="Generate full test").click()
        # answering phase is reached when the sticky Submit button appears
        submit = page.get_by_role("button", name="Submit test", exact=False)
        submit.wait_for(state="visible", timeout=GEN_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        shot(page, "ft_10_answering")

        part_badges = page.get_by_text("Part ", exact=False)
        # Count the Part N section badges specifically (Badge component)
        n_parts = page.locator("text=/^Part [1-4]$/").count()
        maps = page.locator("figure[aria-label^='Map:']").count()
        tables = page.locator("figure[aria-label*='table chart']").count()
        play_btns = page.locator("button[aria-label='Play audio']").count()
        text_inputs = page.locator(
            "input[aria-label^='Answer to question']"
        ).count()
        option_btns = page.locator("button:has(> span:only-child)").count()
        print(
            f"    part-badges~={n_parts}  map-figs={maps}  table-figs={tables}\n"
            f"    play-buttons={play_btns}  text-inputs={text_inputs}"
        )

        # snapshot just the map figure if present
        if maps:
            page.locator("figure[aria-label^='Map:']").first.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.locator("figure[aria-label^='Map:']").first.screenshot(
                path=str(OUT / "ft_11_map_figure.png")
            )
            print("  [shot] ft_11_map_figure.png")
        if tables:
            page.locator("figure[aria-label*='table chart']").first.screenshot(
                path=str(OUT / "ft_12_table_figure.png")
            )
            print("  [shot] ft_12_table_figure.png")

        print("\n[4] filling answers ...")
        inputs = page.locator("input[aria-label^='Answer to question']")
        n_in = inputs.count()
        for i in range(n_in):
            inputs.nth(i).fill("A")
        # click the first option button in each multiple-choice question
        mc_first = page.locator("li:has(button[type='button']) button[type='button']")
        # only click ones that look like option buttons (single-letter badge)
        filled_mc = 0
        for li in page.locator("li").all():
            opt = li.locator("button[type='button']").first
            if opt.count() and li.locator(
                "input[aria-label^='Answer to question']"
            ).count() == 0:
                try:
                    opt.click()
                    filled_mc += 1
                except Exception:
                    pass
        print(f"    filled text-inputs={n_in}  clicked mc-first={filled_mc}")
        page.wait_for_timeout(400)

        print("\n[5] submitting for marking (up to 4 min) ...")
        submit = page.get_by_role("button", name="Submit test", exact=False)
        submit.click()
        done = page.get_by_text("correct answers", exact=False)
        done.wait_for(state="visible", timeout=CHECK_TIMEOUT_MS)
        page.wait_for_timeout(1200)
        shot(page, "ft_20_done")

        body = page.locator("body").inner_text()
        has_band = "Estimated band" in body
        has_partcards = body.count("Part 4") >= 1
        print(f"    band-shown={has_band}  score-summary rendered={has_partcards}")

        print("\n[6] console/page-error tail:")
        errs = [ln for ln in logs if "[pageerror]" in ln or "[error]" in ln]
        if not errs:
            print("    (no page errors / console errors)")
        for line in errs[-20:]:
            print(f"    {line}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
