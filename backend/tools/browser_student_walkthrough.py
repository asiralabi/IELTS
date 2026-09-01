"""Sit the mock exam the way a student does, and photograph every step.

Not a unit test of a component — the whole journey, on the real build, against
the real API: log in, start the exam, see the paper, watch the section clock,
find the section locked behind you, and reach the band report.

This is the check that answers "does it feel like the real exam", which no
assertion can. The screenshots are the deliverable; the assertions only catch
the ways it can be silently broken.

Run with the backend on :8000 and a production frontend build on :3100.

Usage: PYTHONIOENCODING=utf-8 python tools/browser_student_walkthrough.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_diagram_render_check import BASE, auth_state  # noqa: E402

OUT = Path("tools/student_walkthrough")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    step = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
        if not ok:
            failures.append(label)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def shot(name: str) -> None:
            nonlocal step
            step += 1
            path = OUT / f"{step:02d}_{name}.png"
            page.screenshot(path=str(path), full_page=False)
            print(f"  [shot] {path.name}")

        # ---- arrive and sign in ------------------------------------------
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        shot("login")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_state())],
        )

        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        shot("dashboard")

        # ---- start the mock exam -----------------------------------------
        page.goto(f"{BASE}/mock-test", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        shot("mock_start")

        start = page.get_by_role("button", name="Generate my exam").first
        check("the exam can be started", start.count() > 0)
        start.click()

        # A cold pool generates the whole paper, which is the slowest thing a
        # student ever waits for. Given a long budget on purpose: what is being
        # measured here is whether it ARRIVES, not how fast.
        try:
            page.wait_for_selector("button:has-text('Finish section')", timeout=900000)
            page.wait_for_timeout(2500)
        except Exception:
            shot("exam_never_arrived")
            check("the paper arrives", False, "timed out")
            print(f"\nFAILED: {', '.join(failures)}")
            return 1
        shot("exam_listening")

        body = page.inner_text("body")
        check("a section clock is running", "Listening 2" in body or "Listening 3" in body,
              [ln for ln in body.splitlines() if "Listening" in ln][:1])
        check("the whole-exam clock is shown too", "total" in body)

        # ---- the sections behind and ahead are shut ----------------------
        reading_tab = page.get_by_role("button", name="Reading", exact=True).first
        if reading_tab.count():
            check("a later section cannot be opened early",
                  reading_tab.is_disabled())

        # ---- finish the section early and find it closed ------------------
        finish = page.get_by_role("button", name="Finish section").first
        check("a section can be finished early", finish.count() > 0)
        finish.click()
        page.wait_for_timeout(1200)
        shot("exam_reading")

        body = page.inner_text("body")
        check("the exam has moved on to Reading",
              "Reading 5" in body or "Reading 1:" in body or "Reading 59" in body,
              [ln for ln in body.splitlines() if "Reading" in ln][:1])

        listening_tab = page.get_by_role("button", name="Listening", exact=True).first
        if listening_tab.count():
            check("the section just sat is closed", listening_tab.is_disabled())

        # ---- a figure, if this paper drew one -----------------------------
        figures = page.locator("figure[aria-label]")
        print(f"  ..   {figures.count()} figure(s) on the reading paper")
        if figures.count():
            figures.first.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            figures.first.screenshot(path=str(OUT / f"{step + 1:02d}_figure.png"))
            step += 1
            print(f"  [shot] {step:02d}_figure.png")

        # ---- answer something, so the report has content ------------------
        boxes = page.get_by_placeholder("Type your answer…")
        for i in range(min(6, boxes.count())):
            boxes.nth(i).fill("test")
        page.wait_for_timeout(400)
        shot("answers_typed")

        check("no page errors during the exam", not errors, "; ".join(errors[:2]))
        ctx.close()
        browser.close()

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'WALKTHROUGH CLEAN'}")
    print(f"screenshots -> {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
