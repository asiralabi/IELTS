"""Deterministic render check for the drawn labelled diagram.

Intercepts /listening/full-test with hand-built figures — one per layout, plus
the two real Cambridge diagrams that motivated the schema and the live payload
the OLD engine produced. No LLM call is involved, so a failure here is the
renderer's.

The diagram is the figure the exam prints most often in Reading and the one the
engine could not draw at all: `prompts.py` answered `diagram_label_completion`
with `kind: "plan"`, the grid the floor plan uses, so a live set titled
"Cross-section of a Sewing Machine" rendered as seven text boxes in a Tetris
shape. This check exists because no backend test can see that — the payload was
valid, `visual_slots` returned 1-5, and the loss happened only at render.

Run with the backend on :8000 and a production frontend build on :3100.

Usage: PYTHONIOENCODING=utf-8 python tools/browser_diagram_render_check.py
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


# Cambridge IELTS 9 T3, Reading Questions 23-26 — the apparatus diagram the
# book prints, as the schema now expresses it. An assembly with a part hung off
# its side, which is the case that used to put two leader lines in one place.
UNDERSEA_TURBINE = {
    "kind": "diagram",
    "title": "An Undersea Turbine",
    "layout": "apparatus",
    "parts": [
        {"id": "rotor", "form": "rotor"},
        {"id": "housing", "form": "chamber", "name": "Generator housing"},
        {"id": "tower", "form": "column"},
        {"id": "seabed", "form": "ground", "name": "Sea bed"},
        {"id": "cable", "form": "pipe", "attach": "left", "to": "tower"},
    ],
    "labels": [
        {"at": "rotor", "text": "__23__", "side": "right"},
        {"at": "housing", "text": "__24__", "side": "right"},
        {"at": "tower", "text": "Whole tower can be raised", "side": "left"},
        {"at": "cable", "text": "__25__", "side": "left"},
        {"at": "seabed", "text": "__26__", "side": "right"},
    ],
}

# The exact figure the OLD engine returned live on 2026-08-24 and rendered as a
# Tetris block of seven boxes, rewritten into the schema that replaced the
# grid. Kept for the same reason the flow check keeps its live chart: this is
# the thing the user saw and called too basic.
SEWING_MACHINE = {
    "kind": "diagram",
    "title": "Cross-section of a Sewing Machine",
    "layout": "apparatus",
    "parts": [
        {"id": "spool", "form": "disc"},
        {"id": "guide", "form": "pipe"},
        {"id": "arm", "form": "chamber", "name": "Thread guide"},
        {"id": "needle", "form": "valve"},
        {"id": "plate", "form": "platform"},
        {"id": "bobbin", "form": "disc", "name": "Bobbin"},
        {"id": "base", "form": "box"},
        {"id": "wheel", "form": "disc", "attach": "right", "to": "arm"},
    ],
    "labels": [
        {"at": "spool", "text": "__1__", "side": "left"},
        {"at": "needle", "text": "__2__", "side": "left"},
        {"at": "plate", "text": "__3__", "side": "right"},
        {"at": "wheel", "text": "__4__", "side": "right"},
        {"at": "base", "text": "__5__", "side": "left"},
    ],
}

# Cambridge IELTS 2 T1, Reading — "Cross-section of the same area at the time
# the article was written": granite runways, mud, water, stiff clay, sand.
AIRPORT_STRATA = {
    "kind": "diagram",
    "title": "Cross-section of the airport site",
    "layout": "layers",
    "parts": [
        {"id": "terminal", "form": "band", "name": "Terminal building"},
        {"id": "runway", "form": "band", "name": "Granite runways and taxiways"},
        {"id": "mud", "form": "soil", "name": "__10__"},
        {"id": "water", "form": "water", "name": "Water"},
        {"id": "clay", "form": "clay", "name": "__11__"},
        {"id": "sand", "form": "sand", "name": "Sand"},
    ],
    "labels": [{"at": "runway", "text": "__12__", "side": "right"}],
}

# Cambridge IELTS 7 T3, Listening — "THE OPERATIONAL CYCLE". Six stages is the
# count that exposed the ring sizing: at a fixed radius the boxes sat shoulder
# to shoulder and every arc between them was hidden behind paper.
OPERATIONAL_CYCLE = {
    "kind": "diagram",
    "title": "The Operational Cycle",
    "layout": "cycle",
    "parts": [
        {"id": "drop", "name": "Float dropped into ocean"},
        {"id": "sink", "name": "Float sinks to __21__ metres"},
        {"id": "record", "name": "Records changes in __22__"},
        {"id": "rise", "name": "Float returns to surface"},
        {"id": "send", "name": "Data sent by __23__"},
        {"id": "analyse", "name": "Information is analysed"},
    ],
    "labels": [],
}

# Cambridge IELTS 3 T2, Reading — "Dung Beetle Types". Four siblings on the
# bottom row is the count that overlapped at a fixed box width, and the level
# ordering is what stops the connectors crossing.
DUNG_BEETLES = {
    "kind": "diagram",
    "title": "Dung Beetle Types",
    "layout": "tree",
    "parts": [
        {"id": "beetles", "name": "Dung beetles"},
        {"id": "rollers", "name": "Ball rollers", "parent": "beetles"},
        {"id": "tunnellers", "name": "__6__", "parent": "beetles"},
        {"id": "french", "name": "French", "parent": "tunnellers"},
        {"id": "spanish", "name": "__7__", "parent": "tunnellers"},
        {"id": "african", "name": "South African", "parent": "rollers"},
        {"id": "native", "name": "__8__", "parent": "rollers"},
    ],
    "labels": [],
}

# Cambridge IELTS 9 T4, Listening — the "Water Heater" controls. A panel prints
# its numbers ON the face: every leader from a side gutter would have to cross
# the controls between it and its own.
WATER_HEATER = {
    "kind": "diagram",
    "title": "Water Heater",
    "layout": "panel",
    "parts": [
        {"id": "power", "form": "light", "name": "Electricity indicator"},
        {"id": "onoff", "form": "switch"},
        {"id": "reset", "form": "button"},
        {"id": "timer", "form": "dial"},
        {"id": "warn", "form": "light"},
        {"id": "temp", "form": "gauge", "name": "Temperature"},
    ],
    "labels": [
        {"at": "onoff", "text": "__11__"},
        {"at": "reset", "text": "__12__"},
        {"at": "timer", "text": "__13__"},
        {"at": "warn", "text": "__14__"},
    ],
}

# What the model ACTUALLY returned, live, on 2026-08-27 -- the first drawn
# diagram the engine ever generated (gpt-oss-120b, 37s, `diagram_error` None and
# `validate_practice` None). Kept for the same reason the flow check keeps its
# live chart: a real figure is shaped differently from a hand-built one. This
# one carries its gaps in the part NAMES and prints only a single callout,
# which is the case that proves the layout does not depend on leader lines.
LIVE_SOLAR_HEATER = {
    "kind": "diagram",
    "title": "Cross‑section of an active solar water‑heater",
    "layout": "apparatus",
    "parts": [
        {
            "id": "collector",
            "form": "box",
            "name": "__1__"
        },
        {
            "id": "heat_ex",
            "form": "chamber",
            "name": "Heat exchanger"
        },
        {
            "id": "tank",
            "form": "tank",
            "name": "__2__"
        },
        {
            "id": "pump",
            "form": "pipe",
            "name": "__3__"
        },
        {
            "id": "controller",
            "form": "box",
            "name": "Control unit"
        }
    ],
    "labels": [
        {
            "at": "tank",
            "text": "Insulated tank",
            "side": "left"
        }
    ]
}

# The listening full-test fixture holds four parts and a part holds one
# figure, so the six layouts are proven over two passes rather than four of
# them being proven and two sitting in this file unrendered.
BATCHES = (
    (UNDERSEA_TURBINE, SEWING_MACHINE, AIRPORT_STRATA, OPERATIONAL_CYCLE),
    (DUNG_BEETLES, WATER_HEATER, LIVE_SOLAR_HEATER),
)

# What each figure must have on screen once it is drawn. Gap numbers are
# checked as the exam prints them -- the number, then the dotted rule -- because
# a renderer that dropped the marker entirely would still pass a title check.
EXPECT = {
    "An Undersea Turbine": ["23", "24", "25", "26", "Generator housing", "Sea bed"],
    "Cross-section of a Sewing Machine": ["1", "2", "3", "4", "5", "Thread guide",
                                          "Bobbin"],
    "Cross-section of the airport site": ["10", "11", "12", "Water", "Sand",
                                          "Terminal building"],
    "The Operational Cycle": ["21", "22", "23", "Float dropped into ocean",
                              "Information is analysed"],
    "Dung Beetle Types": ["6", "7", "8", "Dung beetles", "Ball rollers",
                          "South African", "French"],
    "Water Heater": ["11", "12", "13", "14", "Electricity indicator",
                     "Temperature"],
    LIVE_SOLAR_HEATER["title"]: ["1", "2", "3", "Heat exchanger", "Control unit",
                    "Insulated tank"],
}


def build_fixture(figures: tuple[dict, ...]) -> dict:
    data = json.loads(Path("tools/_fixture_fulltest.json").read_text(encoding="utf-8"))
    parts = data["parts"]
    for index, figure in enumerate(figures):
        parts[index] = copy.deepcopy(parts[index])
        parts[index]["visual"] = figure
    # A part left carrying its own figure would render a fifth shape this pass
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
    """Screenshot every diagram; return (title, rendered text) for each."""
    figs = page.locator("figure[aria-label^='Diagram:']")
    out = []
    for i in range(figs.count()):
        fig = figs.nth(i)
        fig.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        name = f"diagram_{theme}_{i}.png"
        fig.screenshot(path=str(OUT / name))
        print(f"  [shot] {name}")
        title = (fig.get_attribute("aria-label") or "")[len("Diagram: "):]
        # Whitespace-collapsed, because a part name too long for its box is
        # wrapped onto two <text> lines: "Float dropped into ocean" reaches
        # inner_text with a newline in the middle of it, and a raw substring
        # match would report a rendering failure for text plainly on screen.
        out.append((title, " ".join(fig.inner_text().split())))
    return out


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"    {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            failures.append(label)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for batch_no, batch in enumerate(BATCHES, start=1):
          fixture = build_fixture(batch)
          for theme in ("light", "dark"):
            print(f"\n== batch {batch_no} / {theme} ==")
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
            # Closed over this batch's fixture rather than reading a module
            # global, so the two passes cannot serve each other's figures.
            # One parameter on purpose: playwright inspects the handler's arity
            # and hands a two-parameter one the Request as its second argument,
            # so `lambda route, data=fixture:` quietly received a Request in
            # place of the fixture.
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
            page.wait_for_selector("figure[aria-label^='Diagram:']", timeout=60000)
            page.wait_for_timeout(600)

            drawn = shoot(page, f"{batch_no}_{theme}")
            check(f"batch {batch_no} every figure drew", len(drawn) == len(batch),
                  f"{len(drawn)} of {len(batch)}")
            for title, body in drawn:
                for want in EXPECT.get(title, []):
                    check(f"{title!r} shows {want!r}", want in body)
            # A figure that fell back to the chart branch or the grid would
            # still render text, so the SVG itself is checked for drawn ink.
            paths = page.locator("figure[aria-label^='Diagram:'] svg path, "
                                 "figure[aria-label^='Diagram:'] svg rect, "
                                 "figure[aria-label^='Diagram:'] svg circle")
            check("the figures drew real shapes", paths.count() >= 5 * len(batch),
                  f"{paths.count()} shapes")
            check("no page or console errors", not errors, "; ".join(errors[:3]))
            ctx.close()
        browser.close()

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'ALL CHECKS PASSED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
