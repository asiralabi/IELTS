"""Does focusing an answer box light that blank on the figure?

A figure is printed once and asked about five times, so "Label 3 on the
diagram" left the student hunting for a small 3 among four others with a clock
running. Focusing an answer box now marks the figure with that question's
number and the matching blank changes colour.

The mechanism is two data attributes and one CSS rule, which means it can break
silently in three ways a unit test cannot see: the blank stops carrying
`data-gap`, the wrapper stops carrying `data-active-gap`, or the rule stops
matching. This checks the rendered page for all three.

Run with the backend on :8000 and a production frontend build on :3100.

Usage: PYTHONIOENCODING=utf-8 python tools/browser_active_gap_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_diagram_render_check import (  # noqa: E402
    BASE,
    OUT,
    auth_state,
    build_fixture,
    serve,
)

FIGURE = {
    "kind": "diagram",
    "title": "An Undersea Turbine",
    "layout": "apparatus",
    "parts": [
        {"id": "rotor", "form": "rotor"},
        {"id": "housing", "form": "chamber", "name": "Generator housing"},
        {"id": "tower", "form": "column"},
        {"id": "seabed", "form": "ground", "name": "Sea bed"},
    ],
    "labels": [
        {"at": "rotor",
         "text": "Sea life not in danger because blades are comparatively __1__",
         "side": "right"},
        {"at": "tower",
         "text": "Whole tower can be raised for __2__ and the removal of seaweed",
         "side": "left"},
        {"at": "seabed", "text": "The tower is anchored to the __3__", "side": "right"},
    ],
}


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            failures.append(label)

    fixture = build_fixture((FIGURE,))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.route("**/listening/full-test", lambda route: serve(route, fixture))
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_state())],
        )
        page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
        page.get_by_role("button", name="Generate full test").click()
        page.wait_for_selector("figure[aria-label^='Diagram:']", timeout=60000)
        page.wait_for_timeout(500)

        marks = page.locator("[data-gap]")
        check("every blank is tagged", marks.count() >= 3, f"{marks.count()} marks")

        wrapper = page.locator("[data-active-gap]")
        check("nothing is lit before a question is focused", wrapper.count() == 0)

        # Focus the answer box for question 2 and read the colour back off the
        # blank. Computed style, not a class name: the rule is what can break.
        # Exact, or "question 2" also matches 20, 22, 24, 26 and 28.
        box = page.get_by_label("Answer to question 2", exact=True)
        box.scroll_into_view_if_needed()
        box.click()
        page.wait_for_timeout(400)

        lit = page.locator("[data-active-gap='2']")
        check("the figure is marked with the focused question", lit.count() >= 1)

        def fill_of(gap: str) -> str:
            el = page.locator(f"[data-active-gap] [data-gap='{gap}']").first
            if el.count() == 0:
                return ""
            return el.evaluate("e => getComputedStyle(e).fill")

        active, quiet = fill_of("2"), fill_of("3")
        check("the focused blank changes colour", bool(active) and active != quiet,
              f"gap2={active} gap3={quiet}")

        page.locator("figure[aria-label^='Diagram:']").first.screenshot(
            path=str(OUT / "active_gap_light.png")
        )
        print(f"  [shot] active_gap_light.png")

        box.blur()
        page.wait_for_timeout(300)
        check("blurring clears it", page.locator("[data-active-gap]").count() == 0)
        ctx.close()
        browser.close()

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'ALL CHECKS PASSED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
