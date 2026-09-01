"""Deterministic render check for the grid-derived floor plan.

Intercepts /listening/full-test with a hand-built plan: merged multi-cell
rooms, an L-shaped room, a corridor the rooms open onto, and both label
styles (lettered rooms and numbered blanks). No LLM call is involved, so a
failure here is the renderer's.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import Page, Route, sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"

CORS = {
    "Access-Control-Allow-Origin": BASE,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Credentials": "true",
}

LETTERED_PLAN = {
    "kind": "plan",
    "title": "Plan of the Riverside Community Centre",
    "grid": [
        ["Kitchen", "Kitchen", "A", "A", "B", "B", "Store Room", "Store Room"],
        ["corridor"] * 8,
        ["C", "C", "D", "D", "Reception", "Reception", "Reception", "Reception"],
        ["C", "corridor", "corridor", "corridor", "corridor", "corridor", "corridor", "corridor"],
        ["E", "E", "F", "F", "G", "G", "Main Hall", "Main Hall"],
    ],
    "entrance": {"side": "left", "index": 1, "label": "Main entrance"},
}

BLANK_PLAN = {
    "kind": "plan",
    "title": "Ferry terminal, upper level",
    "grid": [
        ["", "Ticket Office", "Ticket Office", "__11__", "__11__", ""],
        ["corridor", "corridor", "corridor", "corridor", "corridor", "corridor"],
        ["__12__", "__12__", "Cafe", "Cafe", "__13__", "__13__"],
    ],
    "entrance": {"side": "bottom", "index": 2, "label": "Stairs from ground floor"},
}


# A Reading diagram has no corridor, so it must come out with unbroken
# outlines — soil layers do not have doorways between them.
DIAGRAM_PLAN = {
    "kind": "plan",
    "title": "Cross-section of a termite mound",
    "grid": [
        ["", "__6__", ""],
        ["Outer wall", "Ventilation shaft", "Outer wall"],
        ["Outer wall", "__7__", "Outer wall"],
        ["Fungus garden", "Fungus garden", "__8__"],
    ],
}


# What a live hosted generation actually returned (2026-08-21). Kept because
# a real diagram is wordier than a hand-built one: 'Thread take-up' and
# 'Tension discs' have to sit inside cells the renderer also uses for a single
# letter, and its footprint is ragged along the top row.
LIVE_DIAGRAM = {
    "kind": "plan",
    "title": "Cross-section of a sewing machine",
    "grid": [
        ["Hand crank", "Gear system", ""],
        ["Shuttle", "__1__", "Bobbin"],
        ["Needle", "Thread take-up", "Tension discs"],
        ["Presser foot", "Feed dogs", "Sole plate"],
    ],
}

def build_fixture() -> dict:
    data = json.loads(Path("tools/_fixture_fulltest.json").read_text(encoding="utf-8"))
    parts = data["parts"]
    for index, plan in ((0, LIVE_DIAGRAM), (1, LETTERED_PLAN),
                        (2, BLANK_PLAN), (3, DIAGRAM_PLAN)):
        parts[index] = copy.deepcopy(parts[index])
        parts[index]["visual"] = plan
    return data


FIXTURE = build_fixture()


def auth_state() -> dict:
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


def shoot(page: Page, theme: str) -> int:
    figs = page.locator("figure[aria-label^='Plan:']")
    count = figs.count()
    for i in range(count):
        fig = figs.nth(i)
        fig.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        name = f"plan_{theme}_{i}.png"
        fig.screenshot(path=str(OUT / name))
        print(f"  [shot] {name}")
    return count


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900}, color_scheme=theme
            )
            page = ctx.new_page()
            page.on("pageerror", lambda e: failures.append(f"[pageerror] {e}"))
            page.route("**/listening/full-test", handle_full_test)

            page.goto(f"{BASE}/login", wait_until="domcontentloaded")
            page.evaluate(
                "([k, v]) => window.localStorage.setItem(k, v)",
                ["ai-ielts-auth", json.dumps(auth_state())],
            )
            page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
            page.get_by_role("button", name="Generate full test").click()
            page.get_by_role("button", name="Submit test", exact=False).wait_for(
                state="visible", timeout=20000
            )

            plans = shoot(page, theme)
            print(f"[{theme}] plan figures = {plans}")
            # Four, because `build_fixture` puts four of them on the page.
            # This read 3 from the commit that introduced it (`ed4c80d`) —
            # written against three fixtures and not updated when the live
            # sewing machine was added as the fourth — so the check had never
            # passed. Verified 2026-08-28 by screenshot: all four draw.
            if plans != 4:
                failures.append(f"[{theme}] expected 4 plan figures, saw {plans}")
            ctx.close()
        browser.close()

    print("\nfailures:", failures or "(none)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
