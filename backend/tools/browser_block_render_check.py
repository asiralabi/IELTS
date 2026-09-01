"""Deterministic render check for the printed blocks and the picture choice.

Covers the three figure kinds added on 2026-08-27 to close the coverage gap
(`tools/figure_coverage.py`): the notes block, the summary block and
picture-choice. No LLM call is involved, so a failure here is the renderer's.

These matter because the engine used to say so in the prompt: "No summary or
note block is printed on screen — only the question text you write". Every
note and summary item carried its own context inline and the student never saw
the block the rubric named, which is the commonest figure the exam prints.

Run with the backend on :8000 and a production frontend build on :3100.

Usage: PYTHONIOENCODING=utf-8 python tools/browser_block_render_check.py
"""

from __future__ import annotations

import copy
import json
import re
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

# Cambridge IELTS 11 T2, Listening Part 2 — the shape of a real notes block:
# headed groups, some lines gapped and some not, gaps ascending down the page.
FIELD_TRIP_NOTES = {
    "kind": "notes",
    "style": "notes",
    "title": "Field trip to Bramley Farm",
    "sections": [
        {
            "heading": "Before the visit",
            "lines": [
                "Bring waterproof boots and a __11__",
                "Meet outside the library at 8.15am",
                "Cost of the coach is £__12__ per student",
            ],
        },
        {
            "heading": "At the farm",
            "lines": [
                "The tour begins in the dairy",
                "Photography is not allowed in the __13__",
                "Lunch is taken in the visitor centre",
            ],
        },
    ],
}

# The same kind in its other typography. A summary is prose, so its lines are
# sentences of one paragraph — set as bullets it would read as notes, which is
# exactly the distinction this proves.
GLASS_SUMMARY = {
    "kind": "notes",
    "style": "summary",
    "title": "Summary: the ribbon machine",
    "sections": [
        {
            "heading": "",
            "lines": [
                "Molten glass is poured onto a moving __14__, where it is",
                "flattened into a continuous ribbon. The ribbon passes over a",
                "series of rollers and is cooled slowly so that internal __15__",
                "does not build up. Finished sheets are then cut to length and",
                "stacked for __16__.",
            ],
        }
    ],
}

# A picture-choice question: the same three parts in three different orders, so
# the pictures differ in the ONE thing the question asks about.
FILTER_PICTURES = {
    "kind": "picture",
    "title": "Which shows the correct filter position?",
    "choices": [
        {
            "letter": "A",
            "layout": "apparatus",
            "parts": [
                {"id": "tank", "form": "tank", "name": "Tank"},
                {"id": "filter", "form": "valve"},
                {"id": "pump", "form": "disc"},
            ],
            "labels": [],
        },
        {
            "letter": "B",
            "layout": "apparatus",
            "parts": [
                {"id": "tank", "form": "tank", "name": "Tank"},
                {"id": "pump", "form": "disc"},
                {"id": "filter", "form": "valve"},
            ],
            "labels": [],
        },
        {
            "letter": "C",
            "layout": "apparatus",
            "parts": [
                {"id": "filter", "form": "valve"},
                {"id": "tank", "form": "tank", "name": "Tank"},
                {"id": "pump", "form": "disc"},
            ],
            "labels": [],
        },
    ],
}

FIGURES = (FIELD_TRIP_NOTES, GLASS_SUMMARY, FILTER_PICTURES)

# What each must have on screen. The gap numbers are checked because a renderer
# that dropped the marker entirely would still pass a title check, and the raw
# `__n__` is checked ABSENT because a student must never see the marker.
EXPECT = {
    "Notes: Field trip to Bramley Farm": [
        "11", "12", "13", "Before the visit", "At the farm",
        "Meet outside the library",
    ],
    "Summary: Summary: the ribbon machine": [
        "14", "15", "16", "Molten glass is poured",
    ],
    "Pictures: Which shows the correct filter position?": ["A", "B", "C", "Tank"],
}


def build_fixture(figures: tuple[dict, ...]) -> dict:
    data = json.loads(Path("tools/_fixture_fulltest.json").read_text(encoding="utf-8"))
    parts = data["parts"]
    for index, figure in enumerate(figures):
        parts[index] = copy.deepcopy(parts[index])
        parts[index]["visual"] = figure
    # A part left carrying its own figure would render a fourth shape this pass
    # is not checking, and the count assertion would read as a failure.
    for part in parts[len(figures):]:
        part["visual"] = None
    return data


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


def serve(route: Route, fixture: dict) -> None:
    if route.request.method == "OPTIONS":
        route.fulfill(status=204, headers=CORS)
        return
    route.fulfill(
        status=200,
        headers={"Content-Type": "application/json", **CORS},
        body=json.dumps(fixture),
    )


def shoot(page: Page, theme: str) -> list[tuple[str, str]]:
    figs = page.locator(
        "figure[aria-label^='Notes:'], figure[aria-label^='Summary:'], "
        "figure[aria-label^='Pictures:']"
    )
    out = []
    for i in range(figs.count()):
        fig = figs.nth(i)
        fig.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        name = f"block_{theme}_{i}.png"
        fig.screenshot(path=str(OUT / name))
        print(f"  [shot] {name}")
        # Whitespace-collapsed: a line too long for its column wraps, and a raw
        # substring match would report a failure for text plainly on screen.
        out.append((fig.get_attribute("aria-label") or "",
                    " ".join(fig.inner_text().split())))
    return out


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"    {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            failures.append(label)

    fixture = build_fixture(FIGURES)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            print(f"\n== {theme} ==")
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 950}, color_scheme=theme
            )
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on(
                "console",
                lambda m: errors.append(f"console: {m.text}")
                if m.type == "error"
                else None,
            )
            page.route(
                "**/listening/full-test", lambda route: serve(route, fixture)
            )
            page.goto(f"{BASE}/login", wait_until="domcontentloaded")
            page.evaluate(
                "([k, v]) => window.localStorage.setItem(k, v)",
                ["ai-ielts-auth", json.dumps(auth_state())],
            )
            page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
            page.get_by_role("button", name="Generate full test").click()
            page.wait_for_selector("figure[aria-label^='Notes:']", timeout=60000)
            page.wait_for_timeout(600)

            drawn = shoot(page, theme)
            check("every block drew", len(drawn) == len(FIGURES),
                  f"{len(drawn)} of {len(FIGURES)}")
            for label, body in drawn:
                for want in EXPECT.get(label, []):
                    check(f"{label[:34]!r} shows {want!r}", want in body)
                check(f"{label[:34]!r} hides the raw marker", "__" not in body,
                      body[:60])
            # The picture choice must draw real ink, not three empty frames.
            shapes = page.locator(
                "figure[aria-label^='Pictures:'] svg path, "
                "figure[aria-label^='Pictures:'] svg rect, "
                "figure[aria-label^='Pictures:'] svg circle"
            )
            check("the pictures drew real shapes", shapes.count() >= 9,
                  f"{shapes.count()} shapes")
            check("no page or console errors", not errors, "; ".join(errors[:3]))
            ctx.close()
        browser.close()

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'ALL CHECKS PASSED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
