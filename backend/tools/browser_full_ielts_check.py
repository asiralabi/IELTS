"""Live browser check of the five whole-paper flows.

Covers what a student sitting a complete IELTS actually touches: the full
Reading, Listening, Writing and Speaking tests, and the four-skill mock exam.
All of them serve pre-built papers from the warm pool, so this runs in seconds
rather than the hours the papers themselves take to write.

Each flow is driven the same way: open the page, generate, count the sections
and question inputs, answer everything, submit, and read the band back off the
results screen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"

# Pooled papers arrive at once; a cold pool falls back to real generation.
GEN_TIMEOUT_MS = 900_000
CHECK_TIMEOUT_MS = 600_000

ANSWER_INPUT = "input[aria-label^='Answer to question']"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"    {'OK  ' if condition else 'FAIL'} {label}{f'  ({detail})' if detail else ''}")
    if not condition:
        failures.append(f"{label} {detail}".strip())


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


def auth_state() -> dict:
    tokens = httpx.post(
        f"{API}/auth/login", data={"username": EMAIL, "password": PASSWORD}, timeout=15
    )
    tokens.raise_for_status()
    pair = tokens.json()
    me = httpx.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        timeout=15,
    )
    me.raise_for_status()
    return {
        "state": {
            "accessToken": pair["access_token"],
            "refreshToken": pair["refresh_token"],
            "user": me.json(),
        },
        "version": 0,
    }


def answer_everything(page: Page) -> int:
    """Fill every text input and pick the first option of every choice question."""
    inputs = page.locator(ANSWER_INPUT)
    for i in range(inputs.count()):
        inputs.nth(i).fill("A")
    answered = inputs.count()
    for li in page.locator("li").all():
        if li.locator(ANSWER_INPUT).count():
            continue
        option = li.locator("button[type='button']").first
        if option.count():
            try:
                option.click()
                answered += 1
            except Exception:
                pass
    return answered


def run_full_test(page: Page, path: str, noun: str, expected: int, tag: str) -> None:
    print(f"\n[{tag}] {path}")
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    page.get_by_role("button", name="Generate full test").click()
    page.get_by_role("button", name="Submit test", exact=False).wait_for(
        state="visible", timeout=GEN_TIMEOUT_MS
    )
    page.wait_for_timeout(1200)
    shot(page, f"{tag}_answering")

    sections = page.locator(f"text=/^{noun} [1-9]$/").count()
    check(f"{noun.lower()} sections rendered", sections >= expected, f"{sections}")
    answered = answer_everything(page)
    check("questions answerable", answered > 0, f"{answered} answered")

    page.get_by_role("button", name="Submit test", exact=False).click()
    page.get_by_text("correct answers", exact=False).wait_for(
        state="visible", timeout=CHECK_TIMEOUT_MS
    )
    page.wait_for_timeout(1000)
    shot(page, f"{tag}_marked")
    body = page.locator("body").inner_text()
    check("band shown", "Estimated band" in body)


ANSWER = (
    "This is a sample answer written to exercise the examiner end to end. " * 6
)


def run_productive_test(
    page: Page, path: str, tag: str, tabs: tuple[str, ...], placeholder: str
) -> None:
    """Writing and Speaking drive identically: one tab per task/part, one box.

    Both are marked as a whole paper — Writing weighting Task 2 double, Speaking
    averaging its parts — so what matters here is that every tab is reachable
    and the single submit comes back with one band.
    """
    print(f"\n[{tag}] {path}")
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    page.get_by_role("button", name="Generate full test").click()
    page.get_by_role("button", name="Submit test", exact=False).wait_for(
        state="visible", timeout=GEN_TIMEOUT_MS
    )
    page.wait_for_timeout(800)

    for tab in tabs:
        page.get_by_role("button", name=tab, exact=False).first.click()
        page.wait_for_timeout(300)
        box = page.get_by_placeholder(placeholder)
        check(f"{tab} box", box.count() > 0, f"{box.count()}")
        if box.count():
            box.first.fill(ANSWER)
    shot(page, f"{tag}_answering")

    page.get_by_role("button", name="Submit test", exact=False).click()
    page.get_by_text("Estimated band", exact=False).wait_for(
        state="visible", timeout=CHECK_TIMEOUT_MS
    )
    page.wait_for_timeout(800)
    shot(page, f"{tag}_marked")
    body = page.locator("body").inner_text()
    check(f"{tag} band shown", "Estimated band" in body)
    # One band for the paper is the point — per-task cards alone would mean the
    # aggregate never ran.
    for tab in tabs:
        check(f"{tag} {tab} feedback", tab in body)


def run_mock_exam(page: Page) -> None:
    print("\n[mock] /mock-test")
    page.goto(f"{BASE}/mock-test", wait_until="domcontentloaded")
    page.get_by_role("button", name="Generate my exam").click()
    page.get_by_role("button", name="Submit", exact=True).wait_for(
        state="visible", timeout=GEN_TIMEOUT_MS
    )
    page.wait_for_timeout(1200)

    total = 0
    for label, noun, expected in (
        ("Listening", "Part", 4),
        ("Reading", "Passage", 3),
    ):
        page.get_by_role("button", name=label, exact=False).first.click()
        page.wait_for_timeout(600)
        shot(page, f"mock_{label.lower()}")
        sections = page.locator(f"text=/^{noun} [1-9]$/").count()
        check(f"{label.lower()} is a whole paper", sections >= expected, f"{sections}")
        total += answer_everything(page)
    check("mock questions answerable", total > 0, f"{total} answered")

    for label, placeholder in (
        ("Writing", "Write your answer…"),
        ("Speaking", "Type (or dictate) what you would say…"),
    ):
        page.get_by_role("button", name=label, exact=False).first.click()
        page.wait_for_timeout(400)
        boxes = page.get_by_placeholder(placeholder)
        check(f"{label.lower()} boxes", boxes.count() > 0, f"{boxes.count()}")
        for i in range(boxes.count()):
            boxes.nth(i).fill(
                "This is a sample answer written to exercise the examiner end to end. "
                * 6
            )
        shot(page, f"mock_{label.lower()}")

    page.get_by_role("button", name="Submit", exact=True).click()
    page.get_by_text("Overall Band", exact=False).wait_for(
        state="visible", timeout=CHECK_TIMEOUT_MS
    )
    page.wait_for_timeout(1200)
    shot(page, "mock_results")
    body = page.locator("body").inner_text()
    for skill in ("Listening", "Reading", "Writing", "Speaking"):
        check(f"{skill.lower()} band card", skill in body)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_state())],
        )

        run_full_test(page, "/reading/test", "Passage", 3, "reading")
        run_full_test(page, "/listening/test", "Part", 4, "listening")
        run_productive_test(
            page, "/writing/test", "writing", ("Task 1", "Task 2"), "Write your answer…"
        )
        run_productive_test(
            page,
            "/speaking/test",
            "speaking",
            ("Part 1", "Part 2", "Part 3"),
            "Type (or dictate) what you would say…",
        )
        run_mock_exam(page)

        errors = [ln for ln in logs if "[pageerror]" in ln or "[error]" in ln]
        print(f"\n[console] {len(errors)} error(s)")
        for line in errors[-15:]:
            print(f"    {line}")
        check("no page errors", not errors)
        browser.close()

    print(f"\n{'ALL CHECKS PASSED' if not failures else 'FAILURES: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
