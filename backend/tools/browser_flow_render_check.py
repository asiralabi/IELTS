"""Deterministic render check for the flow chart.

Intercepts /listening/full-test with hand-built charts: a plain chain, one
whose gaps sit mid-sentence beside prose numbers that must NOT be mistaken for
gaps, a long-stepped chart that has to wrap inside its box, and the two real
charts Cambridge prints (13 T1 listening, 21 T4 reading). No LLM call is
involved, so a failure here is the renderer's.

The chart is the one figure the exam prints in BOTH papers and the engine could
not draw at all before this: the reading prompt allowed only a table or a plan,
and `_PART_SPECS[3]` said "No figure is needed - set `visual` to null".

Run with the backend on :8000 and a production frontend build on :3100.
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


# Cambridge IELTS 13 Academic T1, Listening Part 3, Questions 26-30 — the exact
# chain the book prints, with its letter-box answers rewritten as word gaps
# because that is the form the engine generates.
LIVE_LISTENING_FLOW = {
    "kind": "flow",
    "title": "Stages in the experiment",
    "steps": [
        "Select seeds of different __26__",
        "Measure and record the __27__ and size of each one",
        "Decide on the __28__ to be used",
        "Use a different container for each seed and label it",
        "After about 3 weeks, record the plant's __29__",
        "Investigate the __30__",
    ],
}

# Cambridge IELTS 21 T4, Reading Questions 8-10. Three gaps and four boxes is
# the smallest chart in the books, so it is the one that proves the floor.
LIVE_READING_FLOW = {
    "kind": "flow",
    "title": "Generating biogas for domestic use in Dunga",
    "steps": [
        "First, place water hyacinth together with some __8__ into a digester",
        "Leave the mixture until the __9__ is completed",
        "Capture the gas emitted by the digester and use __10__ to transport it "
        "to individual homes",
        "Then use the gas for cooking as well as making water fit for human "
        "consumption",
    ],
}

# A prose number in the same box as a gap. `__3__` is a gap; the "3" in
# "3 weeks" and the "2" in "stage 2" are not, and a renderer that pilled every
# digit would put phantom answer boxes in the middle of a sentence.
PROSE_NUMBERS_FLOW = {
    "kind": "flow",
    "title": "The production of Bakelite",
    "steps": [
        "Phenol and formaldehyde are combined under __4__",
        "The stage 2 resin, called __5__, is cooled for 3 hours until it hardens",
        "The hardened resin is broken up and ground into powder",
        "Fillers such as cotton or asbestos are added to the mixture",
        "The mixture is poured into a mould and heated to produce __6__",
    ],
}

# What a live hosted generation actually returned (2026-08-25, the first
# reading flow chart the engine ever wrote). Kept for the same reason the plan
# check keeps LIVE_DIAGRAM: a real chart is far wordier than a hand-built one.
# Every box here is a full sentence and three of them wrap to three lines,
# which is the whole reason this figure is laid out in HTML rather than the SVG
# the floor plan uses.
WRAPPING_FLOW = {
    "kind": "flow",
    "title": "The Development of the de Havilland Comet",
    "steps": [
        "The initial aim was to create an aircraft that could fly faster and "
        "higher than existing propeller-driven planes.",
        "The design of the Comet began in 1946, when de Havilland's chief "
        "designer, Ronald Bishop, started working on the project.",
        "The team decided to use a new type of material, called 'sandwich' "
        "construction, for the aircraft's fuselage, which provided excellent "
        "__1__.",
        "The Comet's engines were also a major innovation, with the de "
        "Havilland Ghost engine being the first commercial jet engine to be "
        "produced in the UK.",
        "The first prototype of the Comet was completed in 1949, and it made "
        "its maiden flight in July of that year, which was a __2__.",
        "The Comet entered commercial service in 1952, and it quickly became "
        "popular with airlines and passengers alike, due to its high speed and "
        "__3__.",
        "Despite its success, the Comet was not without its problems, with a "
        "series of accidents occurring in the early 1950s, which led to "
        "concerns about the aircraft's __4__.",
    ],
}

CHARTS = (LIVE_LISTENING_FLOW, LIVE_READING_FLOW, PROSE_NUMBERS_FLOW, WRAPPING_FLOW)


def build_fixture() -> dict:
    data = json.loads(Path("tools/_fixture_fulltest.json").read_text(encoding="utf-8"))
    parts = data["parts"]
    for index, chart in enumerate(CHARTS):
        parts[index] = copy.deepcopy(parts[index])
        parts[index]["visual"] = chart
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


def shoot(page: Page, theme: str) -> list[str]:
    """Screenshot every chart and return the text each one rendered."""
    figs = page.locator("figure[aria-label^='Flow chart:']")
    count = figs.count()
    texts = []
    for i in range(count):
        fig = figs.nth(i)
        fig.scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        name = f"flow_{theme}_{i}.png"
        fig.screenshot(path=str(OUT / name))
        print(f"  [shot] {name}")
        texts.append(fig.inner_text())
    return texts


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"    {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            failures.append(label)

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

            texts = shoot(page, theme)
            print(f"[{theme}] flow figures = {len(texts)}")
            check(
                f"[{theme}] every chart rendered",
                len(texts) == len(CHARTS),
                f"{len(texts)} of {len(CHARTS)}",
            )
            if len(texts) != len(CHARTS):
                ctx.close()
                continue

            # Every box is drawn, in order, and no `__n__` marker survives as
            # literal underscores where a gap should be.
            for chart, text in zip(CHARTS, texts):
                title = chart["title"]
                check(f"[{theme}] title: {title[:34]}", title in text)
                check(
                    f"[{theme}] no raw gap marker in {title[:24]}",
                    "__" not in text,
                    text[:60].replace("\n", " / "),
                )
                gaps = [
                    n
                    for step in chart["steps"]
                    for n in re.findall(r"__(\d+)__", step)
                ]
                missing = [g for g in gaps if g not in text]
                check(
                    f"[{theme}] gaps {','.join(gaps)} numbered",
                    not missing,
                    f"missing {missing}",
                )
                boxes = page.locator(
                    f"figure[aria-label='Flow chart: {title}'] li"
                ).count()
                check(
                    f"[{theme}] {len(chart['steps'])} boxes drawn",
                    boxes == len(chart["steps"]),
                    f"saw {boxes}",
                )

            # A prose number must not become a gap. The chart prints "stage 2"
            # and "3 hours" beside real gaps 4, 5 and 6.
            prose = texts[CHARTS.index(PROSE_NUMBERS_FLOW)]
            check(
                f"[{theme}] prose numbers left as prose",
                "stage 2 resin" in prose and "3 hours" in prose,
                prose[:80].replace("\n", " / "),
            )
            ctx.close()
        browser.close()

    print("\nfailures:", failures or "(none)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
