"""Deterministic render check for the Listening figures.

Intercepts the /listening/full-test call and returns a fixed, pre-normalized
payload (a deliberately hard map: landmarks clustered on a corridor + rooms),
so we can screenshot the MapBlock / table renderer without waiting on the LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, Page, Route

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8000"
ORIGIN = BASE
EMAIL = "demo@example.com"
PASSWORD = "demo1234"

FIXTURE = json.loads(Path("tools/_fixture_fulltest.json").read_text(encoding="utf-8"))

CORS = {
    "Access-Control-Allow-Origin": ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Credentials": "true",
}


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


def handle_full_test(route: Route) -> None:
    if route.request.method == "OPTIONS":
        route.fulfill(status=204, headers=CORS)
        return
    route.fulfill(
        status=200,
        headers={"Content-Type": "application/json", **CORS},
        body=json.dumps(FIXTURE),
    )


def snap(page: Page) -> None:
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / "map_00_full.png"), full_page=True)
    print("  [shot] map_00_full.png")
    m = page.locator("figure[aria-label^='Map:']")
    if m.count():
        m.first.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        m.first.screenshot(path=str(OUT / "map_10_map.png"))
        print("  [shot] map_10_map.png")
    t = page.locator("figure[aria-label*='table chart']")
    if t.count():
        t.first.screenshot(path=str(OUT / "map_11_table.png"))
        print("  [shot] map_11_table.png")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        errors: list[str] = []
        for theme in ("light", "dark"):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme=theme,
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
            page.route("**/listening/full-test", handle_full_test)

            auth_blob = get_auth_state()
            page.goto(f"{BASE}/login", wait_until="domcontentloaded")
            page.evaluate(
                "([k, v]) => window.localStorage.setItem(k, v)",
                ["ai-ielts-auth", json.dumps(auth_blob)],
            )
            page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
            page.get_by_role("button", name="Generate full test").wait_for(
                state="visible", timeout=15000
            )
            print(f"\n[{theme}] generating (intercepted) ...")
            page.get_by_role("button", name="Generate full test").click()
            page.get_by_role("button", name="Submit test", exact=False).wait_for(
                state="visible", timeout=20000
            )
            maps = page.locator("figure[aria-label^='Map:']").count()
            tables = page.locator("figure[aria-label*='table chart']").count()
            parts = page.locator("text=/^Part [1-4]$/").count()
            print(f"    parts~={parts}  map-figs={maps}  table-figs={tables}")
            if theme == "light":
                snap(page)
            else:
                page.wait_for_timeout(500)
                m = page.locator("figure[aria-label^='Map:']")
                if m.count():
                    m.first.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    m.first.screenshot(path=str(OUT / "map_20_map_dark.png"))
                    print("  [shot] map_20_map_dark.png")
            ctx.close()

        print("\npage errors:", errors or "(none)")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
